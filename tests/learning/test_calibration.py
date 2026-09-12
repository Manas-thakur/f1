"""The probability calibrator, and every case where it must refuse.

``rollout.py`` stamped every published probability ``uncalibrated`` and said
why: no calibrator existed. Adding one creates a new and worse failure mode --
a raw frequency dressed up as a calibrated probability by a map that had no
evidence behind it. So most of this file is refusals, and the two tests that
check the fit itself check that it *recovers a known distortion* rather than
merely that it runs.
"""

from __future__ import annotations

import dataclasses
from itertools import pairwise

import numpy as np
import pytest

from afterlap_contracts import CalibrationStatus
from afterlap_core.learning.calibration import (
    CALIBRATOR_SCHEMA,
    CalibrationSample,
    CalibratorStatus,
    ProbabilityCalibrator,
    fit_calibrator,
    isotonic_fit,
)

EVENT = "pass_before(checkpoint=attack-exit)"
OTHER = "ahead_at(checkpoint=attack-exit)"


def _samples(
    *,
    episodes: int = 40,
    per_episode: int = 3,
    seed: int = 7,
    distortion=lambda raw: raw**2,
    event: str = EVENT,
) -> list[CalibrationSample]:
    """A forecaster whose stated frequency is a known distortion of the truth."""
    rng = np.random.default_rng(seed)
    rows: list[CalibrationSample] = []
    for episode in range(episodes):
        for _ in range(per_episode):
            raw = float(rng.uniform(0.05, 0.95))
            rows.append(
                CalibrationSample(
                    event_definition=event,
                    raw_frequency=raw,
                    outcome=int(rng.uniform() < distortion(raw)),
                    episode_id=f"scenario:{episode}",
                    scenario_id="scenario",
                    checkpoint_id="attack-exit",
                )
            )
    return rows


def _frozen(calibrator: ProbabilityCalibrator) -> ProbabilityCalibrator:
    return dataclasses.replace(calibrator, frozen_before_final_test=True)


class TestIsotonicFit:
    def test_an_already_monotone_sequence_is_returned_unchanged(self) -> None:
        x = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
        y = np.array([0.0, 0.2, 0.4, 0.8, 1.0])
        knots_x, knots_y = isotonic_fit(x, y)
        np.testing.assert_allclose(knots_x, x)
        np.testing.assert_allclose(knots_y, y)

    def test_a_violation_is_pooled_to_its_weighted_mean(self) -> None:
        x = np.array([0.0, 0.5, 1.0])
        y = np.array([0.0, 1.0, 0.0])
        _, knots_y = isotonic_fit(x, y)
        assert knots_y[0] == pytest.approx(0.0)
        assert knots_y[1] == pytest.approx(0.5)
        assert knots_y[2] == pytest.approx(0.5)

    def test_ties_in_the_forecast_receive_one_value(self) -> None:
        """Two identical forecasts must not be calibrated differently."""
        x = np.array([0.4, 0.4, 0.4, 0.9])
        y = np.array([0.0, 1.0, 1.0, 1.0])
        knots_x, knots_y = isotonic_fit(x, y)
        assert list(knots_x) == [0.4, 0.9]
        assert knots_y[0] == pytest.approx(2.0 / 3.0)

    def test_the_fit_is_never_decreasing(self) -> None:
        rng = np.random.default_rng(3)
        x = np.sort(rng.uniform(0.0, 1.0, size=60))
        y = rng.integers(0, 2, size=60).astype(float)
        _, knots_y = isotonic_fit(x, y)
        assert all(a <= b + 1e-12 for a, b in pairwise(knots_y))

    def test_a_non_positive_weight_is_refused(self) -> None:
        with pytest.raises(ValueError, match="weights must be positive"):
            isotonic_fit(np.array([0.0, 1.0]), np.array([0.0, 1.0]), np.array([1.0, 0.0]))


