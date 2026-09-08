"""The seam between the simulator and the learning environment.

Truth reaches the learner along exactly one path::

    Simulator.observe()  ->  TelemetryEvent stream  ->  estimation.update()
                                                     -> StateEstimate
                                                     -> FeatureEncoder

Nothing here reads ``WorldState``. :class:`ObservationBridge` is handed one
already-built :class:`~afterlap_core.simulation.Observation` at a time and never
holds a reference to the simulator, which is what makes the truth-mutation test
meaningful: replace every hidden rival state, keep the delivered observations
fixed, and the encoded vector is byte identical.

The rule context and the overtake-permission machine live here too. Without a
resolved permission the independent checker returns ``unknown`` for every
candidate and the planner accepts nothing, so a learning environment that never
ran an :class:`~afterlap_core.rules.EligibilityMachine` would have observed a
planner that could never plan.

This module deliberately does **not** re-implement A02's ingestion pipeline.
It performs the shape conversion that pipeline would perform and hands the
canonical events to A05's estimator; deduplication, backpressure and quality
tracking are the pipeline's job and are out of scope for an in-process training
loop. That limitation is recorded in ``handoffs/A07.md``.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field

from afterlap_contracts import (
    SCHEMA_VERSION,
    EligibilityState,
    Provenance,
    Quality,
    RuleContext,
    SessionMode,
    SourceCapability,
    StateEstimate,
    TelemetryEvent,
)

from ..estimation import EstimationContext, EstimatorState, create_state, update
from ..feature_manifest import LOOKAHEAD_OFFSETS_M
from ..rules import EligibilityMachine, RulePack, resolve_pack_context
from ..rules.state import CarState as RuleCarState
from ..simulation import Observation, ScenarioBundle
from .features import FeatureContext, HistorySummary, LookaheadSample

__all__ = [
    "SIMULATOR_SOURCE_ID",
    "BridgeTick",
    "ObservationBridge",
    "simulator_capability",
]

SIMULATOR_SOURCE_ID = "simulator"

#: Own-car observation channel -> (canonical channel, SI unit).
_OWN_CHANNEL_MAP: dict[str, tuple[str, str]] = {
    "speed_mps": ("speed_mps", "m/s"),
    "progress_m": ("progress_m", "m"),
    "s_m": ("lap_distance_m", "m"),
    "acceleration_mps2": ("acceleration_mps2", "m/s^2"),
    "battery_energy_j": ("battery_energy_j", "J"),
    "battery_temperature_k": ("battery_temperature_k", "K"),
    "electrical_power_w": ("electrical_power_w", "W"),
    "recharge_cumulative_j": ("recharge_ledger_j", "J"),
}

_CANONICAL_CHANNELS: tuple[str, ...] = tuple(sorted({name for name, _ in _OWN_CHANNEL_MAP.values()}))

#: Rival channels an external observer can genuinely derive. Rival stored energy
#: is never among them.
_RIVAL_CHANNELS: tuple[str, ...] = ("progress_m", "speed_mps")

_FORBIDDEN_RIVAL_FIELDS = frozenset(
    {"battery_energy_j", "battery_temperature_k", "recharge_this_lap_j", "recharge_cumulative_j"}
)


class TruthLeakError(RuntimeError):
    """A rival observation presented a channel the controller may not know."""


def simulator_capability(
    *,
    energy_channel_available: bool,
    rate_hz: float,
    clock_error_s: float = 0.0,
    observation_delay_s: float = 0.0,
) -> SourceCapability:
    """Declare exactly what this observation stream publishes.

    ``battery_energy_j`` appears only when the scenario's observation
    configuration actually carries it. A source that cannot see stored energy
    says so, and estimation then reports ``own_energy_capability=False`` rather
    than inventing a number.
    """
    supported = tuple(c for c in _CANONICAL_CHANNELS if c != "battery_energy_j" or energy_channel_available)
    limitations: tuple[str, ...] = (
        "synthetic simulated observations from a reduced physical model; not a measured car",
        f"observations are delayed by {observation_delay_s:.3f} s at the source",
        "rival records carry derived position and speed only; rival stored energy is never published",
    )
    if not energy_channel_available:
        limitations = (
            *limitations,
            "no battery-energy channel in this scenario: stored energy is not observable here",
        )
    return SourceCapability(
        source_id=SIMULATOR_SOURCE_ID,
        mode=SessionMode.SIMULATION,
        supported_channels=supported,
        measured_channels=supported,
        update_rates_hz=dict.fromkeys(supported, rate_hz),
        clock_error_s=clock_error_s,
        limitations=limitations,
    )


@dataclass(frozen=True, slots=True)
class BridgeTick:
    """One decision tick's controller-visible inputs."""

    estimate: StateEstimate
    rule_context: RuleContext | None
    feature_context: FeatureContext
    eligibility: EligibilityState
    capability_gaps: tuple[str, ...]
    observation_quality: Quality


