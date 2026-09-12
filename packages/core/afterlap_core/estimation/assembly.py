"""Composition of the frozen ``StateEstimate`` contract.

This module owns the public entry points named in the module specification::

    update(events, prior, context) -> StateEstimate
    predict(estimate, target_time_s) -> StateEstimate

``prior`` is the estimator's memory -- covariance, particles, RNG streams, slot
assignments, mode memory and observation history. :func:`update` advances it and
returns the published view; :func:`update_state` is the pure form that leaves the
caller's prior untouched and hands back both the new memory and the estimate.

Identity slots
--------------

``ahead_1`` and ``behind_1`` are *stable* slots. A challenger must beat the
incumbent's absolute gap by ``slots.hysteresis_s`` and hold that margin for
``slots.hold_s`` before it takes the slot, so a car does not switch identity on a
tenth of a second of measurement noise. When a slot genuinely does change hands
the change is recorded in :attr:`EstimatorState.slot_changes` and that slot's
historical summaries are reset, because carrying a previous car's gap history
into a new occupant would fabricate a trend that never happened.

Causality
---------

Every observation later than ``context.cutoff_s`` is dropped in
:func:`afterlap_core.estimation.context.observations_from_events` before any
filter sees it, and its identifier never reaches ``contributing_event_ids``. An
estimate is therefore reproducible from its own cutoff.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from afterlap_contracts import (
    SCHEMA_VERSION,
    ChannelQuality,
    EstimateQuality,
    Provenance,
    Quality,
    RaceContext,
    RivalBelief,
    ScalarValue,
    StateEstimate,
    TelemetryEvent,
)
from afterlap_core.timebase import classify_freshness

from .config import OwnCarConfig, RivalConfig, load_own_car_config, load_rival_config
from .context import (
    OWN_CAR_CHANNELS,
    EstimationContext,
    Observation,
    RejectedObservation,
    observations_from_events,
)
from .own_car import (
    STATE_PROGRESS,
    STATE_SPEED,
    OwnCarFilter,
    build_own_car_estimate,
)
from .rivals import OwnStateSummary, RivalContext, RivalObservation, RivalParticleFilter

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

DEFAULT_SLOTS: tuple[str, ...] = ("ahead_1", "behind_1")

FULL_PRESSURE_GAP_S = 1.0


@dataclass(frozen=True, slots=True)
class SlotChange:
    """A recorded change of which car occupies an identity slot."""

    slot: str
    previous_car_id: str | None
    car_id: str
    at_s: float
    reason: str


@dataclass(slots=True)
class SlotTracker:
    """Hysteretic assignment of cars to stable identity slots."""

    hysteresis_s: float
    hold_s: float
    slots: tuple[str, ...] = DEFAULT_SLOTS
    occupants: dict[str, str] = field(default_factory=dict)
    pending: dict[str, tuple[str, float]] = field(default_factory=dict)
    changes: list[SlotChange] = field(default_factory=list)

    def assign(self, gaps_s: dict[str, float], now_s: float) -> dict[str, str]:
        """Return ``{slot: car_id}`` for the current gaps.

        ``gaps_s`` is signed: positive is ahead of us. A slot keeps its occupant
        unless a challenger is clearly and persistently closer.
        """
        result: dict[str, str] = {}
        for slot in self.slots:
            ahead = slot.startswith("ahead")
            candidates = sorted(
                ((car_id, gap) for car_id, gap in gaps_s.items() if (gap > 0.0) == ahead),
                key=lambda item: (abs(item[1]), item[0]),
            )
            if not candidates:
                previous = self.occupants.pop(slot, None)
                self.pending.pop(slot, None)
                if previous is not None:
                    self.changes.append(
                        SlotChange(
                            slot=slot,
                            previous_car_id=previous,
                            car_id="",
                            at_s=now_s,
                            reason="no car is on that side of us any more",
                        )
                    )
                continue
            best_id, best_gap = candidates[0]
            incumbent = self.occupants.get(slot)
            if incumbent is None:
                self._take(slot, incumbent, best_id, now_s, "slot was empty")
                result[slot] = best_id
                continue
            if incumbent not in gaps_s or (gaps_s[incumbent] > 0.0) != ahead:
                self._take(slot, incumbent, best_id, now_s, "the incumbent left this side of us")
                result[slot] = best_id
                continue
            if best_id == incumbent:
                self.pending.pop(slot, None)
                result[slot] = incumbent
                continue
            margin = abs(gaps_s[incumbent]) - abs(best_gap)
            if margin <= self.hysteresis_s:
                self.pending.pop(slot, None)
                result[slot] = incumbent
                continue
            challenger, since = self.pending.get(slot, (best_id, now_s))
            if challenger != best_id:
                challenger, since = best_id, now_s
            if now_s - since >= self.hold_s:
                self._take(
                    slot,
                    incumbent,
                    best_id,
                    now_s,
                    f"challenger held a {margin:.3f} s advantage for {now_s - since:.3f} s",
                )
                self.pending.pop(slot, None)
                result[slot] = best_id
            else:
                self.pending[slot] = (challenger, since)
                result[slot] = incumbent
        return result

    def _take(self, slot: str, previous: str | None, car_id: str, now_s: float, reason: str) -> None:
        self.occupants[slot] = car_id
        if previous != car_id:
            self.changes.append(
                SlotChange(slot=slot, previous_car_id=previous, car_id=car_id, at_s=now_s, reason=reason)
            )

    def changed_slots(self) -> tuple[str, ...]:
        return tuple(sorted({change.slot for change in self.changes}))

    def snapshot(self) -> dict[str, Any]:
        return {
            "hysteresis_s": self.hysteresis_s,
            "hold_s": self.hold_s,
            "slots": list(self.slots),
            "occupants": dict(self.occupants),
            "pending": {slot: list(value) for slot, value in self.pending.items()},
            "changes": [
                {
                    "slot": c.slot,
                    "previous_car_id": c.previous_car_id,
                    "car_id": c.car_id,
                    "at_s": c.at_s,
                    "reason": c.reason,
                }
                for c in self.changes
            ],
        }

    @classmethod
    def restore(cls, payload: dict[str, Any]) -> SlotTracker:
        return cls(
            hysteresis_s=float(payload["hysteresis_s"]),
            hold_s=float(payload["hold_s"]),
            slots=tuple(payload["slots"]),
            occupants=dict(payload["occupants"]),
            pending={slot: (value[0], float(value[1])) for slot, value in payload["pending"].items()},
            changes=[SlotChange(**item) for item in payload["changes"]],
        )


@dataclass(slots=True)
class RivalTrack:
    """Per-car gap bookkeeping the slot's summaries are reset from."""

    car_id: str
    last_gap_m: float | None = None
    last_gap_s: float | None = None
    last_relative_speed_mps: float | None = None
    last_observed_s: float | None = None
    event_ids: list[str] = field(default_factory=list)

    def reset_history(self) -> None:
        self.last_relative_speed_mps = None


