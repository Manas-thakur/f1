"""The independent ledger must be independent, correct, and have teeth.

Four things are proven here:

1. the reconstruction reproduces a hand-computed constant-power case, with the
   expected numbers written out arithmetically in the test rather than obtained
   by calling the code under test;
2. a deliberately corrupted trajectory is *detected* — this is the test that
   proves the checker can fail;
3. the line-crossing reference recovers an analytically known crossing;
4. the reconstruction runs against real A03 trajectories and the measured
   discrepancy is asserted against the frozen tolerances.

The first test in the file is structural: it reads this package's own source and
fails if any module imports the simulator's physics or battery code. Without
that, "independent" is a claim rather than a property.
"""

from __future__ import annotations

import math
import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from afterlap_core.evaluation import independent_ledger as il
from afterlap_core.simulation import Simulator, load_bundle

from .conftest import RECORD_DT_S

if TYPE_CHECKING:
    from afterlap_core.simulation.config import ScenarioBundle


_EVALUATION_DIR = Path(il.__file__).parent
_FORBIDDEN_IMPORTS = (
    r"from\s+\.\.simulation\s+import\s+physics",
    r"from\s+\.\.simulation\.physics\s+import",
    r"from\s+\.\.simulation\.battery\s+import",
    r"from\s+afterlap_core\.simulation\.physics\s+import",
    r"from\s+afterlap_core\.simulation\.battery\s+import",
    r"import\s+afterlap_core\.simulation\.physics",
    r"import\s+afterlap_core\.simulation\.battery",
)