@dataclass
class ObservationBridge:
    """Converts delivered observations into beliefs, contexts and features.

    One instance follows one ego car through one episode. ``reset`` clears every
    piece of per-episode memory, including the estimator, the permission machine
    and the short-horizon history buffers.
    """

    bundle: ScenarioBundle
    pack: RulePack
    session_id: str
    seed: int = 0
    remaining_distance_m: float | None = None
    start_progress_m: float | None = None
    """Ego progress the episode is measured from. Defaults to the scenario's own
    initial state; the environment overrides it after a declared warm-up."""

    _state: EstimatorState = field(init=False)
    _eligibility: EligibilityMachine | None = field(init=False, default=None)
    _capability: SourceCapability = field(init=False)
    _sequence: int = field(init=False, default=0)
    _last_progress_m: float | None = field(init=False, default=None)
    _last_time_s: float | None = field(init=False, default=None)
    _gap_history: deque[tuple[float, float]] = field(init=False)
    _energy_history: deque[tuple[float, float]] = field(init=False)
    _instruction_changes: deque[float] = field(init=False)
    _missed_executions: deque[float] = field(init=False)
    _last_instruction_change_s: float | None = field(init=False, default=None)
    _last_gap_prediction_s: float | None = field(init=False, default=None)
    _last_decoded_budget_j: float | None = field(init=False, default=None)
    _last_decoded_reserve_j: float | None = field(init=False, default=None)
    _instruction_hold_remaining_s: float | None = field(init=False, default=None)
    _last_estimate: StateEstimate | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        scenario = self.bundle.scenario
        self._capability = simulator_capability(
            energy_channel_available=bool(scenario.observation.energy_channel_available),
            rate_hz=1.0,
            observation_delay_s=float(scenario.observation.delay_s.value),
        )
        self.reset()

    # -- lifecycle ----------------------------------------------------------- #

    def reset(self) -> None:
        """Clear every piece of per-episode memory."""
        scenario = self.bundle.scenario
        self._state = create_state(session_id=self.session_id, car_id=scenario.ego_car_id, seed=self.seed)
        lines = self.pack.manifest.detection_lines
        try:
            self._eligibility = EligibilityMachine.from_lines(lines, self.bundle.track.length)
        except ValueError:
            # A pack without a detection/activation pair cannot resolve a
            # permission. That is reported as unknown eligibility, not guessed.
            self._eligibility = None
        self._sequence = 0
        self._last_progress_m = None
        self._last_time_s = None
        self._gap_history = deque(maxlen=64)
        self._energy_history = deque(maxlen=64)
        self._instruction_changes = deque(maxlen=64)
        self._missed_executions = deque(maxlen=64)
        self._last_instruction_change_s = None
        self._last_gap_prediction_s = None
        self._last_decoded_budget_j = None
        self._last_decoded_reserve_j = None
        self._instruction_hold_remaining_s = None
        self._last_estimate = None

    # -- controller-side bookkeeping ----------------------------------------- #

    def record_instruction_change(self, at_s: float) -> None:
        self._instruction_changes.append(at_s)
        self._last_instruction_change_s = at_s

    def record_missed_execution(self, at_s: float) -> None:
        self._missed_executions.append(at_s)

    def record_decoded_preferences(self, budget_j: float | None, reserve_j: float | None) -> None:
        self._last_decoded_budget_j = budget_j
        self._last_decoded_reserve_j = reserve_j

    def record_instruction_hold(self, remaining_s: float | None) -> None:
        self._instruction_hold_remaining_s = remaining_s

    @property
    def eligibility_state(self) -> EligibilityState:
        return EligibilityState.UNKNOWN if self._eligibility is None else self._eligibility.state

    # -- the tick ------------------------------------------------------------ #

    def observe(self, observation: Observation) -> BridgeTick:
        """Fuse one delivered observation and build every controller input."""
        for rival in observation.rivals:
            leaked = _FORBIDDEN_RIVAL_FIELDS.intersection(rival.keys())
            if leaked:
                raise TruthLeakError(
                    f"rival observation carries {sorted(leaked)}; the learner may not know rival "
                    "stored energy or thermal state"
                )

        scenario = self.bundle.scenario
        track_length = self.bundle.track.length
        now_s = observation.delivered_at_s
        cutoff_s = max(0.0, observation.observed_at_s)

        if observation.quality is not Quality.VALID or not observation.channels:
            # Nothing old enough has been delivered yet. The previous belief is
            # still the newest thing that exists; it is republished unchanged
            # rather than filled in with the present.
            estimate = self._republish(now_s, cutoff_s)
            context = self._feature_context(estimate, None, observation)
            return BridgeTick(
                estimate=estimate,
                rule_context=None,
                feature_context=context,
                eligibility=self.eligibility_state,
                capability_gaps=("observation_unavailable",),
                observation_quality=observation.quality,
            )

        progress_m = float(observation.channels["progress_m"])
        self._advance_eligibility(now_s, progress_m, observation)

        events = tuple(self._events_from(observation))
        estimation_context = EstimationContext(
            session_id=self.session_id,
            car_id=scenario.ego_car_id,
            cutoff_s=cutoff_s,
            track_length_m=track_length,
            created_at_s=now_s,
            lap=int(observation.channels.get("lap", 0.0)),
            rival_car_ids=tuple(c for c in scenario.car_ids if c != scenario.ego_car_id),
            capability=self._capability,
            eligibility=self.eligibility_state,
            eligibility_observed_at_s=(
                None if self._eligibility is None else self._eligibility.observed_at_s
            ),
            lateral_geometry_known=False,
        )
        estimate = update(events, self._state, estimation_context)
        estimate = self._with_remaining_distance(estimate, progress_m)

        rule_context, gaps = self._rule_context(observation, now_s)
        self._record_history(estimate, now_s)
        feature_context = self._feature_context(estimate, rule_context, observation)

        return BridgeTick(
            estimate=estimate,
            rule_context=rule_context,
            feature_context=feature_context,
            eligibility=self.eligibility_state,
            capability_gaps=gaps,
            observation_quality=observation.quality,
        )

    # -- internals ----------------------------------------------------------- #

    def _republish(self, now_s: float, cutoff_s: float) -> StateEstimate:
        """Publish the newest belief the estimator holds, aged to ``now_s``."""
        from ..estimation import predict

        last = self._last_estimate
        if last is None:
            # No belief exists yet at all. Build an explicitly empty one through
            # the estimator so every field carries its own missing quality.
            context = EstimationContext(
                session_id=self.session_id,
                car_id=self.bundle.scenario.ego_car_id,
                cutoff_s=cutoff_s,
                track_length_m=self.bundle.track.length,
                created_at_s=now_s,
                rival_car_ids=tuple(
                    c for c in self.bundle.scenario.car_ids if c != self.bundle.scenario.ego_car_id
                ),
                capability=self._capability,
            )
            estimate = update((), self._state, context)
            self._last_estimate = estimate
            return estimate
        return predict(last, now_s, state=self._state)

    def _with_remaining_distance(self, estimate: StateEstimate, progress_m: float) -> StateEstimate:
        """Attach the declared remaining race distance when one is configured.

        The distance is a *declared* scenario length, not a race-truth lookup:
        the environment configuration says how far the segment runs and the
        controller is entitled to know that.
        """
        self._last_estimate = estimate
        if self.remaining_distance_m is None:
            return estimate
        own_progress = estimate.own_car.progress_m.value
        travelled = 0.0 if own_progress is None else max(0.0, own_progress - self._start_progress_m())
        remaining = max(0.0, self.remaining_distance_m - travelled)
        race = estimate.race_context
        updated = race.model_copy(
            update={
                "remaining_distance_m": race.remaining_distance_m.model_copy(
                    update={"value": remaining, "quality": Quality.VALID}
                ),
                "eligibility": self.eligibility_state,
                "eligibility_observed_at_s": (
                    None if self._eligibility is None else self._eligibility.observed_at_s
                ),
            }
        )
        estimate = estimate.model_copy(update={"race_context": updated})
        self._last_estimate = estimate
        return estimate

    def _start_progress_m(self) -> float:
        if self.start_progress_m is not None:
            return float(self.start_progress_m)
        initial = self.bundle.scenario.initial_states[self.bundle.scenario.ego_car_id]
        return float(initial.progress_m.value)

    def _events_from(self, observation: Observation) -> Iterable[TelemetryEvent]:
        own_progress = float(observation.channels["progress_m"])
        source_time = max(0.0, observation.observed_at_s)
        for channel, value in observation.channels.items():
            mapped = _OWN_CHANNEL_MAP.get(channel)
            if mapped is None:
                continue
            name, unit = mapped
            if not self._capability.provides(name):
                continue
            yield self._event(observation.car_id, name, float(value), unit, source_time, observation)
        for rival in observation.rivals:
            rival_id = str(rival["car_id"])
            yield self._event(
                rival_id,
                "progress_m",
                own_progress + float(rival["relative_progress_m"]),
                "m",
                source_time,
                observation,
            )
            yield self._event(
                rival_id, "speed_mps", float(rival["speed_mps"]), "m/s", source_time, observation
            )

    def _event(
        self,
        car_id: str,
        channel: str,
        value: float,
        unit: str,
        source_time_s: float,
        observation: Observation,
    ) -> TelemetryEvent:
        self._sequence += 1
        return TelemetryEvent(
            schema_version=SCHEMA_VERSION,
            event_id=f"{self.session_id}:{self._sequence}",
            session_id=self.session_id,
            car_id=car_id,
            sequence=self._sequence,
            source_time_s=source_time_s,
            received_time_s=observation.delivered_at_s,
            channel=channel,
            value=value,
            unit=unit,
            provenance=Provenance.SIMULATED,
            quality=Quality.VALID,
        )

    def _advance_eligibility(self, now_s: float, progress_m: float, observation: Observation) -> None:
        if self._eligibility is None:
            return
        previous_progress = self._last_progress_m
        previous_time = self._last_time_s
        self._last_progress_m = progress_m
        self._last_time_s = now_s
        if previous_progress is None or previous_time is None:
            return
        if progress_m < previous_progress or now_s < previous_time:
            # Progress noise can read backwards across a tick. A crossing cannot
            # be resolved from a non-monotonic interval, so none is claimed.
            return
        ahead = observation.rival_ahead()
        gap_condition = None if ahead is None else abs(float(ahead["gap_s"])) <= 1.0
        self._eligibility.advance(
            previous_time, now_s, previous_progress, progress_m, gap_condition_met=gap_condition
        )

    def _rule_context(
        self, observation: Observation, now_s: float
    ) -> tuple[RuleContext | None, tuple[str, ...]]:
        """Resolve the applicable limits from the observation alone.

        With no energy channel the context resolves at the regulated floor. That
        is a fail-closed substitution which removes every profile needing usable
        energy, and the gap is reported rather than hidden behind a reading of
        zero.
        """
        gaps: list[str] = []
        manifest = self.pack.manifest
        if observation.has("battery_energy_j"):
            energy_j = observation.get("battery_energy_j")
        else:
            gaps.append("own_energy_unavailable")
            energy_j = float(manifest.battery_energy_min_j or 0.0)
        car_state = RuleCarState(
            speed_mps=max(0.0, observation.get("speed_mps")),
            battery_energy_j=max(0.0, energy_j),
            temperature_k=observation.get("battery_temperature_k"),
            recharge_used_this_lap_j=max(0.0, observation.get("recharge_this_lap_j")),
            eligibility=self.eligibility_state,
            eligibility_observed_at_s=(
                None if self._eligibility is None else self._eligibility.observed_at_s
            ),
            lap_index=int(observation.get("lap")),
        )
        context = resolve_pack_context(
            self.pack,
            max(0.0, observation.get("progress_m")),
            now_s,
            car_state,
            session_id=self.session_id,
        )
        return context, tuple(gaps)

    def _record_history(self, estimate: StateEstimate, now_s: float) -> None:
        ahead = estimate.rival_in_slot("ahead_1") or estimate.nearest_ahead
        if ahead is not None and ahead.gap_s.value is not None:
            self._gap_history.append((now_s, float(ahead.gap_s.value)))
        energy = estimate.own_car.battery_energy_j.value
        if energy is not None and estimate.quality.own_energy_capability:
            self._energy_history.append((now_s, float(energy)))

    def _rate_over(self, history: deque[tuple[float, float]], window_s: float) -> float | None:
        """Signed change per second over the trailing window, or ``None``."""
        if len(history) < 2:
            return None
        now_s, latest = history[-1]
        for time_s, value in reversed(history):
            if now_s - time_s >= window_s:
                span = now_s - time_s
                return (latest - value) / span if span > 0.0 else None
        first_time, first_value = history[0]
        span = now_s - first_time
        if span <= 0.0:
            return None
        return (latest - first_value) / span

    def _count_within(self, stamps: deque[float], now_s: float, window_s: float) -> int:
        return sum(1 for t in stamps if now_s - t <= window_s)

    def _feature_context(
        self,
        estimate: StateEstimate,
        rule_context: RuleContext | None,
        observation: Observation,
    ) -> FeatureContext:
        track = self.bundle.track
        now_s = estimate.created_at_s
        limits = rule_context.applicable_limits if rule_context is not None else None

        progress = estimate.own_car.progress_m.value
        remaining = estimate.race_context.remaining_distance_m.value
        lookahead: list[LookaheadSample] = []
        for offset in LOOKAHEAD_OFFSETS_M:
            if progress is None:
                lookahead.append(LookaheadSample(beyond_finish=False))
                continue
            beyond = remaining is not None and offset > remaining
            if beyond:
                lookahead.append(LookaheadSample(beyond_finish=True))
                continue
            s_m = (progress + offset) % track.length
            lookahead.append(
                LookaheadSample(
                    distance_ahead_m=offset,
                    curvature_inv_m=track.curvature_at(s_m),
                    grade_rad=track.grade_at(s_m),
                    # The applicable ceiling is only known where a rule context
                    # resolved. Future unknown eligibility stays masked rather
                    # than being predicted as a guaranteed permission.
                    deployment_ceiling_w=None if limits is None else limits.deployment_ceiling_w,
                    recovery_capacity_w=None if limits is None else limits.recovery_ceiling_w,
                )
            )

        driver = self.bundle.scenario.drivers[self.bundle.scenario.ego_car_id]
        car = self.bundle.car_configs[self.bundle.scenario.ego_car_id]
        temperature = estimate.own_car.battery_temperature_k.value
        headroom = (
            None if temperature is None else float(car.derate_start_temperature_k.value) - float(temperature)
        )

        gap_rate = self._rate_over(self._gap_history, 4.0)
        energy_rate = self._rate_over(self._energy_history, 4.0)
        innovation = None
        if self._gap_history and self._last_gap_prediction_s is not None:
            innovation = abs(self._gap_history[-1][1] - self._last_gap_prediction_s)
        if self._gap_history:
            self._last_gap_prediction_s = self._gap_history[-1][1]

        history = HistorySummary(
            gap_trend_4s=gap_rate,
            own_depletion_rate_4s_w=None if energy_rate is None else -energy_rate,
            gap_innovation_magnitude_s=innovation,
            missed_execution_count_8s=self._count_within(self._missed_executions, now_s, 8.0),
            last_decoded_budget_j=self._last_decoded_budget_j,
            last_decoded_reserve_target_j=self._last_decoded_reserve_j,
            time_since_instruction_change_s=(
                None
                if self._last_instruction_change_s is None
                else max(0.0, now_s - self._last_instruction_change_s)
            ),
            instruction_change_count_8s=self._count_within(self._instruction_changes, now_s, 8.0),
        )

        wet = None
        if "wet" in observation.context:
            wet = bool(observation.context["wet"])

        return FeatureContext(
            track_length_m=track.length,
            limits_deployment_ceiling_w=None if limits is None else limits.deployment_ceiling_w,
            limits_recovery_ceiling_w=None if limits is None else limits.recovery_ceiling_w,
            limits_recharge_allowance_remaining_j=(
                None if limits is None else limits.recharge_allowance_remaining_j
            ),
            thermal_headroom_k=headroom,
            instruction_hold_remaining_s=self._instruction_hold_remaining_s,
            driver_delay_mean_s=float(driver.reaction_delay_mean_s.value),
            driver_delay_std_s=float(driver.reaction_delay_std_s.value),
            wet_flag=wet,
            lookahead=tuple(lookahead),
            history=history,
        )