@dataclass(slots=True)
class EstimatorState:
    """The estimator's complete replayable memory."""

    session_id: str
    car_id: str
    seed: int
    own_config: OwnCarConfig
    rival_config: RivalConfig
    own: OwnCarFilter
    rivals: dict[str, RivalParticleFilter] = field(default_factory=dict)
    tracks: dict[str, RivalTrack] = field(default_factory=dict)
    slot_tracker: SlotTracker | None = None
    revision: int = 0
    cutoff_s: float = 0.0
    last_context: EstimationContext | None = None
    rejected: list[RejectedObservation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def slots(self) -> SlotTracker:
        if self.slot_tracker is None:  # pragma: no cover - constructed in the factory
            raise RuntimeError("slot tracker was not initialised")
        return self.slot_tracker

    @property
    def slot_changes(self) -> tuple[SlotChange, ...]:
        return tuple(self.slots.changes)

    def copy(self) -> EstimatorState:
        clone = EstimatorState(
            session_id=self.session_id,
            car_id=self.car_id,
            seed=self.seed,
            own_config=self.own_config,
            rival_config=self.rival_config,
            own=OwnCarFilter(self.own_config),
            slot_tracker=SlotTracker.restore(self.slots.snapshot()),
            revision=self.revision,
            cutoff_s=self.cutoff_s,
            last_context=self.last_context,
            rejected=list(self.rejected),
            notes=list(self.notes),
        )
        clone.own.restore(self.own.snapshot())
        for car_id, filter_ in self.rivals.items():
            restored = RivalParticleFilter(self.rival_config, car_id=car_id, seed=self.seed)
            restored.restore(filter_.snapshot())
            clone.rivals[car_id] = restored
        clone.tracks = {
            car_id: RivalTrack(
                car_id=track.car_id,
                last_gap_m=track.last_gap_m,
                last_gap_s=track.last_gap_s,
                last_relative_speed_mps=track.last_relative_speed_mps,
                last_observed_s=track.last_observed_s,
                event_ids=list(track.event_ids),
            )
            for car_id, track in self.tracks.items()
        }
        return clone

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "car_id": self.car_id,
            "seed": self.seed,
            "revision": self.revision,
            "cutoff_s": self.cutoff_s,
            "own": self.own.snapshot(),
            "rivals": {car_id: f.snapshot() for car_id, f in sorted(self.rivals.items())},
            "tracks": {
                car_id: {
                    "car_id": t.car_id,
                    "last_gap_m": t.last_gap_m,
                    "last_gap_s": t.last_gap_s,
                    "last_relative_speed_mps": t.last_relative_speed_mps,
                    "last_observed_s": t.last_observed_s,
                    "event_ids": list(t.event_ids),
                }
                for car_id, t in sorted(self.tracks.items())
            },
            "slots": self.slots.snapshot(),
            "notes": list(self.notes),
        }

    def restore(self, payload: dict[str, Any]) -> None:
        self.session_id = payload["session_id"]
        self.car_id = payload["car_id"]
        self.seed = payload["seed"]
        self.revision = int(payload["revision"])
        self.cutoff_s = float(payload["cutoff_s"])
        self.own.restore(payload["own"])
        self.rivals = {}
        for car_id, snapshot in payload["rivals"].items():
            filter_ = RivalParticleFilter(self.rival_config, car_id=car_id, seed=self.seed)
            filter_.restore(snapshot)
            self.rivals[car_id] = filter_
        self.tracks = {car_id: RivalTrack(**item) for car_id, item in payload["tracks"].items()}
        self.slot_tracker = SlotTracker.restore(payload["slots"])
        self.notes = list(payload["notes"])


