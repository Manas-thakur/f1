"""Assembly of the frozen contract: identity slots, prediction and provenance.

An identity slot that swaps cars on a tenth of a second of noise would make every
downstream trend -- closing rate, intention history, expected pass -- a fiction
stitched from two different cars.
"""

from __future__ import annotations

import numpy as np
import pytest

from afterlap_contracts import (
    SCHEMA_VERSION,
    Provenance,
    Quality,
    TelemetryEvent,
)
from afterlap_core.estimation import (
    STATE_PROGRESS,
    STATE_SPEED,
    OwnCarConfig,
    RivalConfig,
    create_state,
    predict,
    update,
    update_state,
)
from afterlap_core.estimation.assembly import SlotTracker

from .conftest import OWN_CAR_ID, RIVAL_CAR_ID, SECOND_RIVAL_ID, SESSION_ID, make_context, make_run


def _event(
    sequence: int,
    car_id: str,
    channel: str,
    value: float,
    unit: str,
    source_time_s: float,
) -> TelemetryEvent:
    return TelemetryEvent(
        schema_version=SCHEMA_VERSION,
        event_id=f"{car_id}-{channel}-{sequence:05d}",
        session_id=SESSION_ID,
        car_id=car_id,
        sequence=sequence,
        source_time_s=source_time_s,
        received_time_s=source_time_s + 0.01,
        channel=channel,
        value=value,
        unit=unit,
        provenance=Provenance.SIMULATED,
        quality=Quality.VALID,
    )


# -- slot hysteresis ------------------------------------------------------


def test_a_slot_does_not_change_hands_on_noise() -> None:
    """A challenger inside the hysteresis margin never takes the slot."""
    tracker = SlotTracker(hysteresis_s=0.15, hold_s=1.0, slots=("ahead_1",))
    assert tracker.assign({"a": 0.60}, 0.0) == {"ahead_1": "a"}
    for step in range(1, 40):
        # 'b' is closer, but only by 0.02 s -- inside the noise band.
        assignment = tracker.assign({"a": 0.60, "b": 0.58}, step * 0.1)
        assert assignment == {"ahead_1": "a"}
    assert len(tracker.changes) == 1, "only the initial assignment should be recorded"


def test_a_slot_changes_hands_once_a_challenger_is_clearly_and_persistently_closer() -> None:
    tracker = SlotTracker(hysteresis_s=0.15, hold_s=1.0, slots=("ahead_1",))
    tracker.assign({"a": 0.60}, 0.0)
    # 'b' beats 'a' by 0.3 s, well past the hysteresis, but must hold it for 1 s.
    for step in range(1, 10):
        assignment = tracker.assign({"a": 0.60, "b": 0.30}, step * 0.1)
        assert assignment == {"ahead_1": "a"}, f"changed too early at t={step * 0.1}"
    # The challenge was first registered at t=0.1, so the 1 s hold expires at 1.1.
    assert tracker.assign({"a": 0.60, "b": 0.30}, 1.0) == {"ahead_1": "a"}
    assert tracker.assign({"a": 0.60, "b": 0.30}, 1.1) == {"ahead_1": "b"}
    change = tracker.changes[-1]
    assert change.slot == "ahead_1"
    assert change.previous_car_id == "a"
    assert change.car_id == "b"
    assert change.at_s == pytest.approx(1.1)


def test_an_interrupted_challenge_restarts_the_hold_window() -> None:
    tracker = SlotTracker(hysteresis_s=0.15, hold_s=1.0, slots=("ahead_1",))
    tracker.assign({"a": 0.60}, 0.0)
    for step in range(1, 9):
        tracker.assign({"a": 0.60, "b": 0.30}, step * 0.1)
    # 'b' falls back inside the margin; the pending challenge is dropped.
    tracker.assign({"a": 0.60, "b": 0.55}, 0.9)
    assert tracker.assign({"a": 0.60, "b": 0.30}, 1.0) == {"ahead_1": "a"}
    assert tracker.assign({"a": 0.60, "b": 0.30}, 1.9) == {"ahead_1": "a"}
    assert tracker.assign({"a": 0.60, "b": 0.30}, 2.0) == {"ahead_1": "b"}
    assert tracker.changes[-1].at_s == pytest.approx(2.0)


