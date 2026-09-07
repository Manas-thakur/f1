"""Overtake-permission state machine.

The synthetic pack puts the detection line at s = 1600 m and the activation line
at s = 1900 m on a 5000 m track. Every crossing time below is computed in the
test from the interval's own linear interpolation.
"""

from __future__ import annotations

import pytest

from afterlap_contracts import DeploymentProfile, EligibilityState, FlagState
from afterlap_core.rules import (
    CarState,
    EligibilityMachine,
    RaceEvent,
    RaceEventKind,
    admissible_profiles,
    resolve_pack_context,
)
from afterlap_core.timebase import EventPriority

from .conftest import TRACK_LENGTH_M


def machine(pack) -> EligibilityMachine:
    return EligibilityMachine.from_lines(pack.manifest.detection_lines, TRACK_LENGTH_M)


def test_detection_between_ticks_resolves_at_interpolated_time(pack_v1):
    engine = machine(pack_v1)
    # 1500 m -> 1700 m over 10.0 s -> 11.0 s. The line at 1600 m is exactly
    # half way along the interval, so it is crossed at 10.0 + 0.5 * 1.0 = 10.5 s.
    transitions = engine.advance(10.0, 11.0, 1_500.0, 1_700.0, gap_condition_met=True)

    assert len(transitions) == 1
    assert transitions[0].to_state is EligibilityState.ELIGIBLE_DETECTED
    assert transitions[0].at_session_time_s == pytest.approx(10.5, abs=1e-12)
    assert engine.observed_at_s == pytest.approx(10.5, abs=1e-12)
    # Not the tick boundary: neither the start nor the end of the interval.
    assert engine.observed_at_s not in (10.0, 11.0)
    assert engine.state is EligibilityState.ELIGIBLE_DETECTED
    assert engine.total_detections == 1


def test_crossing_exactly_on_a_tick_boundary_fires_at_that_tick(pack_v1):
    engine = machine(pack_v1)
    # The interval ends exactly on the line: fraction 1.0, so t = 12.0 s.
    transitions = engine.advance(11.0, 12.0, 1_500.0, 1_600.0, gap_condition_met=True)
    assert len(transitions) == 1
    assert transitions[0].at_session_time_s == pytest.approx(12.0, abs=1e-12)
    # The next interval starts on the line and must not fire it a second time.
    again = engine.advance(12.0, 13.0, 1_600.0, 1_700.0, gap_condition_met=True)
    assert again == ()
    assert engine.total_detections == 1


def test_two_lines_in_one_interval_fire_in_order(pack_v1):
    engine = machine(pack_v1)
    # 1500 m -> 2000 m (500 m) over 10.0 s -> 12.0 s (2.0 s).
    # detection at 1600: (1600 - 1500) / 500 = 0.2 -> 10.0 + 0.4 = 10.4 s
    # activation at 1900: (1900 - 1500) / 500 = 0.8 -> 10.0 + 1.6 = 11.6 s
    transitions = engine.advance(10.0, 12.0, 1_500.0, 2_000.0, gap_condition_met=True)

    assert [t.line_id for t in transitions] == ["detect-1", "activate-1"]
    assert transitions[0].at_session_time_s == pytest.approx(10.4, abs=1e-12)
    assert transitions[1].at_session_time_s == pytest.approx(11.6, abs=1e-12)
    assert transitions[0].at_session_time_s < transitions[1].at_session_time_s
    assert transitions[0].to_state is EligibilityState.ELIGIBLE_DETECTED
    assert transitions[1].to_state is EligibilityState.ACTIVE
    assert engine.state is EligibilityState.ACTIVE
    assert engine.activated_at_s == pytest.approx(11.6, abs=1e-12)


def test_missing_detection_never_promotes_to_active(pack_v1):
    # An activation crossing with no eligible detection behind it.
    from_unknown = machine(pack_v1)
    from_unknown.advance(10.0, 11.0, 1_850.0, 1_950.0, gap_condition_met=True)
    assert from_unknown.state is EligibilityState.UNKNOWN
    assert from_unknown.total_activations == 0
    assert from_unknown.activated_at_s is None

    # And after a detection that resolved to ineligible.
    from_ineligible = machine(pack_v1)
    from_ineligible.advance(10.0, 11.0, 1_500.0, 1_700.0, gap_condition_met=False)
    assert from_ineligible.state is EligibilityState.INELIGIBLE
    from_ineligible.advance(11.0, 12.0, 1_850.0, 1_950.0, gap_condition_met=False)
    assert from_ineligible.state is EligibilityState.INELIGIBLE
    assert from_ineligible.total_activations == 0


def test_unresolved_gap_condition_keeps_state_unknown(pack_v1):
    engine = machine(pack_v1)
    engine.advance(10.0, 12.0, 1_500.0, 2_000.0, gap_condition_met=None)
    # Both lines were crossed, and the machine still refuses to assert a
    # permission it cannot resolve.
    assert engine.state is EligibilityState.UNKNOWN
    assert engine.total_detections == 1
    assert engine.total_activations == 0
    assert engine.permits_overtake_profile is False