def create_state(
    *,
    session_id: str,
    car_id: str,
    seed: int = 0,
    own_config: OwnCarConfig | None = None,
    rival_config: RivalConfig | None = None,
    slots: tuple[str, ...] = DEFAULT_SLOTS,
) -> EstimatorState:
    """Build a fresh estimator memory from the manifests."""
    own_cfg = own_config or load_own_car_config()
    rival_cfg = rival_config or load_rival_config()
    return EstimatorState(
        session_id=session_id,
        car_id=car_id,
        seed=seed,
        own_config=own_cfg,
        rival_config=rival_cfg,
        own=OwnCarFilter(own_cfg),
        slot_tracker=SlotTracker(
            hysteresis_s=rival_cfg.slots.hysteresis_s.value,
            hold_s=rival_cfg.slots.hold_s.value,
            slots=slots,
        ),
    )


def _own_progress_series(observations: Sequence[Observation], car_id: str) -> tuple[np.ndarray, np.ndarray]:
    times: list[float] = []
    values: list[float] = []
    for observation in observations:
        if observation.car_id != car_id or not observation.usable:
            continue
        if observation.channel == "progress_m":
            times.append(observation.session_time_s)
            values.append(float(observation.value or 0.0))
    return np.array(times, dtype=np.float64), np.array(values, dtype=np.float64)


def _own_progress_at(
    session_time_s: float,
    series: tuple[np.ndarray, np.ndarray],
    fallback_progress_m: float,
    fallback_speed_mps: float,
    fallback_time_s: float,
) -> float:
    """Own progress at ``session_time_s``.

    Interpolates the own-car progress samples in the same batch when they exist,
    which is exact for a synchronised feed. Otherwise it extrapolates from the
    posterior at the cutoff at constant speed, which is an approximation and is
    declared as one in the estimate notes.
    """
    times, values = series
    if times.size >= 1:
        return float(np.interp(session_time_s, times, values))
    return fallback_progress_m - fallback_speed_mps * (fallback_time_s - session_time_s)