def test_a_slot_is_taken_immediately_when_its_occupant_leaves_that_side() -> None:
    """Hysteresis protects against noise, not against a car that overtook us."""
    tracker = SlotTracker(hysteresis_s=0.15, hold_s=1.0, slots=("ahead_1", "behind_1"))
    tracker.assign({"a": 0.60, "b": -0.90}, 0.0)
    assignment = tracker.assign({"a": -0.10, "b": 0.80}, 0.1)
    assert assignment == {"ahead_1": "b", "behind_1": "a"}
    reasons = [c.reason for c in tracker.changes if c.at_s == 0.1]
    assert all("incumbent left this side" in reason for reason in reasons)


def test_a_slot_identity_change_resets_that_slots_history(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    """The new occupant must not inherit the previous car's closing rate."""
    state = create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=3,
        own_config=own_config,
        rival_config=rival_config,
    )
    sequence = 0

    def batch(time_s: float, own_progress: float, gaps: dict[str, float]) -> list[TelemetryEvent]:
        nonlocal sequence
        events: list[TelemetryEvent] = []
        sequence += 1
        events.append(_event(sequence, OWN_CAR_ID, "progress_m", own_progress, "m", time_s))
        sequence += 1
        events.append(_event(sequence, OWN_CAR_ID, "speed_mps", 75.0, "m/s", time_s))
        for car_id, gap in gaps.items():
            sequence += 1
            events.append(_event(sequence, car_id, "progress_m", own_progress + gap, "m", time_s))
        return events

    context_ids = (RIVAL_CAR_ID, SECOND_RIVAL_ID)
    time_s = 0.0
    progress = 0.0
    # Phase 1: rival-a is nearest ahead and closing on us steadily.
    for _ in range(12):
        time_s += 0.5
        progress += 37.5
        update(
            batch(time_s, progress, {RIVAL_CAR_ID: 45.0, SECOND_RIVAL_ID: 400.0}),
            state,
            make_context(time_s, rival_car_ids=context_ids),
        )
    assert state.slots.occupants["ahead_1"] == RIVAL_CAR_ID
    assert state.tracks[RIVAL_CAR_ID].last_relative_speed_mps is not None

    # Phase 2: rival-b arrives much closer and holds it past the hold window.
    published = []
    for _ in range(8):
        time_s += 0.5
        progress += 37.5
        published.append(
            update(
                batch(time_s, progress, {RIVAL_CAR_ID: 45.0, SECOND_RIVAL_ID: 12.0}),
                state,
                make_context(time_s, rival_car_ids=context_ids),
            )
        )
    assert state.slots.occupants["ahead_1"] == SECOND_RIVAL_ID
    change = next(c for c in state.slot_changes if c.car_id == SECOND_RIVAL_ID)
    assert change.previous_car_id == RIVAL_CAR_ID
    assert change.slot == "ahead_1"
    belief = published[-1].rival_in_slot("ahead_1")
    assert belief is not None and belief.car_id == SECOND_RIVAL_ID
    # The change is announced on the estimate published at the moment it happened,
    # and the new occupant starts with no inherited closing rate.
    announcing = next(e for e in published if e.cutoff_s == pytest.approx(change.at_s))
    assert any("history was reset" in note for note in announcing.quality.notes)
    fresh = announcing.rival_in_slot("ahead_1")
    assert fresh is not None and fresh.car_id == SECOND_RIVAL_ID
    assert fresh.relative_speed_mps.value is None, (
        "the slot's closing rate must be cleared, not carried over from the previous car"
    )
    assert fresh.relative_speed_mps.quality is Quality.MISSING