def test_safety_state_interruption_invalidates_active_permission(pack_v1):
    engine = machine(pack_v1)
    engine.advance(10.0, 12.0, 1_500.0, 2_000.0, gap_condition_met=True)
    assert engine.state is EligibilityState.ACTIVE

    transition = engine.invalidate(12.5, "virtual safety car deployed")
    assert transition.priority is EventPriority.SAFETY_OR_RULE_INVALIDATION
    assert transition.from_state is EligibilityState.ACTIVE
    assert engine.state is EligibilityState.INELIGIBLE
    assert engine.activated_at_s is None
    assert engine.observed_at_s == 12.5
    assert engine.invalidations == 1

    # An unresolved permission is not "resolved" into ineligible by a flag.
    unknown_engine = machine(pack_v1)
    unknown_engine.advance(10.0, 12.0, 1_500.0, 2_000.0, gap_condition_met=None)
    unknown_engine.invalidate(12.5, "virtual safety car deployed")
    assert unknown_engine.state is EligibilityState.UNKNOWN


def test_race_control_invalidation_removes_overtake_from_the_context(pack_v1):
    car = CarState(
        speed_mps=60.0,
        battery_energy_j=2_000_000.0,
        temperature_k=300.0,
        eligibility=EligibilityState.ACTIVE,
        eligibility_observed_at_s=11.6,
    )
    green = resolve_pack_context(
        pack_v1,
        1_950.0,
        12.0,
        car,
        session_id="s",
        race_events=[
            RaceEvent(at_session_time_s=0.0, kind=RaceEventKind.FLAG, flags=(FlagState.GREEN,)),
        ],
    )
    assert DeploymentProfile.OVERTAKE in green.admissible_profiles

    interrupted = resolve_pack_context(
        pack_v1,
        1_950.0,
        12.0,
        car,
        session_id="s",
        race_events=[
            RaceEvent(at_session_time_s=0.0, kind=RaceEventKind.FLAG, flags=(FlagState.GREEN,)),
            RaceEvent(at_session_time_s=11.9, kind=RaceEventKind.FLAG, flags=(FlagState.SAFETY_CAR,)),
            RaceEvent(at_session_time_s=11.9, kind=RaceEventKind.INVALIDATION, reason="safety car"),
        ],
    )
    assert interrupted.eligibility is EligibilityState.INELIGIBLE
    assert interrupted.eligibility_observed_at_s == 11.9
    assert DeploymentProfile.OVERTAKE not in interrupted.admissible_profiles
    assert DeploymentProfile.PUSH not in interrupted.admissible_profiles
    assert DeploymentProfile.HARVEST in interrupted.admissible_profiles


def test_lap_reset_clears_only_lap_scoped_state(pack_v1):
    engine = machine(pack_v1)
    engine.advance(10.0, 12.0, 1_500.0, 2_000.0, gap_condition_met=True)
    assert (engine.detections_this_lap, engine.activations_this_lap) == (1, 1)
    assert (engine.total_detections, engine.total_activations) == (1, 1)

    engine.reset_lap(90.0)

    # Lap-scoped state is cleared ...
    assert engine.detections_this_lap == 0
    assert engine.activations_this_lap == 0
    assert engine.state is EligibilityState.INELIGIBLE
    assert engine.activated_at_s is None
    # ... and session-scoped state is not.
    assert engine.total_detections == 1
    assert engine.total_activations == 1
    assert engine.lap_resets == 1

    # A second lap can earn its own permission again.
    engine.advance(100.0, 102.0, 6_500.0, 7_000.0, gap_condition_met=True)
    assert engine.state is EligibilityState.ACTIVE
    assert engine.detections_this_lap == 1
    assert engine.total_detections == 2

    # An unresolved state survives a lap reset as unresolved.
    unknown_engine = machine(pack_v1)
    unknown_engine.advance(10.0, 12.0, 1_500.0, 2_000.0, gap_condition_met=None)
    unknown_engine.reset_lap(90.0)
    assert unknown_engine.state is EligibilityState.UNKNOWN


def test_eligibility_is_permission_not_energy(pack_v1):
    """An active permission never adds joules, and never overrides the floor."""
    floor_j = pack_v1.manifest.battery_energy_min_j
    empty = CarState(
        speed_mps=60.0,
        battery_energy_j=floor_j,
        temperature_k=300.0,
        eligibility=EligibilityState.ACTIVE,
        eligibility_observed_at_s=11.6,
    )
    context = resolve_pack_context(pack_v1, 1_950.0, 12.0, empty, session_id="s")

    assert context.eligibility is EligibilityState.ACTIVE
    assert DeploymentProfile.OVERTAKE not in context.admissible_profiles
    assert DeploymentProfile.PUSH not in context.admissible_profiles
    assert DeploymentProfile.HARVEST in context.admissible_profiles
    assert admissible_profiles(context, empty) == context.admissible_profiles
    # The pack grants no extra ceiling for the overtake profile either.
    assert pack_v1.manifest.overtake_profile_extra_power_w == 0.0

    charged = CarState(
        speed_mps=60.0,
        battery_energy_j=floor_j + 1.0,
        temperature_k=300.0,
        eligibility=EligibilityState.ACTIVE,
        eligibility_observed_at_s=11.6,
    )
    assert DeploymentProfile.OVERTAKE in admissible_profiles(context, charged)