def _rival_observations(
    observations: Sequence[Observation],
    rival_id: str,
    own_series: tuple[np.ndarray, np.ndarray],
    own_progress_m: float,
    own_speed_mps: float,
    cutoff_s: float,
    track_length_m: float,
    *,
    gap_sigma_m: float,
    cadence_s: float,
) -> tuple[RivalObservation, ...]:
    """Turn permitted rival samples into gap/speed observations.

    Gaps are built at common progress from the progress channels. When the feed
    publishes ``gap_ahead_s`` / ``gap_behind_s`` directly those are carried
    through; otherwise the time gap is the distance gap over our own speed, which
    is a straight-line approximation and is flagged as such in the estimate notes.

    Samples are decimated to ``cadence_s``. A 20 Hz feed does not carry 20
    independent looks per second at a rival's intention -- consecutive samples of
    a gap that moves at metres per second are almost the same observation -- and
    feeding them all in would make the posterior sharpen by sqrt(20) every second
    on evidence that is not there. ``gap_sigma_m`` is passed through so the filter
    can charge the real differencing noise rather than a nominal figure.
    """
    by_time: dict[float, dict[str, Any]] = {}
    for observation in observations:
        if observation.car_id != rival_id or not observation.usable:
            continue
        entry = by_time.setdefault(
            observation.session_time_s, {"event_ids": [], "quality": observation.quality}
        )
        entry["event_ids"].append(observation.event_id)
        if observation.channel == "progress_m":
            entry["progress_m"] = float(observation.value or 0.0)
        elif observation.channel == "speed_mps":
            entry["speed_mps"] = float(observation.value or 0.0)
        elif observation.channel in ("gap_ahead_s", "gap_behind_s"):
            entry["gap_s"] = float(observation.value or 0.0)

    built: list[RivalObservation] = []
    last_kept: float | None = None
    for session_time_s in sorted(by_time):
        if last_kept is not None and session_time_s - last_kept < cadence_s:
            continue
        last_kept = session_time_s
        entry = by_time[session_time_s]
        gap_m: float | None = None
        gap_s: float | None = entry.get("gap_s")
        if "progress_m" in entry:
            own_here = _own_progress_at(session_time_s, own_series, own_progress_m, own_speed_mps, cutoff_s)
            gap_m = float(entry["progress_m"]) - own_here
            if abs(gap_m) > 0.5 * track_length_m:
                gap_m = None
        if gap_m is not None and gap_s is None and own_speed_mps > 1.0:
            gap_s = gap_m / own_speed_mps
        if gap_m is None and gap_s is not None and own_speed_mps > 1.0:
            gap_m = gap_s * own_speed_mps
        built.append(
            RivalObservation(
                session_time_s=session_time_s,
                gap_m=gap_m,
                gap_s=gap_s,
                rival_speed_mps=entry.get("speed_mps"),
                gap_sigma_m=gap_sigma_m,
                event_ids=tuple(entry["event_ids"]),
                quality=entry["quality"],
            )
        )
    return tuple(built)


def _pressure_from_gaps(gaps_s: dict[str, float]) -> float:
    """How hard we are being pressured from behind, in ``[0, 1]``."""
    behind = [abs(gap) for gap in gaps_s.values() if gap < 0.0]
    if not behind:
        return 0.0
    closest = min(behind)
    return float(max(0.0, min(1.0, 1.0 - closest / FULL_PRESSURE_GAP_S)))


