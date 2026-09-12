"""Configuration provenance, track interpolation and footprint geometry.

The provenance test is the one that keeps the package honest: every physical
number in every shipped fixture must declare a unit, a source and a verification
status, and none of them may claim to be measured.
"""

from __future__ import annotations

import math

import pytest
from conftest import build_bundle
from pydantic import ValidationError

from afterlap_core.config import VerificationStatus, list_configs
from afterlap_core.simulation import (
    CarFootprint,
    geometry_for,
    load_car,
    load_scenario,
    load_track,
    overlap,
    parameter_provenance,
)
from afterlap_core.simulation.config import ScenarioBundle

SHIPPED_TRACKS = ("test-loop", "test-oval")
SHIPPED_CARS = ("synthetic-2026", "synthetic-2026-no-regen")
SHIPPED_SCENARIOS = (
    "two-straight-counterattack",
    "oval-low-energy",
    "loop-no-energy-channel",
    "oval-defend-hold",
    "loop-regen-disabled",
)


class TestProvenance:
    @pytest.mark.parametrize(
        ("kind", "expected"),
        [("tracks", SHIPPED_TRACKS), ("cars", SHIPPED_CARS), ("scenarios", SHIPPED_SCENARIOS)],
    )
    def test_the_expected_fixtures_are_present(self, kind: str, expected: tuple[str, ...]) -> None:
        assert set(expected) <= set(list_configs(kind))

    @pytest.mark.parametrize("track_id", SHIPPED_TRACKS)
    def test_track_parameters_declare_units_and_provenance(self, track_id: str) -> None:
        self._check(load_track(track_id))

    @pytest.mark.parametrize("car_id", SHIPPED_CARS)
    def test_car_parameters_declare_units_and_provenance(self, car_id: str) -> None:
        self._check(load_car(car_id))

    @pytest.mark.parametrize("scenario_id", SHIPPED_SCENARIOS)
    def test_scenario_parameters_declare_units_and_provenance(self, scenario_id: str) -> None:
        self._check(load_scenario(scenario_id))

    @staticmethod
    def _check(document) -> None:
        provenance = parameter_provenance(document)
        assert provenance, f"{document.id} declares no parameters at all"
        assert document.synthetic is True
        for name, entry in provenance.items():
            assert entry["unit"], f"{document.id}.{name} has no unit"
            assert entry["source"], f"{document.id}.{name} has no source"
            assert entry["verification"] == VerificationStatus.SYNTHETIC_ASSUMPTION.value, (
                f"{document.id}.{name} claims verification {entry['verification']}; "
                "nothing in this package is measured"
            )

    def test_no_track_claims_surveyed_geometry(self) -> None:
        for track_id in SHIPPED_TRACKS:
            track = load_track(track_id)
            assert track.lateral_geometry_surveyed is False
            assert track.geometry_provenance == "synthetic_sketch"


class TestScenarioMatchesThePlanFixture:
    """``simulation/scenario.example.json`` is the normative initial condition."""

    def test_the_counterattack_scenario_reproduces_the_example(self) -> None:
        scenario = load_scenario("two-straight-counterattack")
        track = load_track(scenario.track_id)

        assert scenario.id == "two-straight-counterattack"
        assert scenario.synthetic is True
        assert scenario.seed == 42
        assert scenario.track_id == "test-loop"
        assert track.length == pytest.approx(5200.0)
        assert track.checkpoint("attack-exit").s_m.value == pytest.approx(2100.0)
        assert track.checkpoint("counterattack-exit").s_m.value == pytest.approx(3500.0)

        own = scenario.initial_states[scenario.ego_car_id]
        rival = scenario.initial_states["rival"]
        assert own.speed_mps.value == pytest.approx(75.0)
        assert own.energy_j.value == pytest.approx(2.4e6)
        assert rival.energy_j.value == pytest.approx(2.8e6)
        assert scenario.gap_ahead_s is not None
        assert scenario.gap_ahead_s.value == pytest.approx(0.65)

        assert scenario.observation.delay_s.value == pytest.approx(0.15)
        assert scenario.observation.expose_rival_energy is False
        assert scenario.observation.energy_provenance.value == "simulated"
        assert scenario.rule_pack == "synthetic-pack-v1-unreviewed"

    def test_the_declared_gap_must_agree_with_the_initial_states(self) -> None:
        scenario = load_scenario("two-straight-counterattack")
        implied = (
            scenario.initial_states["rival"].progress_m.value
            - scenario.initial_states["own"].progress_m.value
        ) / scenario.initial_states["own"].speed_mps.value
        assert implied == pytest.approx(0.65, abs=1e-9)

        broken = scenario.model_dump(mode="python")
        broken["initial_states"]["rival"]["progress_m"]["value"] = 999.0
        with pytest.raises(ValueError, match="disagrees with the initial states"):
            type(scenario).model_validate(broken)