def test_slots_are_unique_and_survive_a_state_round_trip(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    run = make_run(own_config, rival_config, scenario_id="slots", seed=87, duration_s=6.0)
    state = create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=9,
        own_config=own_config,
        rival_config=rival_config,
    )
    estimate = update(run.events, state, make_context(6.0))
    slots = [belief.slot for belief in estimate.rival_beliefs]
    assert len(slots) == len(set(slots))

    restored = create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=9,
        own_config=own_config,
        rival_config=rival_config,
    )
    restored.restore(state.snapshot())
    assert restored.slots.occupants == state.slots.occupants
    assert [c.slot for c in restored.slot_changes] == [c.slot for c in state.slot_changes]


# -- update_state ---------------------------------------------------------


def test_update_state_leaves_the_prior_untouched(own_config: OwnCarConfig, rival_config: RivalConfig) -> None:
    """The pure form lets a replay branch without corrupting the trunk."""
    run = make_run(own_config, rival_config, scenario_id="branch", seed=91, duration_s=6.0)
    prior = create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=11,
        own_config=own_config,
        rival_config=rival_config,
    )
    update(run.events_until(3.0), prior, make_context(3.0))
    before = prior.snapshot()

    posterior, estimate = update_state(
        tuple(e for e in run.events if 3.0 < e.source_time_s <= 6.0), prior, make_context(6.0)
    )
    assert prior.snapshot() == before, "update_state must not advance the prior"
    assert posterior.revision == prior.revision + 1
    assert estimate.revision == posterior.revision
    assert estimate.cutoff_s == pytest.approx(6.0)


# -- prediction -----------------------------------------------------------


def test_prediction_keeps_the_cutoff_and_only_advances_creation_time(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    """No new observation arrived, so the causal cutoff cannot move."""
    run = make_run(own_config, rival_config, scenario_id="predict", seed=93, duration_s=8.0)
    state = create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=13,
        own_config=own_config,
        rival_config=rival_config,
    )
    estimate = update(run.events, state, make_context(8.0))
    projected = predict(estimate, 9.5, state=state)

    assert projected.cutoff_s == pytest.approx(estimate.cutoff_s)
    assert projected.created_at_s == pytest.approx(9.5)
    assert projected.revision == estimate.revision + 1
    assert projected.contributing_event_ids == estimate.contributing_event_ids
    assert any("projected 1.500 s" in note for note in projected.quality.notes)


def test_prediction_widens_uncertainty_monotonically(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    run = make_run(own_config, rival_config, scenario_id="predict-wide", seed=95, duration_s=8.0)
    state = create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=15,
        own_config=own_config,
        rival_config=rival_config,
    )
    estimate = update(run.events, state, make_context(8.0))
    sigmas = []
    for horizon in (0.5, 1.0, 2.0, 4.0):
        projected = predict(estimate, 8.0 + horizon, state=state)
        sigma = projected.own_car.speed_mps.standard_deviation
        assert sigma is not None
        sigmas.append(sigma)
    assert sigmas == sorted(sigmas)
    base = estimate.own_car.speed_mps.standard_deviation
    assert base is not None and sigmas[0] > base


def test_prediction_does_not_mutate_the_estimator_state(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    run = make_run(own_config, rival_config, scenario_id="predict-pure", seed=97, duration_s=6.0)
    state = create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=17,
        own_config=own_config,
        rival_config=rival_config,
    )
    estimate = update(run.events, state, make_context(6.0))
    before = state.snapshot()
    predict(estimate, 7.0, state=state)
    assert state.snapshot() == before


def test_prediction_from_marginals_declares_that_it_is_an_approximation(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    """Without the estimator only the transported marginals exist; say so."""
    run = make_run(own_config, rival_config, scenario_id="predict-marginal", seed=99, duration_s=6.0)
    state = create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=19,
        own_config=own_config,
        rival_config=rival_config,
    )
    estimate = update(run.events, state, make_context(6.0))
    projected = predict(estimate, 7.0)

    assert projected.cutoff_s == pytest.approx(estimate.cutoff_s)
    assert projected.created_at_s == pytest.approx(7.0)
    assert projected.quality.overall is Quality.DEGRADED
    assert any("not a bound" in note for note in projected.quality.notes)
    sigma = projected.own_car.speed_mps.standard_deviation
    base = estimate.own_car.speed_mps.standard_deviation
    assert sigma is not None and base is not None and sigma > base