def update(
    events: Iterable[TelemetryEvent],
    prior: EstimatorState,
    context: EstimationContext,
) -> StateEstimate:
    """Fuse ``events`` into ``prior`` and publish the posterior.

    ``prior`` is advanced in place. Use :func:`update_state` when the caller
    needs to keep the previous memory, for example to branch a replay.
    """
    accepted, rejected = observations_from_events(events, context)
    prior.rejected = list(rejected)
    prior.cutoff_s = context.cutoff_s
    prior.last_context = context
    prior.revision += 1

    own_observations = [
        obs for obs in accepted if obs.car_id == context.car_id and obs.channel in OWN_CAR_CHANNELS
    ]
    prior.own.ingest(own_observations, context)

    own_progress = float(prior.own.state.mean[STATE_PROGRESS])
    own_speed = float(prior.own.state.mean[STATE_SPEED])
    own_series = _own_progress_series(accepted, context.car_id)

    rival_ids = sorted(
        set(context.rival_car_ids) | {obs.car_id for obs in accepted if obs.car_id != context.car_id}
    )
    gaps_s: dict[str, float] = {}
    per_rival: dict[str, tuple[RivalObservation, ...]] = {}
    gap_sigma_m = math.sqrt(
        float(prior.own.state.covariance[STATE_PROGRESS, STATE_PROGRESS])
        + prior.own_config.measurement.progress_sigma_m.value**2
    )
    cadence_s = prior.rival_config.likelihood.belief_update_interval_s.value
    for rival_id in rival_ids:
        observations = _rival_observations(
            accepted,
            rival_id,
            own_series,
            own_progress,
            own_speed,
            context.cutoff_s,
            context.track_length_m,
            gap_sigma_m=gap_sigma_m,
            cadence_s=cadence_s,
        )
        per_rival[rival_id] = observations
        track = prior.tracks.setdefault(rival_id, RivalTrack(car_id=rival_id))
        for observation in observations:
            track.event_ids.extend(observation.event_ids)
        latest = next(
            (obs for obs in reversed(observations) if obs.gap_s is not None or obs.gap_m is not None),
            None,
        )
        if latest is not None:
            if latest.gap_m is not None and track.last_gap_m is not None and track.last_observed_s:
                dt = latest.session_time_s - track.last_observed_s
                if dt > 0.0:
                    track.last_relative_speed_mps = (latest.gap_m - track.last_gap_m) / dt
            track.last_gap_m = latest.gap_m
            track.last_gap_s = latest.gap_s
            track.last_observed_s = latest.session_time_s
        if track.last_gap_s is not None:
            gaps_s[rival_id] = track.last_gap_s

    assignments = prior.slots.assign(gaps_s, context.cutoff_s)
    changed = {change.slot for change in prior.slots.changes if change.at_s == context.cutoff_s}
    for slot in changed:
        occupant = assignments.get(slot)
        if occupant and occupant in prior.tracks:
            prior.tracks[occupant].reset_history()

    own_summary = OwnStateSummary(
        speed_mps=own_speed,
        speed_variance=float(prior.own.state.covariance[STATE_SPEED, STATE_SPEED]),
        acceleration_mps2=float(prior.own.state.mean[2]),
        progress_m=own_progress,
        progress_variance=float(prior.own.state.covariance[STATE_PROGRESS, STATE_PROGRESS]),
    )
    pressure = _pressure_from_gaps(gaps_s)

    beliefs: list[RivalBelief] = []
    for slot, rival_id in sorted(assignments.items()):
        filter_ = prior.rivals.get(rival_id)
        if filter_ is None:
            filter_ = RivalParticleFilter(
                prior.rival_config,
                car_id=rival_id,
                seed=prior.seed,
                time_s=prior.tracks[rival_id].last_observed_s or context.cutoff_s,
            )
            prior.rivals[rival_id] = filter_
        is_ahead = (prior.tracks[rival_id].last_gap_s or 0.0) > 0.0
        rival_context = RivalContext(
            is_ahead=is_ahead,
            pressure=pressure,
            dropout_s=context.observation_dropout_s,
        )
        for observation in per_rival.get(rival_id, ()):
            if observation.session_time_s < filter_.time_s:
                continue
            filter_.update(observation, own_summary, rival_context)
        if context.cutoff_s > filter_.time_s:
            filter_.propagate(context.cutoff_s - filter_.time_s, rival_context)
        track = prior.tracks[rival_id]
        beliefs.append(
            filter_.to_belief(
                slot=slot,
                is_ahead=is_ahead,
                now_s=context.cutoff_s,
                gap_s=track.last_gap_s,
                gap_m=track.last_gap_m,
                relative_speed_mps=track.last_relative_speed_mps,
                lateral_geometry_known=context.lateral_geometry_known,
                lap_time_s=_nominal_lap_time_s(context, own_speed),
                reference_speed_mps=own_speed if own_speed > 1.0 else None,
            )
        )

    return _assemble(prior, context, tuple(beliefs), accepted)


def update_state(
    events: Iterable[TelemetryEvent],
    prior: EstimatorState,
    context: EstimationContext,
) -> tuple[EstimatorState, StateEstimate]:
    """Pure form of :func:`update`: ``prior`` is left untouched."""
    posterior = prior.copy()
    estimate = update(events, posterior, context)
    return posterior, estimate