@pytest.fixture(scope="module")
def fit():
    """One fit of the known distortion, shared by the recovery tests."""
    return fit_calibrator(_samples(), forecaster_version="test-v1", seed=3, min_support=10)


@pytest.fixture(scope="module")
def calibrator(fit):
    return fit.calibrator


@pytest.fixture(scope="module")
def frozen_calibrator(calibrator):
    return _frozen(calibrator)


class TestTheFitRecoversAKnownDistortion:
    def test_the_held_out_brier_score_improves(self, fit) -> None:
        """The only evidence a calibrator is worth applying."""
        assert fit.before[EVENT]["brier_score"] > fit.after[EVENT]["brier_score"]

    def test_an_overconfident_forecast_is_pulled_down(self, fit) -> None:
        frozen = _frozen(fit.calibrator)
        for raw in (0.4, 0.5, 0.6):
            calibrated = frozen.apply(EVENT, raw)
            assert calibrated.value is not None
            assert calibrated.value < raw

    def test_the_calibrated_map_is_monotone(self, fit) -> None:
        """A calibration step must never reorder two forecasts."""
        frozen = _frozen(fit.calibrator)
        values = [frozen.apply(EVENT, raw).value for raw in np.linspace(0.0, 1.0, 40)]
        assert all(a is not None and b is not None for a, b in pairwise(values))
        assert all(a <= b + 1e-12 for a, b in pairwise(values))

    def test_the_split_is_by_episode_and_both_sides_are_non_empty(self, fit) -> None:
        assert fit.episode_count >= 1
        assert fit.holdout_episode_count >= 1
        assert fit.episode_count + fit.holdout_episode_count == 40

    def test_the_report_it_carries_is_the_held_out_one(self, fit) -> None:
        report = fit.calibrator.report_for(EVENT)
        assert report is not None
        assert report.event_definition == EVENT
        assert report.support_count > 0


class TestRefusals:
    def test_an_empty_sample_set_is_refused(self) -> None:
        with pytest.raises(ValueError, match="no samples"):
            fit_calibrator([], forecaster_version="test-v1")

    def test_a_single_episode_cannot_be_split(self) -> None:
        """A calibrator scored on its own fitting set reports training error."""
        rows = _samples(episodes=1, per_episode=60)
        with pytest.raises(ValueError, match="at least two episodes"):
            fit_calibrator(rows, forecaster_version="test-v1")

    def test_thin_evidence_yields_no_map_and_a_stated_reason(self) -> None:
        rows = _samples(episodes=4, per_episode=2)
        fit = fit_calibrator(rows, forecaster_version="test-v1", min_support=30)
        assert fit.calibrator is None
        assert "below the declared minimum 30" in fit.refusals[EVENT]

    def test_a_single_class_set_is_refused_rather_than_fitted_flat(self) -> None:
        """A constant fit on one class would report a perfect Brier score."""
        rows = [dataclasses.replace(sample, outcome=1) for sample in _samples(episodes=30, per_episode=3)]
        fit = fit_calibrator(rows, forecaster_version="test-v1", min_support=10)
        assert fit.calibrator is None
        assert "same class" in fit.refusals[EVENT]

    def test_one_event_can_be_calibrated_while_another_is_refused(self) -> None:
        rows = [*_samples(episodes=40, event=EVENT), *_samples(episodes=40, per_episode=1, event=OTHER)[:4]]
        fit = fit_calibrator(rows, forecaster_version="test-v1", seed=5, min_support=20)
        assert fit.calibrator is not None
        assert EVENT in fit.calibrator.event_definitions
        assert OTHER not in fit.calibrator.event_definitions
        assert OTHER in fit.refusals

    def test_an_out_of_range_frequency_is_refused_at_construction(self) -> None:
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            CalibrationSample(
                event_definition=EVENT,
                raw_frequency=1.4,
                outcome=1,
                episode_id="e",
                scenario_id="s",
            )

    def test_a_non_binary_label_is_refused_at_construction(self) -> None:
        with pytest.raises(ValueError, match="0 or 1"):
            CalibrationSample(
                event_definition=EVENT,
                raw_frequency=0.5,
                outcome=2,
                episode_id="e",
                scenario_id="s",
            )