def test_prediction_backwards_is_refused(own_config: OwnCarConfig, rival_config: RivalConfig) -> None:
    run = make_run(own_config, rival_config, scenario_id="predict-back", seed=101, duration_s=4.0)
    state = create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=21,
        own_config=own_config,
        rival_config=rival_config,
    )
    estimate = update(run.events, state, make_context(4.0))
    with pytest.raises(ValueError, match="precedes the estimate"):
        predict(estimate, 3.0, state=state)


def test_prediction_without_energy_capability_keeps_it_closed(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    """Extrapolating in time cannot conjure an energy measurement."""
    run = make_run(
        own_config,
        rival_config,
        scenario_id="predict-no-energy",
        seed=103,
        duration_s=5.0,
        energy_channel=False,
    )
    state = create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=23,
        own_config=own_config,
        rival_config=rival_config,
    )
    estimate = update(run.events, state, make_context(5.0, with_energy=False))
    for projected in (predict(estimate, 6.0, state=state), predict(estimate, 6.0)):
        assert projected.quality.own_energy_capability is False
        assert projected.own_car.battery_energy_j.value is None


# -- provenance and quality ----------------------------------------------


def test_contributing_event_ids_are_real_accepted_events(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    run = make_run(own_config, rival_config, scenario_id="provenance", seed=105, duration_s=5.0)
    state = create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=25,
        own_config=own_config,
        rival_config=rival_config,
    )
    events = run.events_until(5.0)
    estimate = update(events, state, make_context(5.0))
    available = {event.event_id for event in events}
    assert estimate.contributing_event_ids
    assert set(estimate.contributing_event_ids) <= available
    assert len(set(estimate.contributing_event_ids)) == len(estimate.contributing_event_ids)


def test_channel_quality_reports_a_channel_the_source_never_sent(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    run = make_run(own_config, rival_config, scenario_id="quality", seed=107, duration_s=4.0)
    state = create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=27,
        own_config=own_config,
        rival_config=rival_config,
    )
    estimate = update(run.events, state, make_context(4.0))
    by_channel = {entry.channel: entry for entry in estimate.quality.channels}
    # The synthetic capability declares battery_temperature_k but the generator
    # never emits it; the estimate must say missing, not invent a temperature.
    assert by_channel["battery_temperature_k"].quality is Quality.MISSING
    assert by_channel["speed_mps"].quality is Quality.VALID
    assert estimate.own_car.battery_temperature_k.value is None


def test_the_race_context_reports_remaining_distance_or_nothing(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    run = make_run(own_config, rival_config, scenario_id="race-context", seed=109, duration_s=4.0)
    state = create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=29,
        own_config=own_config,
        rival_config=rival_config,
    )
    known = update(run.events, state, make_context(4.0, total_laps=8))
    assert known.race_context.remaining_distance_m.value is not None
    assert known.race_context.total_laps == 8

    unknown_state = create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=29,
        own_config=own_config,
        rival_config=rival_config,
    )
    unknown = update(run.events, unknown_state, make_context(4.0, total_laps=None))
    assert unknown.race_context.remaining_distance_m.value is None
    assert unknown.race_context.remaining_distance_m.quality is Quality.MISSING


def test_the_own_state_summary_handed_to_rivals_carries_its_variance(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    """The rival filter must receive real uncertainty, not a bare mean."""
    run = make_run(own_config, rival_config, scenario_id="own-summary", seed=111, duration_s=5.0)
    state = create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=31,
        own_config=own_config,
        rival_config=rival_config,
    )
    update(run.events, state, make_context(5.0))
    covariance = state.own.state.covariance
    assert float(covariance[STATE_SPEED, STATE_SPEED]) > 0.0
    assert float(covariance[STATE_PROGRESS, STATE_PROGRESS]) > 0.0
    assert np.allclose(covariance, covariance.T)
    assert float(np.min(np.linalg.eigvalsh(covariance))) >= -1e-6
