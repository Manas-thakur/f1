"""Uncertainty and calibration.

The two properties that matter most here are negative ones: the resampler must
refuse correlated telemetry frames, and a single-class calibration set must
produce a reason rather than a score. Both are asserted as refusals, not as
conventions.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from afterlap_contracts import BenchmarkComparison, CalibrationStatus
from afterlap_core.evaluation.statistics import (
    ELAPSED_TIME,
    UTILITY,
    CorrelatedSampleError,
    EvaluationUnit,
    PairedSample,
    TelemetryFrameSeries,
    assess_calibration,
    brier_score,
    hierarchical_paired_bootstrap,
    log_loss,
    reliability_bins,
    summarise,
)


def _synthetic_sample(
    *,
    effect: float,
    scenarios: int = 20,
    seeds: int = 5,
    noise: float = 1.0,
    seed: int = 7,
) -> PairedSample:
    """Paired units where ``candidate - reference`` has a known mean effect.

    A per-scenario offset is shared by both arms, so the *unpaired* variance is
    large while the paired difference is tight. That is exactly the structure a
    paired design exists to exploit, and it makes the test sensitive to a
    resampler that broke the pairing.
    """
    rng = np.random.default_rng(seed)
    units: list[EvaluationUnit] = []
    for index in range(scenarios):
        scenario_offset = rng.normal(0.0, 25.0)
        for seed_index in range(seeds):
            reference = scenario_offset + rng.normal(0.0, noise)
            candidate = reference + effect + rng.normal(0.0, noise * 0.2)
            units.append(
                EvaluationUnit(
                    scenario_id=f"scenario-{index:02d}",
                    seed=1000 + seed_index,
                    family="family-a" if index % 2 == 0 else "family-b",
                    values={"candidate": candidate, "reference": reference},
                )
            )
    return PairedSample(metric=UTILITY, units=tuple(units))


class TestPairedBootstrap:
    def test_it_recovers_a_known_effect_size(self) -> None:
        effect = 2.5
        sample = _synthetic_sample(effect=effect)
        result = hierarchical_paired_bootstrap(sample, "candidate", "reference", iterations=2000, seed=11)
        assert result.difference_mean == pytest.approx(effect, abs=0.15)
        assert result.ci_low < effect < result.ci_high
        assert result.interval_excludes_zero
        assert result.favours_controller
        assert result.scenario_count == 20
        assert result.seed_count == 5
        assert result.unit_count == 100

    def test_a_zero_effect_produces_an_interval_that_contains_zero(self) -> None:
        sample = _synthetic_sample(effect=0.0)
        result = hierarchical_paired_bootstrap(sample, "candidate", "reference", iterations=2000, seed=11)
        assert result.ci_low <= 0.0 <= result.ci_high
        assert not result.interval_excludes_zero
        assert not result.favours_controller

    def test_the_direction_of_the_metric_decides_what_favourable_means(self) -> None:
        """The same +2.5 difference favours the controller on utility and not on time."""
        units = _synthetic_sample(effect=2.5).units
        as_utility = PairedSample(metric=UTILITY, units=units)
        as_time = PairedSample(metric=ELAPSED_TIME, units=units)
        utility = hierarchical_paired_bootstrap(as_utility, "candidate", "reference", iterations=800, seed=3)
        elapsed = hierarchical_paired_bootstrap(as_time, "candidate", "reference", iterations=800, seed=3)
        assert utility.difference_mean == pytest.approx(elapsed.difference_mean)
        assert utility.favours_controller
        assert not elapsed.favours_controller

    def test_the_interval_always_contains_its_own_point_estimate(self) -> None:
        sample = _synthetic_sample(effect=1.0, scenarios=6, seeds=2)
        result = hierarchical_paired_bootstrap(sample, "candidate", "reference", iterations=500, seed=5)
        assert result.ci_low <= result.difference_mean <= result.ci_high
        # The contract enforces the same thing, so this always constructs.
        contract = result.to_contract()
        assert contract.ci_low <= contract.difference_mean <= contract.ci_high

    def test_pairing_survives_a_large_shared_scenario_offset(self) -> None:
        """An unpaired estimator would be swamped by the +/-25 unit offsets."""
        sample = _synthetic_sample(effect=1.0, noise=0.5)
        result = hierarchical_paired_bootstrap(sample, "candidate", "reference", iterations=2000, seed=13)
        width = result.ci_high - result.ci_low
        assert width < 1.0, f"paired interval unexpectedly wide ({width}); pairing may be broken"

    def test_zero_seed_variance_is_reported_not_hidden(self) -> None:
        """Identical seeds inside a scenario make the seed level contribute nothing."""
        units = tuple(
            EvaluationUnit(
                scenario_id=f"s{index}",
                seed=seed,
                family="f",
                values={"candidate": 10.0 + index, "reference": 8.0 + index},
            )
            for index in range(5)
            for seed in (1, 2, 3)
        )
        result = hierarchical_paired_bootstrap(
            PairedSample(metric=UTILITY, units=units),
            "candidate",
            "reference",
            iterations=400,
            seed=2,
        )
        assert result.degenerate_seed_variance
        assert result.within_scenario_variance == 0.0

    def test_missing_controllers_are_skipped_not_imputed(self) -> None:
        units = (
            EvaluationUnit("s0", 1, "f", {"candidate": 3.0, "reference": 1.0}),
            EvaluationUnit("s0", 2, "f", {"reference": 1.0}, missing=("candidate",)),
            EvaluationUnit("s1", 1, "f", {"candidate": 5.0, "reference": 1.0}),
        )
        sample = PairedSample(metric=UTILITY, units=units)
        result = hierarchical_paired_bootstrap(sample, "candidate", "reference", iterations=200, seed=1)
        assert result.unit_count == 2
        assert result.difference_mean == pytest.approx(3.0)


class TestCorrelatedFramesAreRefused:
    def test_a_bare_sequence_of_observations_is_refused(self) -> None:
        frames = [1.0, 1.1, 1.2, 1.3, 1.4]
        with pytest.raises(CorrelatedSampleError, match="PairedSample"):
            hierarchical_paired_bootstrap(frames, "candidate", "reference")

    def test_a_sequence_of_frame_series_is_refused(self) -> None:
        series = [
            TelemetryFrameSeries("s0", 1, "candidate", (1.0, 1.1, 1.2)),
            TelemetryFrameSeries("s0", 1, "reference", (0.9, 1.0, 1.1)),
        ]
        with pytest.raises(CorrelatedSampleError):
            hierarchical_paired_bootstrap(series, "candidate", "reference")

    def test_repeating_one_episode_as_many_units_is_refused(self) -> None:
        """The shape a caller reaches for when inflating a sample size."""
        units = tuple(
            EvaluationUnit("s0", 1, "f", {"candidate": 1.0 + i * 0.01, "reference": 1.0}) for i in range(50)
        )
        with pytest.raises(CorrelatedSampleError, match="more than once"):
            PairedSample(metric=UTILITY, units=units)

    def test_frames_can_only_enter_through_a_stated_reduction(self) -> None:
        series = {
            "candidate": TelemetryFrameSeries("s0", 1, "candidate", (2.0, 4.0, 6.0)),
            "reference": TelemetryFrameSeries("s0", 1, "reference", (1.0, 1.0, 1.0)),
        }
        unit = EvaluationUnit.from_frame_series(
            scenario_id="s0",
            seed=1,
            family="f",
            series=series,
            reducer=lambda values: float(np.mean(values)),
        )
        assert unit.values == {"candidate": 4.0, "reference": 1.0}
        assert unit.key == ("s0", 1)

    def test_a_reduction_refuses_frames_from_another_episode(self) -> None:
        series = {"candidate": TelemetryFrameSeries("s9", 7, "candidate", (1.0,))}
        with pytest.raises(CorrelatedSampleError, match="belongs to"):
            EvaluationUnit.from_frame_series(
                scenario_id="s0",
                seed=1,
                family="f",
                series=series,
                reducer=lambda values: float(np.mean(values)),
            )


class TestDistributionsAndPoorTail:
    def test_the_summary_reports_the_tail_not_only_the_mean(self) -> None:
        units = tuple(
            EvaluationUnit(f"s{index}", 1, "f", {"candidate": 1.0 if index else -20.0, "reference": 0.0})
            for index in range(20)
        )
        summary = summarise(PairedSample(metric=UTILITY, units=units), "candidate", "reference", alpha=0.9)
        assert summary.count == 20
        assert summary.mean == pytest.approx((19 * 1.0 - 20.0) / 20.0)
        # CVaR at alpha = 0.9 over 20 units averages the worst ceil(0.1 * 20) = 2:
        # (-20 + 1) / 2 = -9.5. The mean alone is -0.05, which hides the outlier.
        assert summary.poor_tail_mean == pytest.approx(-9.5)
        assert summary.worst_cases[0][2] == pytest.approx(-20.0)

    def test_the_tail_follows_the_metric_direction(self) -> None:
        units = tuple(
            EvaluationUnit(f"s{index}", 1, "f", {"candidate": 1.0 if index else 40.0, "reference": 0.0})
            for index in range(20)
        )
        # On elapsed time, +40 s is the *worst* case, not the best, so the two
        # worst units are 40 and 1, averaging 20.5.
        summary = summarise(
            PairedSample(metric=ELAPSED_TIME, units=units), "candidate", "reference", alpha=0.9
        )
        assert summary.poor_tail_mean == pytest.approx(20.5)
        assert summary.worst_cases[0][2] == pytest.approx(40.0)


class TestCalibration:
    def test_a_set_with_only_positives_is_insufficient_not_scored(self) -> None:
        predictions = [0.2, 0.4, 0.6, 0.8, 0.9, 0.95, 0.99, 0.3, 0.55, 0.7, 0.65, 0.85]
        labels = [1] * len(predictions)
        assessment = assess_calibration(
            predictions, labels, event_definition="pass_retained_at_counterattack_exit"
        )
        assert not assessment.sufficient
        assert assessment.report.status is CalibrationStatus.UNAVAILABLE
        assert assessment.report.brier_score is None
        assert assessment.report.log_loss is None
        assert assessment.report.support_count == len(predictions)
        assert "positive" in (assessment.reason or "")

    def test_a_set_with_only_negatives_is_also_insufficient(self) -> None:
        predictions = [0.1] * 12
        assessment = assess_calibration(predictions, [0] * 12, event_definition="pass_retained")
        assert not assessment.sufficient
        assert assessment.report.status is CalibrationStatus.UNAVAILABLE
        assert "negative" in (assessment.reason or "")

    def test_an_empty_set_is_unavailable_with_zero_support(self) -> None:
        assessment = assess_calibration([], [], event_definition="pass_retained")
        assert assessment.report.status is CalibrationStatus.UNAVAILABLE
        assert assessment.report.support_count == 0

    def test_thin_support_is_declared_rather_than_scored(self) -> None:
        assessment = assess_calibration(
            [0.2, 0.8, 0.5], [0, 1, 1], event_definition="pass_retained", min_support=10
        )
        assert not assessment.sufficient
        assert "below the declared minimum" in (assessment.reason or "")

    def test_a_well_calibrated_forecast_is_scored_and_calibrated(self) -> None:
        rng = np.random.default_rng(4)
        predictions = rng.uniform(0.05, 0.95, size=4000)
        labels = (rng.uniform(size=predictions.size) < predictions).astype(int)
        assessment = assess_calibration(predictions, labels, event_definition="pass_retained", bins=10)
        assert assessment.sufficient
        assert assessment.report.status is CalibrationStatus.CALIBRATED
        assert assessment.report.brier_score is not None
        assert assessment.report.support_count == 4000
        assert len(assessment.report.bin_counts) == len(assessment.report.bin_observed)
        assert sum(assessment.report.bin_counts) == 4000

    def test_a_badly_calibrated_forecast_is_scored_but_not_called_calibrated(self) -> None:
        rng = np.random.default_rng(5)
        truth = rng.uniform(size=2000)
        labels = (rng.uniform(size=2000) < truth).astype(int)
        # A forecaster that is systematically over-confident.
        predictions = np.clip(truth + 0.3, 0.0, 1.0)
        assessment = assess_calibration(predictions, labels, event_definition="pass_retained", bins=10)
        assert assessment.sufficient
        assert assessment.report.status is CalibrationStatus.UNCALIBRATED
        assert assessment.report.brier_score is not None
        assert "reliability gap" in (assessment.reason or "")

    def test_brier_and_log_loss_match_hand_computed_values(self) -> None:
        # Brier: ((0.8-1)^2 + (0.3-0)^2) / 2 = (0.04 + 0.09) / 2 = 0.065
        assert brier_score([0.8, 0.3], [1, 0]) == pytest.approx(0.065, abs=1e-12)
        # Log loss: -(ln 0.5 + ln 0.5) / 2 = ln 2 = 0.6931471805599453
        assert log_loss([0.5, 0.5], [1, 0]) == pytest.approx(0.6931471805599453, abs=1e-12)

    def test_empty_bins_are_omitted_rather_than_zero_filled(self) -> None:
        counts, predicted, observed = reliability_bins([0.05, 0.95], [0, 1], bins=10)
        assert counts == (1, 1)
        assert len(predicted) == len(observed) == 2


class TestContractRefusals:
    def test_an_interval_excluding_its_point_estimate_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="does not contain its own point estimate"):
            BenchmarkComparison(
                controller="candidate",
                reference="mpc_only",
                metric="utility",
                unit="1",
                difference_mean=2.0,
                ci_low=0.1,
                ci_high=1.5,
                coverage=0.95,
                scenario_count=20,
                seed_count=5,
                favours_controller=True,
            )

    def test_a_valid_interval_is_accepted(self) -> None:
        comparison = BenchmarkComparison(
            controller="candidate",
            reference="mpc_only",
            metric="utility",
            unit="1",
            difference_mean=2.0,
            ci_low=0.1,
            ci_high=3.5,
            coverage=0.95,
            scenario_count=20,
            seed_count=5,
            favours_controller=True,
        )
        assert comparison.ci_low <= comparison.difference_mean <= comparison.ci_high