def predict(
    estimate: StateEstimate,
    target_time_s: float,
    *,
    state: EstimatorState | None = None,
) -> StateEstimate:
    """Extrapolate a published estimate to ``target_time_s``.

    ``cutoff_s`` does not move: no new observation has arrived, so the causal
    cutoff of the belief is unchanged and only ``created_at_s`` advances.

    With ``state`` the exact posterior covariance and the live particles are
    propagated; that is the accurate path and callers who hold the estimator
    should use it.

    Without ``state`` only the marginal standard deviations the contract
    transports are available, so the covariance is reconstructed as diagonal.
    The propagated uncertainty is then **approximate, not conservative**:
    discarding the progress/speed/acceleration cross-covariance can make the
    result either wider or narrower than the exact propagation, because those
    cross terms enter ``F P F^T`` with a sign. The returned quality is marked
    degraded and carries a note saying which path was taken, so a consumer can
    see that the number is an approximation rather than a bound.
    """
    if target_time_s < estimate.created_at_s:
        raise ValueError("prediction target precedes the estimate it starts from")
    if state is not None and state.last_context is not None:
        return _predict_with_state(estimate, target_time_s, state)
    return _predict_from_marginals(estimate, target_time_s)


def _predict_with_state(
    estimate: StateEstimate,
    target_time_s: float,
    state: EstimatorState,
) -> StateEstimate:
    context = state.last_context
    assert context is not None
    working = state.copy()
    working.own.predict_to(
        target_time_s,
        clock_uncertainty_s=context.effective_clock_uncertainty_s,
        power_w=working.own.state.energy.last_power_w,
    )
    horizon = target_time_s - estimate.created_at_s
    beliefs: list[RivalBelief] = []
    pressure = _pressure_from_gaps(
        {t.car_id: t.last_gap_s for t in working.tracks.values() if t.last_gap_s is not None}
    )
    own_speed = float(working.own.state.mean[STATE_SPEED])
    for belief in estimate.rival_beliefs:
        filter_ = working.rivals.get(belief.car_id)
        if filter_ is None:  # pragma: no cover - defensive
            beliefs.append(belief)
            continue
        rival_context = RivalContext(
            is_ahead=belief.is_ahead,
            pressure=pressure,
            dropout_s=context.observation_dropout_s + max(0.0, horizon),
        )
        if horizon > 0.0:
            filter_.propagate(horizon, rival_context)
        track = working.tracks.get(belief.car_id)
        offset = float(
            np.sum(filter_.particles.weights() * filter_.speed_offset(filter_.particles, rival_context))
        )
        gap_m = None if track is None or track.last_gap_m is None else track.last_gap_m + offset * horizon
        gap_s = None if gap_m is None or own_speed <= 1.0 else gap_m / own_speed
        beliefs.append(
            filter_.to_belief(
                slot=belief.slot,
                is_ahead=belief.is_ahead,
                now_s=target_time_s,
                gap_s=gap_s,
                gap_m=gap_m,
                relative_speed_mps=offset,
                lateral_geometry_known=belief.lateral_geometry_known,
                lap_time_s=_nominal_lap_time_s(context, own_speed),
                reference_speed_mps=own_speed if own_speed > 1.0 else None,
            )
        )
    working.revision = estimate.revision + 1
    return _assemble(
        working,
        context,
        tuple(beliefs),
        (),
        created_at_s=target_time_s,
        extra_notes=(f"projected {horizon:.3f} s beyond the cutoff using the live covariance and particles",),
    )