class TestTrackInterpolation:
    def test_values_at_breakpoints_equal_the_declared_values(self) -> None:
        track = load_track("test-loop")
        for segment in track.segments:
            position = segment.s_m.value
            assert track.curvature_at(position) == pytest.approx(segment.curvature_inv_m.value, abs=1e-12)
            assert track.grade_at(position) == pytest.approx(segment.grade_rad.value, abs=1e-12)
            assert track.mu_at(position) == pytest.approx(segment.mu.value, abs=1e-12)
            assert track.width_at(position) == pytest.approx(segment.width_m.value, abs=1e-12)

    def test_a_constant_stretch_stays_constant(self) -> None:
        track = load_track("test-oval")
        for position in (1600.0, 1700.0, 1800.0, 1900.0):
            assert track.curvature_at(position) == pytest.approx(0.0068966, abs=1e-12)

    def test_the_smoothstep_midpoint_is_the_arithmetic_mean(self) -> None:
        track = load_track("test-loop")
        assert track.curvature_at(1550.0) == pytest.approx(0.0025, abs=1e-12)

    def test_interpolation_wraps_around_the_lap(self) -> None:
        track = load_track("test-loop")
        assert track.curvature_at(0.0) == pytest.approx(track.curvature_at(5200.0), abs=1e-12)
        assert track.curvature_at(10.0) == pytest.approx(track.curvature_at(5210.0), abs=1e-12)
        assert track.mu_at(-100.0) == pytest.approx(track.mu_at(5100.0), abs=1e-12)

    def test_checkpoint_lookup(self) -> None:
        track = load_track("test-loop")
        assert track.checkpoint("attack-exit").id == "attack-exit"
        assert "counterattack-exit" in track.checkpoint_ids
        with pytest.raises(KeyError):
            track.checkpoint("nonexistent")

    def test_the_timing_line_sits_at_the_start_of_the_lap(self) -> None:
        for track_id in SHIPPED_TRACKS:
            assert load_track(track_id).timing_line_s_m.value == pytest.approx(0.0)


class TestCarConfig:
    def test_the_ice_power_map_interpolates_and_extrapolates_flat(self) -> None:
        car = load_car("synthetic-2026")
        assert car.ice_power_at(0.0) == pytest.approx(0.0)
        assert car.ice_power_at(15.0) == pytest.approx(240.0e3, rel=1e-12)
        assert car.ice_power_at(40.0) == pytest.approx(400.0e3, rel=1e-12)
        assert car.ice_power_at(200.0) == pytest.approx(400.0e3, rel=1e-12)

    def test_the_downforce_factor_matches_its_definition(self) -> None:
        car = load_car("synthetic-2026")
        expected = 0.5 * 1.20 * 4.00 / 798.0
        assert car.downforce_factor_inv_m == pytest.approx(expected, rel=1e-12)

    def test_the_no_regen_variant_differs_only_in_regeneration(self) -> None:
        regen = load_car("synthetic-2026")
        no_regen = load_car("synthetic-2026-no-regen")
        assert regen.regen_enabled is True
        assert no_regen.regen_enabled is False
        assert no_regen.mass_kg.value == regen.mass_kg.value
        assert no_regen.config_hash != regen.config_hash


