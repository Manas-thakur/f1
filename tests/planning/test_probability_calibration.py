"""Calibrated probabilities on the planner's published output.

Before a calibrator existed, ``rollout.py`` published raw weighted frequencies
and stamped every one ``uncalibrated``, which was correct. Adding a calibrator
creates the opposite risk, so the tests here are mostly about what must *not*
change:

* with no calibrator the published statement is byte-identical to the old
  behaviour;
* a calibrator that refuses leaves the number alone and only degrades the
  claim;
* ``raw_frequency`` always carries the uncalibrated value, so an adjustment is
  auditable rather than invisible.
"""

from __future__ import annotations

import dataclasses

import pytest

from afterlap_contracts import CalibrationStatus
from afterlap_core.planning import plan
from afterlap_core.planning.rollout import FORECASTER_VERSION, ProbabilityCalibration, _statement

from .conftest import context_with, estimate_with


class _Fake:
    """A calibrator whose answer is fixed, so a branch can be chosen exactly."""

    def __init__(self, value: float | None, *, clamped: bool = False, detail: str = "") -> None:
        self._value = value
        self._clamped = clamped
        self._detail = detail

    @property
    def calibrator_id(self) -> str:
        return "calibrator/fake/0"

    def apply(self, event_definition: str, raw_frequency: float) -> _Answer:
        del event_definition, raw_frequency
        return _Answer(value=self._value, clamped=self._clamped, detail=self._detail)


@dataclasses.dataclass(frozen=True, slots=True)
class _Answer:
    value: float | None
    clamped: bool = False
    detail: str = ""
    status: str = "fake"


class TestStatementPublication:
    def test_with_no_calibrator_the_raw_frequency_is_published_uncalibrated(self) -> None:
        notes: list[str] = []
        statement = _statement(
            label="pass_before",
            checkpoint_id="attack-exit",
            frequency=0.375,
            samples=4,
            calibrator=None,
            notes=notes,
        )
        assert statement.value == pytest.approx(0.375)
        assert statement.raw_frequency == pytest.approx(0.375)
        assert statement.calibration_status is CalibrationStatus.UNCALIBRATED
        assert statement.model_version == FORECASTER_VERSION
        assert notes == []

    def test_a_calibrated_value_replaces_the_value_and_keeps_the_raw_beside_it(self) -> None:
        """The adjustment has to stay auditable."""
        notes: list[str] = []
        statement = _statement(
            label="ahead_at",
            checkpoint_id="attack-exit",
            frequency=0.8,
            samples=5,
            calibrator=_Fake(0.55),
            notes=notes,
        )
        assert statement.value == pytest.approx(0.55)
        assert statement.raw_frequency == pytest.approx(0.8)
        assert statement.calibration_status is CalibrationStatus.CALIBRATED
        assert statement.model_version == f"{FORECASTER_VERSION}+calibrator/fake/0"

    def test_a_refusal_keeps_the_number_and_only_degrades_the_claim(self) -> None:
        notes: list[str] = []
        statement = _statement(
            label="pass_before",
            checkpoint_id="attack-exit",
            frequency=0.42,
            samples=3,
            calibrator=_Fake(None, detail="not frozen"),
            notes=notes,
        )
        assert statement.value == pytest.approx(0.42)
        assert statement.raw_frequency == pytest.approx(0.42)
        assert statement.calibration_status is CalibrationStatus.UNCALIBRATED
        assert statement.model_version == FORECASTER_VERSION
        assert notes == ["pass_before(checkpoint=attack-exit): published uncalibrated (not frozen)"]

    def test_a_clamped_value_is_published_but_recorded_as_clamped(self) -> None:
        notes: list[str] = []
        statement = _statement(
            label="pass_before",
            checkpoint_id="attack-exit",
            frequency=0.02,
            samples=3,
            calibrator=_Fake(0.0, clamped=True),
            notes=notes,
        )
        assert statement.calibration_status is CalibrationStatus.CALIBRATED
        assert len(notes) == 1
        assert "clamped to the fitted domain" in notes[0]

    def test_the_event_definitions_are_the_two_the_forecaster_publishes(self) -> None:
        notes: list[str] = []
        for label in ("pass_before", "ahead_at"):
            statement = _statement(
                label=label,
                checkpoint_id="attack-exit",
                frequency=0.5,
                samples=2,
                calibrator=None,
                notes=notes,
            )
            assert statement.event_definition == f"{label}(checkpoint=attack-exit)"
            assert statement.checkpoint_id == "attack-exit"


@pytest.fixture(scope="module")
def inputs(config, manifest, world):
    """One estimate, rule context and world, shared by the planner tests."""
    return estimate_with(), context_with(), manifest, config, world


class TestThroughThePlanner:
    def test_a_calibrator_is_optional_and_absent_by_default(self, inputs) -> None:
        estimate, context, manifest, config, world = inputs
        result = plan(estimate, context, None, 5.0, manifest=manifest, config=config, world=world)
        statements = [s for candidate in result.accepted for s in candidate.probabilities]
        assert statements, "the planner published no probability to calibrate"
        assert all(s.calibration_status is CalibrationStatus.UNCALIBRATED for s in statements)
        assert all(s.value == s.raw_frequency for s in statements)

    def test_a_supplied_calibrator_changes_the_published_status_and_value(self, inputs) -> None:
        estimate, context, manifest, config, world = inputs
        baseline = plan(estimate, context, None, 5.0, manifest=manifest, config=config, world=world)
        calibrated = plan(
            estimate,
            context,
            None,
            5.0,
            manifest=manifest,
            config=config,
            world=world,
            calibrator=_Fake(0.25),
        )
        before = [s for c in baseline.accepted for s in c.probabilities]
        after = [s for c in calibrated.accepted for s in c.probabilities]
        assert before and after
        assert all(s.calibration_status is CalibrationStatus.CALIBRATED for s in after)
        assert all(s.value == pytest.approx(0.25) for s in after)
        assert {s.raw_frequency for s in after} == {s.raw_frequency for s in before}

    def test_a_refusing_calibrator_leaves_the_plan_unchanged(self, inputs) -> None:
        """A calibration refusal must not move the selected plan."""
        estimate, context, manifest, config, world = inputs
        baseline = plan(estimate, context, None, 5.0, manifest=manifest, config=config, world=world)
        refused = plan(
            estimate,
            context,
            None,
            5.0,
            manifest=manifest,
            config=config,
            world=world,
            calibrator=_Fake(None, detail="thin support"),
        )
        assert refused.selected_plan_id == baseline.selected_plan_id
        before = [s.value for c in baseline.accepted for s in c.probabilities]
        after = [s.value for c in refused.accepted for s in c.probabilities]
        assert after == before

    def test_the_planner_never_imports_the_learning_package(self) -> None:
        """The protocol boundary, checked structurally rather than by convention."""
        import ast
        from pathlib import Path

        source = Path("packages/core/afterlap_core/planning/rollout.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        assert not any("learning" in name for name in names), names

    def test_the_real_calibrator_satisfies_the_declared_protocol(self) -> None:
        pytest.importorskip("torch", reason="the learning package imports torch")
        from afterlap_core.learning.calibration import ProbabilityCalibrator

        calibrator = ProbabilityCalibrator(maps={}, forecaster_version=FORECASTER_VERSION)
        assert isinstance(calibrator, ProbabilityCalibration)