def _predict_from_marginals(estimate: StateEstimate, target_time_s: float) -> StateEstimate:
    """Conservative extrapolation from the contract's marginal uncertainties."""
    config = load_own_car_config()
    filter_ = OwnCarFilter(config)
    own = estimate.own_car
    horizon = target_time_s - estimate.created_at_s
    progress = own.progress_m.value
    speed = own.speed_mps.value
    acceleration = own.acceleration_mps2.value
    energy = own.battery_energy_j.value
    filter_.state.mean = np.array(
        [
            progress if progress is not None else 0.0,
            speed if speed is not None else 0.0,
            acceleration if acceleration is not None else 0.0,
            energy if energy is not None else math.nan,
        ],
        dtype=np.float64,
    )
    filter_.state.covariance = np.diag(
        np.array(
            [
                _variance(own.progress_m, config.initial.progress_sigma_m.value),
                _variance(own.speed_mps, config.initial.speed_sigma_mps.value),
                _variance(own.acceleration_mps2, config.initial.acceleration_sigma_mps2.value),
                _variance(own.battery_energy_j, config.initial.energy_sigma_j.value),
            ],
            dtype=np.float64,
        )
    )
    filter_.state.time_s = estimate.created_at_s
    filter_.state.started = progress is not None or speed is not None
    filter_.state.energy.initialised = energy is not None
    filter_.state.energy.last_power_w = own.electrical_power_w.value
    filter_.predict_to(
        target_time_s,
        clock_uncertainty_s=estimate.quality.clock_uncertainty_s,
        power_w=own.electrical_power_w.value,
    )
    context = EstimationContext(
        session_id=estimate.session_id,
        car_id=own.car_id,
        cutoff_s=estimate.cutoff_s,
        created_at_s=target_time_s,
        track_length_m=estimate.race_context.track_length_m,
        clock_uncertainty_s=estimate.quality.clock_uncertainty_s,
        lap=estimate.race_context.lap,
        total_laps=estimate.race_context.total_laps,
        position=estimate.race_context.position,
        flag_state=estimate.race_context.flag_state,
        flag_known=estimate.race_context.flag_known,
        eligibility=estimate.race_context.eligibility,
        eligibility_observed_at_s=estimate.race_context.eligibility_observed_at_s,
    )
    own_estimate, capability = build_own_car_estimate(filter_, context, at_time_s=target_time_s)
    if energy is not None:
        capability = estimate.quality.own_energy_capability
    notes = (
        *estimate.quality.notes,
        (
            f"projected {horizon:.3f} s from published marginals only; cross-covariance was not "
            "available, so this uncertainty is an approximation and not a bound"
        ),
    )
    quality = EstimateQuality(
        overall=Quality.DEGRADED if horizon > 0.0 else estimate.quality.overall,
        channels=estimate.quality.channels,
        clock_uncertainty_s=estimate.quality.clock_uncertainty_s,
        own_energy_capability=capability,
        residual_alarm=estimate.quality.residual_alarm,
        notes=notes,
    )
    return StateEstimate(
        schema_version=SCHEMA_VERSION,
        session_id=estimate.session_id,
        revision=estimate.revision + 1,
        cutoff_s=estimate.cutoff_s,
        created_at_s=target_time_s,
        own_car=(
            own_estimate if energy is None else own_estimate.revise(battery_energy_j=own.battery_energy_j)
        ),
        rival_beliefs=estimate.rival_beliefs,
        race_context=estimate.race_context,
        quality=quality,
        contributing_event_ids=estimate.contributing_event_ids,
    )


def _variance(value: ScalarValue, fallback_sigma: float) -> float:
    sigma = value.standard_deviation if value.standard_deviation is not None else fallback_sigma
    return float(sigma) ** 2


def _nominal_lap_time_s(context: EstimationContext, speed_mps: float) -> float:
    if speed_mps <= 1.0:
        return 0.0
    return context.track_length_m / speed_mps


def _assemble(
    state: EstimatorState,
    context: EstimationContext,
    beliefs: tuple[RivalBelief, ...],
    accepted: Sequence[Observation],
    *,
    created_at_s: float | None = None,
    extra_notes: tuple[str, ...] = (),
) -> StateEstimate:
    now_s = created_at_s if created_at_s is not None else context.publish_time_s
    own_estimate, capability = build_own_car_estimate(state.own, context, at_time_s=now_s)
    channels = _channel_qualities(state, context)
    notes: list[str] = []
    notes.extend(context.notes)
    notes.extend(state.own.state.notes)
    notes.extend(state.notes)
    notes.extend(extra_notes)
    if not capability:
        notes.append("own_energy_capability is False: precise energy advice is unsupported for this session")
    if beliefs and not context.lateral_geometry_known:
        notes.append("lateral placement is not resolvable from this source; contact-risk claims are blocked")
    for change in state.slots.changes:
        if change.at_s == context.cutoff_s:
            notes.append(
                f"slot {change.slot} changed from {change.previous_car_id or 'empty'} to "
                f"{change.car_id or 'empty'}; that slot's history was reset"
            )

    overall = _overall_quality(channels, capability=capability, residual_alarm=state.own.residual_alarm)
    quality = EstimateQuality(
        overall=overall,
        channels=channels,
        clock_uncertainty_s=context.effective_clock_uncertainty_s,
        own_energy_capability=capability,
        residual_alarm=state.own.residual_alarm,
        notes=tuple(dict.fromkeys(notes)),
    )

    contributing = list(dict.fromkeys(state.own.state.contributing_event_ids))
    for belief in beliefs:
        track = state.tracks.get(belief.car_id)
        if track is not None:
            contributing.extend(track.event_ids)
    contributing = list(dict.fromkeys(contributing))
    if accepted:
        known = {obs.event_id for obs in accepted}
        contributing = [event_id for event_id in contributing if event_id in known] or contributing

    return StateEstimate(
        schema_version=SCHEMA_VERSION,
        session_id=state.session_id,
        revision=state.revision,
        cutoff_s=context.cutoff_s,
        created_at_s=max(now_s, context.cutoff_s),
        own_car=own_estimate,
        rival_beliefs=beliefs,
        race_context=_race_context(state, context, own_estimate.progress_m.value),
        quality=quality,
        contributing_event_ids=tuple(contributing),
    )