class TestApplyGates:
    def test_an_unfrozen_calibrator_publishes_nothing(self, calibrator) -> None:
        """``frozen_before_final_test`` is the gate, exactly as for support."""
        result = calibrator.apply(EVENT, 0.5)
        assert result.value is None
        assert result.status == CalibratorStatus.NOT_FROZEN
        assert result.calibrated is False
        assert result.contract_status is CalibrationStatus.UNCALIBRATED

    def test_an_uncalibrated_event_is_named_not_guessed(self, calibrator) -> None:
        result = _frozen(calibrator).apply("finish_ahead(checkpoint=x)", 0.5)
        assert result.value is None
        assert result.status == CalibratorStatus.EVENT_NOT_CALIBRATED

    def test_a_non_finite_frequency_is_refused(self, calibrator) -> None:
        result = _frozen(calibrator).apply(EVENT, float("nan"))
        assert result.value is None
        assert result.status == CalibratorStatus.NON_FINITE

    def test_support_below_the_declared_minimum_refuses(self, calibrator) -> None:
        strict = dataclasses.replace(calibrator, frozen_before_final_test=True, min_support=10_000)
        result = strict.apply(EVENT, 0.5)
        assert result.value is None
        assert result.status == CalibratorStatus.INSUFFICIENT_SUPPORT
        assert result.support_count is not None

    def test_extrapolation_is_clamped_and_flagged_never_silent(self, calibrator) -> None:
        frozen = _frozen(calibrator)
        inside = frozen.apply(EVENT, 0.5)
        outside = frozen.apply(EVENT, 0.0)
        assert inside.clamped is False
        assert outside.clamped is True
        assert "clamped" in outside.detail
        assert outside.value is not None

    def test_an_unavailable_value_is_never_zero(self, calibrator) -> None:
        """The null-not-zero rule, applied to a probability."""
        result = calibrator.apply(EVENT, 0.5)
        assert result.value is None
        assert result.value != 0.0


class TestSerialisation:
    def test_a_round_trip_preserves_every_calibrated_value(self, frozen_calibrator) -> None:
        calibrator = frozen_calibrator
        restored = ProbabilityCalibrator.from_dict(calibrator.as_dict())
        assert restored is not None
        for raw in np.linspace(0.0, 1.0, 25):
            assert restored.apply(EVENT, raw).value == calibrator.apply(EVENT, raw).value

    def test_the_serialised_form_declares_its_schema(self, frozen_calibrator) -> None:
        payload = frozen_calibrator.as_dict()
        assert payload["schema"] == CALIBRATOR_SCHEMA
        assert payload["status"] == "available"
        assert payload["method"] == "isotonic_pav"

    def test_the_unavailable_placeholder_loads_as_absent(self) -> None:
        """``write_bundle`` writes this when no calibration set exists."""
        assert ProbabilityCalibrator.from_dict({"status": "unavailable"}) is None
        assert ProbabilityCalibrator.from_dict({}) is None

    def test_an_unknown_schema_loads_as_absent_rather_than_raising(self) -> None:
        assert ProbabilityCalibrator.from_dict({"schema": "something/else"}) is None

    def test_the_content_hash_ignores_the_timestamp_but_not_the_map(self, frozen_calibrator) -> None:
        same = dataclasses.replace(frozen_calibrator, fitted_at="1999-01-01T00:00:00Z")
        assert same.content_hash() == frozen_calibrator.content_hash()
        moved = dataclasses.replace(frozen_calibrator, min_support=999)
        assert moved.content_hash() != frozen_calibrator.content_hash()