class TestStructuralIndependence:
    def test_the_ledger_never_imports_the_simulators_physics_or_battery(self) -> None:
        source = Path(il.__file__).read_text(encoding="utf-8")
        for pattern in _FORBIDDEN_IMPORTS:
            assert re.search(pattern, source) is None, (
                f"independent_ledger.py imports the code it audits ({pattern}); "
                "a shared defect would then cancel out"
            )

    def test_the_pattern_list_would_actually_catch_an_import(self) -> None:
        """A control: the guard is not vacuously satisfied by a broken regex."""
        sample = "from afterlap_core.simulation.physics import drag_force\n"
        assert any(re.search(pattern, sample) for pattern in _FORBIDDEN_IMPORTS)

    def test_no_evaluation_module_imports_planning_or_estimation(self) -> None:
        for path in sorted(_EVALUATION_DIR.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for module in ("afterlap_core.planning", "afterlap_core.estimation"):
                assert f"import {module}" not in source, f"{path.name} imports {module}"
                assert f"from {module}" not in source, f"{path.name} imports from {module}"


class TestReferenceEquations:
    def test_drag_matches_a_hand_computed_value(self) -> None:
        assert il.drag_force_n(1.2, 1.2, 50.0) == pytest.approx(1800.0, abs=1e-12)

    def test_grade_force_matches_a_hand_computed_value(self) -> None:
        expected = 798.0 * 9.80665 * math.sin(0.05)
        assert il.grade_force_n(798.0, 0.05) == pytest.approx(expected, rel=1e-15)
        assert expected == pytest.approx(391.122, abs=0.001)

    def test_rolling_force_uses_the_slope_normal_component(self) -> None:
        expected = 0.012 * 798.0 * 9.80665 * math.cos(0.05)
        assert il.rolling_force_n(798.0, 0.012, 0.05) == pytest.approx(expected, rel=1e-15)

    def test_battery_conversions_go_in_opposite_directions(self) -> None:
        assert il.battery_terminal_out_w(350_000.0, 0.95) == pytest.approx(368_421.0526, abs=1e-3)
        assert il.battery_terminal_in_w(350_000.0, 0.94) == pytest.approx(329_000.0, abs=1e-9)
        assert il.battery_terminal_out_w(350_000.0, 0.95) > 350_000.0
        assert il.battery_terminal_in_w(350_000.0, 0.94) < 350_000.0

    def test_the_thermal_derivative_is_zero_at_the_steady_state(self) -> None:
        steady = 303.15 + 45_000.0 / 900.0
        assert il.thermal_derivative_k_per_s(steady, 80_000.0, 45_000.0, 900.0, 303.15) == (
            pytest.approx(0.0, abs=1e-12)
        )


_CAR = il.CarParameters(
    car_config_id="hand-computed",
    mass_kg=800.0,
    cda_m2=1.0,
    crr=0.01,
    air_density_kgpm3=1.2,
    eta_discharge=0.8,
    eta_charge=0.5,
    battery_energy_min_j=0.0,
    battery_energy_max_j=4.0e6,
    aux_load_w=1000.0,
    c_th_j_per_k=100_000.0,
    h_w_per_k=1000.0,
    ambient_temperature_k=300.0,
)

_LEVEL_TRACK = il.TrackReference(
    track_id="hand-computed-level",
    length_m=1000.0,
    nodes_s_m=(0.0, 500.0, 1000.0),
    curvature_inv_m=(0.0, 0.0, 0.0),
    grade_rad=(0.0, 0.0, 0.0),
    mu=(1.5, 1.5, 1.5),
)


def _constant_power_frame(index: int, *, deploy_w: float, dt_s: float) -> il.TrajectoryFrame:
    """One frame in which the electrical powers are constant and known.

    The battery numbers here are the arithmetic answer, written out in the test
    that consumes this helper. The mechanical fields are set so the motion and
    work checks are trivially satisfiable and do not interfere.
    """
    out_w = deploy_w / _CAR.eta_discharge + _CAR.aux_load_w
    start_e = 2.0e6 - index * out_w * dt_s
    return il.TrajectoryFrame(
        index=index,
        start_time_s=index * dt_s,
        end_time_s=(index + 1) * dt_s,
        dt_s=dt_s,
        substeps=1,
        profile=il.DeploymentProfile.PUSH,
        start_progress_m=0.0,
        end_progress_m=0.0,
        start_speed_mps=0.0,
        end_speed_mps=0.0,
        start_temperature_k=300.0,
        end_temperature_k=300.0,
        start_battery_energy_j=start_e,
        end_battery_energy_j=start_e - out_w * dt_s,
        start_lap=0,
        end_lap=0,
        deploy_power_dc_w=deploy_w,
        harvest_power_dc_w=0.0,
        auxiliary_power_w=_CAR.aux_load_w,
        electrical_loss_power_w=0.0,
        drive_force_n=0.0,
        mechanical_braking_power_w=0.0,
        delta_deployed_dc_j=deploy_w * dt_s,
        delta_harvested_dc_j=0.0,
        delta_auxiliary_j=_CAR.aux_load_w * dt_s,
        delta_battery_out_j=out_w * dt_s,
        delta_battery_in_j=0.0,
        delta_recharge_cumulative_j=0.0,
    )


def _constant_power_trajectory(*, deploy_w: float, dt_s: float, frames: int) -> il.RecordedTrajectory:
    built = tuple(_constant_power_frame(i, deploy_w=deploy_w, dt_s=dt_s) for i in range(frames))
    return il.RecordedTrajectory(
        car_id="hand",
        scenario_id="hand-computed-constant-power",
        bundle_hash="sha256:1b001706a418bdfca35361355c643b7918572b8f9b7503f3043a6e23b45dce52",
        seed=0,
        car=_CAR,
        track=_LEVEL_TRACK,
        frames=built,
        initial_battery_energy_j=built[0].start_battery_energy_j,
        final_battery_energy_j=built[-1].end_battery_energy_j,
        final_recharge_cumulative_j=0.0,
        simulator_close_error_j=0.0,
        simulator_integrator="hand",
    )


class TestHandComputedConstantPower:
    """Numbers computed arithmetically here, not by calling the checker."""

    def test_the_reconstruction_matches_the_arithmetic_answer(self) -> None:
        deploy_w = 200_000.0
        dt_s = 0.1
        frames = 100

        expected_drain_j = (200_000.0 / 0.8 + 1000.0) * 10.0
        assert expected_drain_j == 2_510_000.0

        trajectory = _constant_power_trajectory(deploy_w=deploy_w, dt_s=dt_s, frames=frames)
        expected_final_j = trajectory.initial_battery_energy_j - expected_drain_j

        audit = il.reconstruct(trajectory)
        bus = audit.by_name("battery_energy_from_bus_ledgers")
        power = audit.by_name("battery_energy_from_powers")

        assert bus.independent_value == pytest.approx(expected_final_j, abs=1e-6)
        assert power.independent_value == pytest.approx(expected_final_j, abs=1e-6)
        assert bus.within_tolerance and power.within_tolerance
        assert not audit.flagged

    def test_a_swapped_efficiency_would_change_the_answer_measurably(self) -> None:
        """The check is sensitive to the error it exists to catch.

        If the discharge efficiency were applied as a multiplication instead of
        a division, the reconstructed drain would fall by 36 %. That is what
        gives the 1e-4 J tolerance its meaning.
        """
        correct = 200_000.0 / 0.8
        wrong = 200_000.0 * 0.8
        assert correct == 250_000.0
        assert wrong == 160_000.0
        assert abs(correct - wrong) * 10.0 == pytest.approx(900_000.0)

    def test_the_thermal_reconstruction_matches_the_analytic_solution(self) -> None:
        """RK4 against the closed form of the same linear ODE, by hand."""
        loss_w = 50_000.0
        dt_s = 0.5
        steady = _CAR.ambient_temperature_k + loss_w / _CAR.h_w_per_k
        start = 310.0
        decay = math.exp(-_CAR.h_w_per_k * dt_s / _CAR.c_th_j_per_k)
        analytic = steady + (start - steady) * decay
        numeric = il._rk4_temperature(_CAR, temperature_k=start, loss_power_w=loss_w, dt_s=dt_s, substeps=8)
        assert numeric == pytest.approx(analytic, abs=1e-9)


class TestCorruptedTrajectoryIsDetected:
    def test_injected_free_energy_is_flagged(self, oval_trajectory) -> None:
        """Add 50 kJ of energy that no flow explains, and require a finding."""
        injection_j = 50_000.0
        target = 120
        frames = list(oval_trajectory.frames)
        assert target < len(frames)
        frames[target] = replace(
            frames[target], end_battery_energy_j=frames[target].end_battery_energy_j + injection_j
        )
        for index in range(target + 1, len(frames)):
            frames[index] = replace(
                frames[index],
                start_battery_energy_j=frames[index].start_battery_energy_j + injection_j,
                end_battery_energy_j=frames[index].end_battery_energy_j + injection_j,
            )
        corrupted = oval_trajectory.with_frames(frames)

        clean_audit = il.reconstruct(oval_trajectory)
        assert not clean_audit.flagged, "the clean trajectory must not be flagged"

        audit = il.reconstruct(corrupted)
        assert audit.flagged
        findings = [f for f in audit.frame_findings if f.kind == "unexplained_battery_energy"]
        assert len(findings) == 1
        assert findings[0].frame_index == target
        assert findings[0].residual == pytest.approx(injection_j, abs=1e-6)
        assert findings[0].unit == "J"

        bus = audit.by_name("battery_energy_from_bus_ledgers")
        assert not bus.within_tolerance
        assert bus.difference == pytest.approx(-injection_j, abs=1e-6)

    def test_a_ledger_that_counted_battery_gain_on_the_cuk_bus_is_flagged(
        self, harvesting_trajectory
    ) -> None:
        """The CU-K ledger integrates the DC bus, not the battery gain.

        Rewriting the recharge ledger as battery gain is a 6 % error in the
        favourable direction for a plan; the identity check catches it.
        """
        assert harvesting_trajectory.final_recharge_cumulative_j > 0.0, (
            "this fixture must actually harvest, or the corruption is a no-op"
        )
        eta_charge = harvesting_trajectory.car.eta_charge
        frames = [
            replace(
                frame,
                delta_recharge_cumulative_j=eta_charge * frame.delta_harvested_dc_j,
            )
            for frame in harvesting_trajectory.frames
        ]
        corrupted = harvesting_trajectory.with_frames(frames)
        audit = il.reconstruct(corrupted)
        identity = audit.by_name("cuk_ledger_equals_dc_bus_harvest")
        assert not identity.within_tolerance
        assert identity.difference > 0.0

    def test_an_understated_deployment_is_flagged(self, oval_trajectory) -> None:
        """Halving the recorded deployment without changing the battery state."""
        target = 200
        frames = list(oval_trajectory.frames)
        original = frames[target].delta_deployed_dc_j
        assert original > 0.0, "pick a frame that actually deployed"
        frames[target] = replace(frames[target], delta_deployed_dc_j=original * 0.5)
        audit = il.reconstruct(oval_trajectory.with_frames(frames))
        assert audit.flagged
        assert any(f.frame_index == target for f in audit.frame_findings)


class TestLineCrossingReference:
    def test_it_recovers_an_analytically_known_crossing(self) -> None:
        """Constant acceleration has a closed-form crossing time.

        With ``p(t) = p0 + v0 t + a t^2 / 2`` the threshold ``P`` is reached at
        ``t = (-v0 + sqrt(v0^2 + 2 a (P - p0))) / a``. The reference must find
        that time from samples of the same motion.
        """
        p0, v0, a = 100.0, 60.0, 4.0
        threshold = 400.0
        exact = (-v0 + math.sqrt(v0 * v0 + 2.0 * a * (threshold - p0))) / a
        assert exact == pytest.approx(4.364916731037084, abs=1e-12)

        dt = 0.5
        samples = [
            il.ProgressSample(
                session_time_s=index * dt,
                progress_m=p0 + v0 * (index * dt) + 0.5 * a * (index * dt) ** 2,
                speed_mps=v0 + a * (index * dt),
            )
            for index in range(20)
        ]
        crossings = il.find_crossings(samples, track_length_m=1.0e9, lines={"line": threshold})
        assert len(crossings) == 1
        assert crossings[0].session_time_s == pytest.approx(exact, abs=1e-9)

    def test_it_beats_linear_interpolation_on_the_same_samples(self) -> None:
        """A control proving the Hermite reference is doing real work."""
        p0, v0, a = 0.0, 60.0, 8.0
        threshold = 200.0
        exact = (-v0 + math.sqrt(v0 * v0 + 2.0 * a * threshold)) / a
        low, high = 2.0, 4.0
        pair = [il.ProgressSample(t, p0 + v0 * t + 0.5 * a * t * t, v0 + a * t) for t in (low, high)]
        hermite = il.hermite_crossing_time(pair[0], pair[1], threshold)
        assert hermite is not None
        fraction = (threshold - pair[0].progress_m) / (pair[1].progress_m - pair[0].progress_m)
        linear = low + fraction * (high - low)
        assert abs(hermite - exact) < abs(linear - exact) / 100.0

    def test_it_returns_nothing_when_the_interval_excludes_the_threshold(self) -> None:
        a = il.ProgressSample(0.0, 0.0, 10.0)
        b = il.ProgressSample(1.0, 10.0, 10.0)
        assert il.hermite_crossing_time(a, b, 50.0) is None

    def test_a_missing_recorded_crossing_is_reported_not_dropped(self) -> None:
        reference = (
            il.Crossing(label="alpha", lap=0, threshold_progress_m=100.0, session_time_s=1.0),
            il.Crossing(label="beta", lap=0, threshold_progress_m=200.0, session_time_s=2.0),
        )
        recorded = (("alpha", 0, 1.0000001), ("gamma", 0, 3.0))
        comparison = il.compare_crossings(reference, recorded)
        statuses = {item.label: item.status for item in comparison}
        assert statuses == {
            "alpha": "matched",
            "beta": "missing_from_simulator",
            "gamma": "missing_from_reference",
        }

    def test_the_reference_agrees_with_a_real_simulator_crossing(self, loop_bundle: ScenarioBundle) -> None:
        """Run A03, find the crossing independently, and report the difference."""
        ego = loop_bundle.scenario.ego_car_id
        simulator = Simulator()
        simulator.reset(loop_bundle)
        samples = [
            il.ProgressSample(
                simulator.session_time_s,
                simulator.world.cars[ego].progress_m,
                simulator.world.cars[ego].speed_mps,
            )
        ]
        for _ in range(1300):
            simulator.step(None, RECORD_DT_S)
            samples.append(
                il.ProgressSample(
                    simulator.session_time_s,
                    simulator.world.cars[ego].progress_m,
                    simulator.world.cars[ego].speed_mps,
                )
            )
        lines = {cp.id: float(cp.s_m.value) for cp in loop_bundle.track.checkpoints}
        reference = il.find_crossings(samples, track_length_m=loop_bundle.track.length, lines=lines)
        recorded = il.recorded_crossings(simulator, ego)
        assert reference, "the run must reach at least one checkpoint"
        comparison = il.compare_crossings(reference, recorded)
        matched = [c for c in comparison if c.status == "matched"]
        assert matched, "no reconstructed crossing matched a recorded one"
        assert all(c.status != "missing_from_simulator" for c in comparison)
        worst = max(abs(c.difference_s) for c in matched if c.difference_s is not None)
        assert worst < 1.0e-8, f"crossing-time disagreement {worst} s"


_ALL_FIXTURES = (
    "two-straight-counterattack",
    "oval-low-energy",
    "loop-no-energy-channel",
    "oval-defend-hold",
    "loop-regen-disabled",
)


class TestAgainstRealTrajectories:
    def test_every_discrepancy_is_inside_its_frozen_tolerance(self, oval_trajectory, loop_trajectory) -> None:
        for trajectory in (oval_trajectory, loop_trajectory):
            audit = il.reconstruct(trajectory)
            failures = [d for d in audit.discrepancies if not d.within_tolerance]
            assert not failures, [
                f"{d.name}: {d.difference} {d.unit} exceeds {d.tolerance}" for d in failures
            ]
            assert not audit.frame_findings

    def test_the_headline_battery_discrepancy_is_at_float_noise(self, oval_trajectory) -> None:
        """The reported signed discrepancy, with its unit, on a real run."""
        audit = il.reconstruct(oval_trajectory)
        bus = audit.by_name("battery_energy_from_bus_ledgers")
        assert bus.unit == "J"
        assert abs(bus.difference) < 1.0e-4
        assert bus.relative_difference is not None
        assert abs(bus.relative_difference) < 1.0e-12

    @pytest.mark.parametrize("scenario_id", _ALL_FIXTURES)
    def test_every_shipped_fixture_reconstructs(self, scenario_id: str, record_trajectory_for) -> None:
        bundle = load_bundle(scenario_id)
        trajectory = record_trajectory_for(bundle, bundle.scenario.ego_car_id, 200)
        audit = il.reconstruct(trajectory)
        assert not audit.frame_findings
        assert audit.frame_count == 200
        failures = [d.name for d in audit.discrepancies if not d.within_tolerance]
        assert not failures, failures

    def test_split_frames_are_counted_and_declared(self, loop_trajectory) -> None:
        """The loop fixtures split nearly every step; the audit must say so."""
        audit = il.reconstruct(loop_trajectory)
        assert audit.frames_with_split_steps > 0
        assert any("split" in note for note in audit.notes)

    def test_a_higher_resolution_integrator_than_the_run_under_test(self, oval_trajectory) -> None:
        audit = il.reconstruct(oval_trajectory)
        assert audit.substeps_per_frame >= 8
        assert all(frame.substeps <= 2 for frame in oval_trajectory.frames)

    def test_a_reconstruction_refuses_an_empty_trajectory(self, oval_trajectory) -> None:
        with pytest.raises(ValueError, match="empty trajectory"):
            il.reconstruct(oval_trajectory.with_frames([]))

    def test_the_track_reference_is_not_the_simulators_interpolator(
        self, loop_bundle: ScenarioBundle
    ) -> None:
        """The re-implemented interpolation must agree with A03's to float noise.

        Agreement is the expected result; the point is that it is *checked*
        rather than assumed, because the two implementations are separate.
        """
        reference = il.TrackReference.from_track_config(loop_bundle.track)
        for s_m in (0.0, 137.5, 1499.9, 2100.0, 3500.0, 5199.5):
            assert reference.grade_at(s_m) == pytest.approx(loop_bundle.track.grade_at(s_m), abs=1e-12)
            assert reference.mu_at(s_m) == pytest.approx(loop_bundle.track.mu_at(s_m), abs=1e-12)
            assert reference.curvature_at(s_m) == pytest.approx(
                loop_bundle.track.curvature_at(s_m), abs=1e-12
            )