def _channel_qualities(state: EstimatorState, context: EstimationContext) -> tuple[ChannelQuality, ...]:
    """Per-channel freshness, preferring the ingestion module's own assessment."""
    if context.channel_quality:
        return tuple(context.channel_quality)
    entries: list[ChannelQuality] = []
    for channel in sorted(OWN_CAR_CHANNELS):
        if not context.channel_is_supported(channel):
            continue
        diagnostic = state.own.state.diagnostics.get(channel)
        period = context.expected_period_for(channel)
        if diagnostic is None or diagnostic.observed_at_s is None:
            entries.append(
                ChannelQuality(
                    channel=channel,
                    car_id=context.car_id,
                    quality=Quality.MISSING,
                    expected_period_s=period,
                    reason=(
                        "no observation received on this channel"
                        if context.channel_is_measured(channel)
                        else "channel is declared supported but not measured by this source"
                    ),
                )
            )
            continue
        age = max(0.0, context.cutoff_s - diagnostic.observed_at_s)
        entries.append(
            ChannelQuality(
                channel=channel,
                car_id=context.car_id,
                quality=classify_freshness(age + context.effective_clock_uncertainty_s, period),
                last_source_time_s=diagnostic.observed_at_s,
                age_s=age,
                expected_period_s=period,
                reason=diagnostic.note,
            )
        )
    return tuple(entries)


def _overall_quality(
    channels: tuple[ChannelQuality, ...], *, capability: bool, residual_alarm: bool
) -> Quality:
    order = [Quality.VALID, Quality.DEGRADED, Quality.STALE, Quality.INVALID, Quality.MISSING]
    worst = Quality.VALID
    for entry in channels:
        if order.index(entry.quality) > order.index(worst):
            worst = entry.quality
    if worst is Quality.MISSING and any(c.quality is not Quality.MISSING for c in channels):
        worst = Quality.DEGRADED
    if not capability and worst is Quality.VALID:
        worst = Quality.DEGRADED
    if residual_alarm and order.index(worst) < order.index(Quality.DEGRADED):
        worst = Quality.DEGRADED
    return worst


def _race_context(state: EstimatorState, context: EstimationContext, progress_m: float | None) -> RaceContext:
    completed = state.own.state.completed_laps
    remaining: ScalarValue
    if context.total_laps is not None and progress_m is not None:
        total_distance = context.total_laps * context.track_length_m
        remaining = ScalarValue(
            value=max(0.0, total_distance - progress_m),
            unit="m",
            provenance=Provenance.ESTIMATED,
            quality=Quality.VALID,
            observed_at_s=context.cutoff_s,
            age_s=0.0,
        )
    else:
        remaining = ScalarValue.missing("m", Provenance.CONFIGURED)
    return RaceContext(
        lap=max(context.lap, completed),
        total_laps=context.total_laps,
        remaining_distance_m=remaining,
        track_length_m=context.track_length_m,
        flag_state=context.flag_state,
        flag_known=context.flag_known,
        eligibility=context.eligibility,
        eligibility_observed_at_s=context.eligibility_observed_at_s,
        position=context.position,
    )


__all__ = [
    "DEFAULT_SLOTS",
    "FULL_PRESSURE_GAP_S",
    "EstimatorState",
    "RivalTrack",
    "SlotChange",
    "SlotTracker",
    "create_state",
    "predict",
    "update",
    "update_state",
]