class TestBundleValidation:
    def test_a_bundle_hash_covers_every_referenced_document(self) -> None:
        bundle = build_bundle()
        other = build_bundle("oval-defend-hold")
        assert bundle.bundle_hash != other.bundle_hash
        assert bundle.bundle_hash == build_bundle().bundle_hash

    def test_an_unknown_evaluation_checkpoint_is_rejected(self) -> None:
        scenario = load_scenario("two-straight-counterattack")
        broken = scenario.model_copy(update={"evaluation_checkpoints": ("does-not-exist",)})
        from afterlap_core.simulation import load_bundle

        with pytest.raises(ValueError, match="unknown checkpoints"):
            load_bundle(broken)

    def test_a_scenario_needs_a_policy_for_every_rival(self) -> None:
        scenario = load_scenario("two-straight-counterattack")
        payload = scenario.model_dump(mode="python")
        payload["opponent_policies"] = {}
        with pytest.raises(ValueError, match="every rival needs"):
            type(scenario).model_validate(payload)

    def test_the_bundle_is_immutable(self) -> None:
        bundle = build_bundle()
        assert isinstance(bundle, ScenarioBundle)
        with pytest.raises(ValidationError):
            bundle.scenario = None  # type: ignore[misc]


class TestFootprintGeometry:
    def test_corners_of_an_axis_aligned_rectangle(self) -> None:
        footprint = CarFootprint(x_m=0.0, y_m=0.0, heading_rad=0.0, length_m=4.0, width_m=2.0)
        corners = footprint.corners()
        assert sorted(corners) == sorted(((2.0, 1.0), (-2.0, 1.0), (-2.0, -1.0), (2.0, -1.0)))
        assert footprint.bounding_radius_m == pytest.approx(math.hypot(4.0, 2.0) / 2.0)

    def test_separating_axis_test_on_known_configurations(self) -> None:
        a = CarFootprint(0.0, 0.0, 0.0, 4.0, 2.0)
        assert overlap(a, CarFootprint(1.0, 0.0, 0.0, 4.0, 2.0))
        assert not overlap(a, CarFootprint(4.1, 0.0, 0.0, 4.0, 2.0))
        assert not overlap(a, CarFootprint(0.0, 2.1, 0.0, 4.0, 2.0))
        assert overlap(a, CarFootprint(0.0, 2.0, math.pi / 2.0, 4.0, 2.0))

    def test_overlap_is_symmetric(self) -> None:
        a = CarFootprint(0.0, 0.0, 0.2, 5.6, 2.0)
        b = CarFootprint(3.0, 1.0, -0.4, 5.6, 2.0)
        assert overlap(a, b) == overlap(b, a)

    def test_arc_length_helpers_wrap_correctly(self) -> None:
        geometry = geometry_for(load_track("test-loop"))
        assert geometry.signed_arc_gap(5190.0, 10.0) == pytest.approx(20.0, abs=1e-9)
        assert geometry.signed_arc_gap(10.0, 5190.0) == pytest.approx(-20.0, abs=1e-9)
        assert geometry.wrap(5300.0) == pytest.approx(100.0, abs=1e-9)

    def test_the_local_frame_places_a_trailing_car_behind(self) -> None:
        geometry = geometry_for(load_track("test-loop"))
        x, y, heading = geometry.local_position(1000.0, 994.0, 0.0, 0.0)
        assert x < 0.0
        assert abs(y) < 1.0
        assert abs(heading) < 0.2

    def test_the_lateral_limit_keeps_the_car_inside_the_track(self) -> None:
        track = load_track("test-loop")
        geometry = geometry_for(track)
        limit = geometry.lateral_limit(0.0, 2.0)
        assert limit == pytest.approx(0.5 * (track.width_at(0.0) - 2.0), rel=1e-12)
        assert geometry.lateral_limit(0.0, 100.0) == 0.0

    @pytest.mark.parametrize("track_id", SHIPPED_TRACKS)
    def test_the_synthetic_centreline_closes(self, track_id: str) -> None:
        """Both fixtures were solved to close, and the residual is reported.

        Closure matters only for a map drawing: the physics runs in an
        arc-length frame and pairwise geometry is built in a local frame, so a
        non-closing sketch could never corrupt a trajectory. The residual is
        exposed so a renderer can state its own precision.
        """
        geometry = geometry_for(load_track(track_id))
        assert geometry.closure_residual_m < 0.5
        assert abs(geometry.closure_heading_residual_rad) < 1.0e-3


@pytest.mark.parametrize("duration", [float("inf"), float("nan"), float("-inf"), 0.0, -1.0])
def test_simulator_rejects_non_finite_or_non_positive_step(duration):
    from afterlap_core.simulation import Simulator, load_bundle

    simulator = Simulator()
    simulator.reset(load_bundle("two-straight-counterattack"), seed=42)
    with pytest.raises(ValueError, match="positive duration"):
        simulator.step(None, duration)
    assert simulator.session_time_s == 0.0
