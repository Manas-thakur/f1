"""Overtake-permission state machine.

``UNKNOWN -> INELIGIBLE / ELIGIBLE_DETECTED -> ACTIVE``.

Transitions happen at the **interpolated crossing time** of a detection or
activation line, not at the tick boundary that happened to contain it
(``contracts/UNITS_TIME.md``, "Events crossing a step"). Two lines inside one
integration interval both fire, in crossing order. A missed detection is never
silently promoted: an activation crossing without a preceding detection leaves
the state exactly where it was.

The machine is conservative in one direction only. It downgrades a permission
(safety state, lap rollover, race-control invalidation) but it never upgrades
one, and ``UNKNOWN`` is absorbing until a detection resolves it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from afterlap_contracts import DetectionLine, EligibilityState

from ..timebase import EventPriority, crossing_time

__all__ = [
    "EligibilityMachine",
    "EligibilityTransition",
    "LineCrossing",
]

_LAP_SCOPED_STATES = (EligibilityState.ELIGIBLE_DETECTED, EligibilityState.ACTIVE)

_KIND_ORDER: dict[str, int] = {"detection": 0, "activation": 1, "checkpoint": 2, "timing": 3}


@dataclass(frozen=True, slots=True)
class LineCrossing:
    """One resolved crossing of a track line inside an integration interval."""

    line_id: str
    kind: str
    at_session_time_s: float
    at_progress_m: float
    lap_index: int


@dataclass(frozen=True, slots=True)
class EligibilityTransition:
    """A recorded state change, with the evidence that caused it."""

    at_session_time_s: float
    from_state: EligibilityState
    to_state: EligibilityState
    cause: str
    priority: EventPriority
    line_id: str | None = None
    at_progress_m: float | None = None
    detail: str | None = None

    @property
    def changed(self) -> bool:
        return self.from_state is not self.to_state


@dataclass(slots=True)
class EligibilityMachine:
    """Stateful overtake-permission tracker for one car.

    Lap-scoped counters (``detections_this_lap``, ``activations_this_lap``) and
    the permission itself reset at a lap rollover. Session-scoped counters
    (``total_detections``, ``total_activations``, ``invalidations``) do not.
    """

    detection_s_m: float
    activation_s_m: float
    track_length_m: float
    detection_line_id: str = "detect-1"
    activation_line_id: str = "activate-1"

    state: EligibilityState = EligibilityState.UNKNOWN
    observed_at_s: float | None = None
    activated_at_s: float | None = None

    detections_this_lap: int = 0
    activations_this_lap: int = 0
    total_detections: int = 0
    total_activations: int = 0
    invalidations: int = 0
    lap_resets: int = 0
    last_invalidation_reason: str | None = None

    transitions: list[EligibilityTransition] = field(default_factory=list)
    crossings: list[LineCrossing] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.track_length_m <= 0.0:
            raise ValueError("track_length_m must be positive")
        for value, name in ((self.detection_s_m, "detection_s_m"), (self.activation_s_m, "activation_s_m")):
            if not (0.0 <= value < self.track_length_m):
                raise ValueError(f"{name} must lie in [0, track_length_m)")

    @classmethod
    def from_lines(
        cls,
        lines: tuple[DetectionLine, ...],
        track_length_m: float,
    ) -> EligibilityMachine:
        """Build from a manifest's detection/activation lines.

        Raises when the pack does not declare both, because guessing a line
        location would be exactly the invented default the plan forbids.
        """
        detection = next((line for line in lines if line.kind == "detection"), None)
        activation = next((line for line in lines if line.kind == "activation"), None)
        if detection is None or activation is None:
            raise ValueError("the rule pack declares no detection/activation line pair")
        return cls(
            detection_s_m=detection.s_m,
            activation_s_m=activation.s_m,
            track_length_m=track_length_m,
            detection_line_id=detection.line_id,
            activation_line_id=activation.line_id,
        )

    def _crossings_in(
        self, t0: float, t1: float, progress0: float, progress1: float
    ) -> tuple[LineCrossing, ...]:
        if progress1 < progress0:
            raise ValueError("progress must not run backwards inside one interval")
        if t1 < t0:
            raise ValueError("session time must not run backwards inside one interval")
        if progress1 == progress0:
            return ()
        found: list[LineCrossing] = []
        first_lap = int(progress0 // self.track_length_m)
        last_lap = int(progress1 // self.track_length_m)
        for lap in range(first_lap, last_lap + 1):
            for s_m, line_id, kind in (
                (self.detection_s_m, self.detection_line_id, "detection"),
                (self.activation_s_m, self.activation_line_id, "activation"),
            ):
                threshold = lap * self.track_length_m + s_m
                if not (progress0 < threshold <= progress1):
                    continue
                at_s = crossing_time(t0, t1, progress0, progress1, threshold)
                if at_s is None:
                    continue
                found.append(
                    LineCrossing(
                        line_id=line_id,
                        kind=kind,
                        at_session_time_s=at_s,
                        at_progress_m=threshold,
                        lap_index=lap,
                    )
                )
        found.sort(key=lambda c: (c.at_session_time_s, _KIND_ORDER[c.kind], c.at_progress_m))
        return tuple(found)

    def advance(
        self,
        t0: float,
        t1: float,
        progress0: float,
        progress1: float,
        *,
        gap_condition_met: bool | None,
    ) -> tuple[EligibilityTransition, ...]:
        """Advance one integration interval and apply every line crossed in it.

        ``gap_condition_met`` is the sporting condition evaluated by the caller
        at the detection line. ``None`` means the pack could not resolve it; the
        machine then reports ``UNKNOWN`` rather than assuming permission.
        """
        applied: list[EligibilityTransition] = []
        for crossing in self._crossings_in(t0, t1, progress0, progress1):
            self.crossings.append(crossing)
            if crossing.kind == "detection":
                applied.append(self._apply_detection(crossing, gap_condition_met=gap_condition_met))
            else:
                applied.append(self._apply_activation(crossing))
        return tuple(applied)

    def _record(self, transition: EligibilityTransition) -> EligibilityTransition:
        self.transitions.append(transition)
        return transition

    def _apply_detection(
        self, crossing: LineCrossing, *, gap_condition_met: bool | None
    ) -> EligibilityTransition:
        previous = self.state
        if gap_condition_met is None:
            new_state = EligibilityState.UNKNOWN
            detail = "detection line crossed but the applicable gap condition is unresolved"
        elif gap_condition_met:
            new_state = EligibilityState.ELIGIBLE_DETECTED
            detail = "gap condition satisfied at the detection line"
        else:
            new_state = EligibilityState.INELIGIBLE
            detail = "gap condition not satisfied at the detection line"
        self.state = new_state
        self.observed_at_s = crossing.at_session_time_s
        self.activated_at_s = None
        self.detections_this_lap += 1
        self.total_detections += 1
        return self._record(
            EligibilityTransition(
                at_session_time_s=crossing.at_session_time_s,
                from_state=previous,
                to_state=new_state,
                cause="detection_crossing",
                priority=EventPriority.PHYSICAL_LINE_EVENT,
                line_id=crossing.line_id,
                at_progress_m=crossing.at_progress_m,
                detail=detail,
            )
        )

    def _apply_activation(self, crossing: LineCrossing) -> EligibilityTransition:
        previous = self.state
        if previous is EligibilityState.ELIGIBLE_DETECTED:
            self.state = EligibilityState.ACTIVE
            self.activated_at_s = crossing.at_session_time_s
            self.activations_this_lap += 1
            self.total_activations += 1
            detail = "activation crossing promoted an observed detection"
        elif previous is EligibilityState.UNKNOWN:
            detail = "activation crossing with unresolved eligibility; not promoted"
        else:
            detail = "activation crossing without a preceding eligible detection; not promoted"
        return self._record(
            EligibilityTransition(
                at_session_time_s=crossing.at_session_time_s,
                from_state=previous,
                to_state=self.state,
                cause="activation_crossing",
                priority=EventPriority.PHYSICAL_LINE_EVENT,
                line_id=crossing.line_id,
                at_progress_m=crossing.at_progress_m,
                detail=detail,
            )
        )

    def invalidate(self, at_session_time_s: float, reason: str) -> EligibilityTransition:
        """Race control invalidated the permission (safety car, VSC, red, instruction).

        ``UNKNOWN`` stays ``UNKNOWN``: an unresolved condition is not resolved
        into "ineligible" by a flag.
        """
        previous = self.state
        if previous in _LAP_SCOPED_STATES:
            self.state = EligibilityState.INELIGIBLE
            self.activated_at_s = None
            self.observed_at_s = at_session_time_s
        self.invalidations += 1
        self.last_invalidation_reason = reason
        return self._record(
            EligibilityTransition(
                at_session_time_s=at_session_time_s,
                from_state=previous,
                to_state=self.state,
                cause="race_control_invalidation",
                priority=EventPriority.SAFETY_OR_RULE_INVALIDATION,
                detail=reason,
            )
        )

    def reset_lap(self, at_session_time_s: float) -> EligibilityTransition:
        """Lap counter rolled over: reset lap-scoped state only.

        Session-scoped totals survive; an outstanding lap-scoped permission does
        not carry into the new lap.
        """
        previous = self.state
        self.detections_this_lap = 0
        self.activations_this_lap = 0
        self.lap_resets += 1
        if previous in _LAP_SCOPED_STATES:
            self.state = EligibilityState.INELIGIBLE
            self.activated_at_s = None
            self.observed_at_s = at_session_time_s
        return self._record(
            EligibilityTransition(
                at_session_time_s=at_session_time_s,
                from_state=previous,
                to_state=self.state,
                cause="lap_reset",
                priority=EventPriority.PHYSICAL_LINE_EVENT,
                detail="lap-scoped eligibility state reset; session totals retained",
            )
        )

    @property
    def permits_overtake_profile(self) -> bool:
        """Permission only — never a statement about available battery energy."""
        return self.state in _LAP_SCOPED_STATES
