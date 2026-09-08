"""The four-stage overtake state machine, driven from simulator truth.

``RACE_CONDITION_MODEL.md`` ("Traffic and overtaking") names the stages:

    An overtake event has stages: close, overlap, complete pass, and retain
    position at a later checkpoint. Reward/metrics distinguish them.

and ``OPPONENTS_AND_BRANCHING.md`` adds the rule that decides what this module
may and may not say:

    Track progress alone is insufficient for contact. ... If the reduced model
    cannot resolve a manoeuvre, report unsupported/uncertain rather than
    assigning an arbitrary collision probability.

Which stages survive an unknown corridor
----------------------------------------

Decision D-10: a compiled driven-line package has
``lateral_geometry_surveyed is False`` and ``width_at`` returns ``nan``. On such
a circuit there is no corridor *at all*, so:

===============  ============  ============================================
Stage            Availability  Decided from
===============  ============  ============================================
``close``        available     unwrapped longitudinal separation
``overlap``      **refused**   needs side-by-side space in an existing corridor
``pass_complete``available     unwrapped longitudinal separation
``retained``     available     the same, re-checked at a named checkpoint
===============  ============  ============================================

Contact is refused with ``overlap``, for the same reason and by the same test:
:func:`~afterlap_core.simulation.track.footprints_overlap` needs a lateral
position that means something, and where there is no corridor the lateral degree
of freedom is disabled rather than invented. A refused stage comes back as
:data:`STATUS_UNAVAILABLE` carrying the reason; it is never reported as
"not reached", which would read as evidence that the cars were never alongside.

A synthetic track document is a different case: it *declares* a width with
``synthetic_assumption`` provenance, the engine already allows lateral motion and
runs its footprint test on it, and so does this module -- while recording
``lateral_geometry_surveyed=False`` on the result so a decidable ``overlap``
there is never read as a measured one.

Everything here reads :class:`~afterlap_core.simulation.state.WorldState`
directly: stage labelling is simulator bookkeeping, not a controller
observation, and it must not be computed from delayed noisy channels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..config import Parameter, VerificationStatus
from .track import footprints_overlap, geometry_for

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .state import WorldState

SOURCE = "synthetic:afterlap-overtake-v1"

CLOSE_SEPARATION_M = Parameter(
    value=15.0,
    unit="m",
    source=SOURCE,
    verification=VerificationStatus.SYNTHETIC_ASSUMPTION,
    lower_bound=1.0,
    upper_bound=200.0,
    note=(
        "Nose-to-tail separation at or below which the follower counts as having *closed*. "
        "A staging threshold for metrics, not a physical limit; it is deliberately larger than "
        "the wake range's half-strength point so that closing is recorded before a tow is."
    ),
)

CLOSE_RELEASE_M = Parameter(
    value=25.0,
    unit="m",
    source=SOURCE,
    verification=VerificationStatus.SYNTHETIC_ASSUMPTION,
    lower_bound=1.0,
    upper_bound=400.0,
    note=(
        "Separation beyond which a *new* attempt may be armed after a previous one ended. "
        "The gap between this and the close threshold is the hysteresis that stops a jittery "
        "separation from producing a stream of close events."
    ),
)

STAGE_CLOSE = "close"
STAGE_OVERLAP = "overlap"
STAGE_PASS_COMPLETE = "pass_complete"
STAGE_RETAINED = "retained"

STAGES: tuple[str, ...] = (STAGE_CLOSE, STAGE_OVERLAP, STAGE_PASS_COMPLETE, STAGE_RETAINED)

STATUS_REACHED = "reached"
STATUS_NOT_REACHED = "not_reached"
STATUS_PENDING = "pending"
"""Decidable in principle, but the deciding event has not happened yet."""

STATUS_UNAVAILABLE = "unavailable"
"""The reduced model cannot decide this stage. Carries ``unavailable_reason``."""

REASON_CORRIDOR_UNKNOWN = "corridor_unknown"
"""There is no corridor here at all, so lateral space is not established."""

CORRIDOR_UNKNOWN_DETAIL = (
    "width_at returns nan: the track source carries no corridor at this position and reports "
    "lateral_geometry_surveyed=False, so lateral position is not established; longitudinal gap "
    "alone can estimate a tow but cannot establish side-by-side space or contact probability"
)

CONTACT_CLEAR = "clear"
CONTACT_TOUCHING = "contact"


@dataclass(frozen=True, slots=True)
class StageOutcome:
    """One stage of one overtake, with the reason for any unavailability."""

    stage: str
    status: str
    session_time_s: float | None = None
    detail: str = ""
    unavailable_reason: str | None = None

    @property
    def reached(self) -> bool:
        return self.status == STATUS_REACHED

    @property
    def unavailable(self) -> bool:
        return self.status == STATUS_UNAVAILABLE

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "session_time_s": self.session_time_s,
            "detail": self.detail,
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True, slots=True)
class ContactAssessment:
    """Whether the two footprints intersect, or why that cannot be decided."""

    status: str
    detail: str = ""
    unavailable_reason: str | None = None

    @property
    def unavailable(self) -> bool:
        return self.status == STATUS_UNAVAILABLE

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "detail": self.detail,
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True, slots=True)
class OvertakeRecord:
    """The four stages of one ordered pair, plus the corridor's honesty flags."""

    overtaking_car_id: str
    overtaken_car_id: str
    track_id: str
    corridor_known: bool
    """A finite corridor width is available here, so lateral claims are decidable."""
    lateral_geometry_surveyed: bool
    """Whether that corridor was surveyed. False plus ``corridor_known`` True means
    the widths are a declared synthetic assumption, not a measurement."""
    separation_m: float
    stages: tuple[StageOutcome, ...]
    contact: ContactAssessment

    def stage(self, name: str) -> StageOutcome:
        for outcome in self.stages:
            if outcome.stage == name:
                return outcome
        raise KeyError(f"unknown overtake stage {name!r}; the stages are {STAGES}")

    @property
    def reached(self) -> tuple[str, ...]:
        return tuple(outcome.stage for outcome in self.stages if outcome.reached)

    @property
    def unavailable(self) -> tuple[str, ...]:
        return tuple(outcome.stage for outcome in self.stages if outcome.unavailable)

    def as_dict(self) -> dict[str, Any]:
        return {
            "overtaking_car_id": self.overtaking_car_id,
            "overtaken_car_id": self.overtaken_car_id,
            "track_id": self.track_id,
            "corridor_known": self.corridor_known,
            "lateral_geometry_surveyed": self.lateral_geometry_surveyed,
            "separation_m": self.separation_m,
            "stages": [outcome.as_dict() for outcome in self.stages],
            "contact": self.contact.as_dict(),
        }


def clearance_m(world: WorldState, a: str, b: str) -> float:
    """Nose-to-tail longitudinal separation between two car *centres*.

    The same definition the engine's pass detector uses, so the two labellings
    cannot disagree about where "fully ahead" is.
    """
    return 0.5 * (float(world.car_configs[a].length_m.value) + float(world.car_configs[b].length_m.value))


def corridor_known(world: WorldState, s_m: float) -> bool:
    """True when the track source supplies a finite corridor width here.

    This is the same condition the engine already uses for the lateral degree of
    freedom (:meth:`~afterlap_core.simulation.track.TrackGeometry.lateral_limit`
    disables it on ``nan``), so the stage machine and the engine's own pass
    detector cannot disagree about whether lateral position means anything.

    It is deliberately *not* the same as
    :func:`corridor_surveyed`: a synthetic track document declares a width with
    ``synthetic_assumption`` provenance, which is enough to place two footprints
    relative to each other inside a synthetic scenario; a compiled driven-line
    package supplies no width at all, and that is the case where every lateral
    claim is refused.
    """
    return not math.isnan(world.track.width_at(s_m))


def corridor_surveyed(world: WorldState) -> bool:
    """Whether the corridor behind those widths was surveyed, or merely declared.

    Reported alongside every record so a decidable ``overlap`` on a synthetic
    corridor is never mistaken for a measured one.
    """
    return bool(getattr(world.track, "lateral_geometry_surveyed", False))


class OvertakeTracker:
    """Latching four-stage machine for one ordered pair, fed from truth.

    ``update`` is called once per step with the world; ``retention_checkpoint``
    is called when the named checkpoint fires. Stages latch: an overtake that is
    completed and then lost keeps ``pass_complete`` reached and answers
    ``retained`` with ``not_reached`` at the checkpoint, which is exactly the
    distinction the spec asks reward and metrics to preserve.
    """

    def __init__(
        self,
        overtaking_car_id: str,
        overtaken_car_id: str,
        *,
        retention_checkpoint_id: str | None = None,
        close_separation_m: float = float(CLOSE_SEPARATION_M.value),
        close_release_m: float = float(CLOSE_RELEASE_M.value),
    ) -> None:
        if close_release_m <= close_separation_m:
            raise ValueError(
                "the re-arm separation must exceed the close separation, otherwise the stage "
                "machine has no hysteresis and a jittery separation re-arms every step"
            )
        self.overtaking_car_id = overtaking_car_id
        self.overtaken_car_id = overtaken_car_id
        self.retention_checkpoint_id = retention_checkpoint_id
        self.close_separation_m = close_separation_m
        self.close_release_m = close_release_m

        self._close_at_s: float | None = None
        self._overlap_at_s: float | None = None
        self._pass_at_s: float | None = None
        self._lost_at_s: float | None = None
        self._retained: bool | None = None
        self._retained_at_s: float | None = None
        self._retained_checkpoint: str | None = None
        self._overlap_refusals = 0
        """How many steps wanted to decide ``overlap`` and could not."""

        self._separation_m = float("nan")
        self._contact = ContactAssessment(status=STATUS_PENDING, detail="no step has been observed yet")

    # -- truth-driven update ------------------------------------------------ #

    def update(self, world: WorldState) -> None:
        """Advance the stage machine from the current simulator truth."""
        a, b = self.overtaking_car_id, self.overtaken_car_id
        follower = world.cars[a]
        leader = world.cars[b]
        now = world.race.session_time_s
        clear = clearance_m(world, a, b)

        delta = follower.progress_m - leader.progress_m
        separation = -delta - clear  # nose-to-tail; negative once the extents overlap
        self._separation_m = separation

        # --- close: longitudinal only, always decidable --------------------
        if self._close_at_s is None and separation <= self.close_separation_m and delta < clear:
            self._close_at_s = now
        elif self._close_at_s is not None and self._pass_at_s is None and separation > self.close_release_m:
            # Dropped clearly back out of the battle without completing: re-arm.
            self._close_at_s = None

        # --- overlap and contact: need a corridor --------------------------
        known = corridor_known(world, follower.s_m) and corridor_known(world, leader.s_m)
        extents_overlap = abs(delta) < clear
        if not known:
            self._contact = ContactAssessment(
                status=STATUS_UNAVAILABLE,
                detail=CORRIDOR_UNKNOWN_DETAIL,
                unavailable_reason=REASON_CORRIDOR_UNKNOWN,
            )
            if extents_overlap:
                self._overlap_refusals += 1
        else:
            touching = self._footprints_overlap(world)
            provenance = "surveyed" if corridor_surveyed(world) else "declared (unsurveyed)"
            self._contact = ContactAssessment(
                status=CONTACT_TOUCHING if touching else CONTACT_CLEAR,
                detail=(
                    f"footprints {'intersect' if touching else 'do not intersect'} in the "
                    f"{provenance} corridor"
                ),
            )
            if self._overlap_at_s is None and extents_overlap and not touching:
                # Side by side with real space between them: the corridor was
                # surveyed, so this is a claim the model is entitled to make.
                self._overlap_at_s = now

        # --- pass_complete: longitudinal, with a contact veto when possible -
        if self._pass_at_s is None and delta > clear:
            if known and self._contact.status == CONTACT_TOUCHING:
                pass  # interlocked: no pass is credited, exactly as the engine rules
            else:
                self._pass_at_s = now
                self._lost_at_s = None
        elif self._pass_at_s is not None and delta < -clear and self._lost_at_s is None:
            self._lost_at_s = now

    def _footprints_overlap(self, world: WorldState) -> bool:
        a, b = self.overtaking_car_id, self.overtaken_car_id
        geometry = geometry_for(world.track)
        first, second = world.cars[a], world.cars[b]
        car_a, car_b = world.car_configs[a], world.car_configs[b]
        return footprints_overlap(
            geometry,
            first.s_m,
            first.lateral_d_m,
            first.heading_error_rad,
            float(car_a.length_m.value),
            float(car_a.width_m.value),
            second.s_m,
            second.lateral_d_m,
            second.heading_error_rad,
            float(car_b.length_m.value),
            float(car_b.width_m.value),
        )

    # -- retention ---------------------------------------------------------- #

    def retention_checkpoint(self, world: WorldState, checkpoint_id: str) -> StageOutcome:
        """Decide ``retained`` at a named checkpoint. Idempotent once decided."""
        if self.retention_checkpoint_id is not None and checkpoint_id != self.retention_checkpoint_id:
            return self._retained_outcome()
        if self._retained is not None:
            return self._retained_outcome()
        a, b = self.overtaking_car_id, self.overtaken_car_id
        delta = world.cars[a].progress_m - world.cars[b].progress_m
        clear = clearance_m(world, a, b)
        if self._pass_at_s is None:
            self._retained = False
            self._retained_at_s = world.race.session_time_s
            self._retained_checkpoint = checkpoint_id
            return self._retained_outcome()
        self._retained = delta > clear
        self._retained_at_s = world.race.session_time_s
        self._retained_checkpoint = checkpoint_id
        return self._retained_outcome()

    # -- reporting ---------------------------------------------------------- #

    def _retained_outcome(self) -> StageOutcome:
        if self._retained is None:
            return StageOutcome(
                stage=STAGE_RETAINED,
                status=STATUS_PENDING,
                detail=(
                    "the retention checkpoint "
                    f"{self.retention_checkpoint_id or '<any>'} has not been reached; retention is "
                    "undecided, not lost"
                ),
            )
        if self._retained:
            return StageOutcome(
                stage=STAGE_RETAINED,
                status=STATUS_REACHED,
                session_time_s=self._retained_at_s,
                detail=f"still ahead by more than one clearance at {self._retained_checkpoint}",
            )
        if self._pass_at_s is None:
            return StageOutcome(
                stage=STAGE_RETAINED,
                status=STATUS_NOT_REACHED,
                session_time_s=self._retained_at_s,
                detail=f"no pass had been completed by {self._retained_checkpoint}",
            )
        lost = "" if self._lost_at_s is None else f"; position lost at t={self._lost_at_s:.3f} s"
        return StageOutcome(
            stage=STAGE_RETAINED,
            status=STATUS_NOT_REACHED,
            session_time_s=self._retained_at_s,
            detail=(
                f"the pass completed at t={self._pass_at_s:.3f} s was not held to "
                f"{self._retained_checkpoint}{lost}"
            ),
        )

    def _close_outcome(self) -> StageOutcome:
        if self._close_at_s is None:
            return StageOutcome(
                stage=STAGE_CLOSE,
                status=STATUS_NOT_REACHED,
                detail=(
                    f"nose-to-tail separation never fell to {self.close_separation_m:g} m "
                    f"(last {self._separation_m:.3f} m)"
                ),
            )
        return StageOutcome(
            stage=STAGE_CLOSE,
            status=STATUS_REACHED,
            session_time_s=self._close_at_s,
            detail=f"closed to within {self.close_separation_m:g} m nose to tail",
        )

    def _overlap_outcome(self, world: WorldState) -> StageOutcome:
        follower = world.cars[self.overtaking_car_id]
        if self._overlap_at_s is not None:
            return StageOutcome(
                stage=STAGE_OVERLAP,
                status=STATUS_REACHED,
                session_time_s=self._overlap_at_s,
                detail="along-track extents overlapped with clear footprints in an available corridor",
            )
        if not corridor_known(world, follower.s_m):
            return StageOutcome(
                stage=STAGE_OVERLAP,
                status=STATUS_UNAVAILABLE,
                detail=(
                    f"{CORRIDOR_UNKNOWN_DETAIL}; {self._overlap_refusals} step(s) had overlapping "
                    "along-track extents and could not be resolved either way"
                ),
                unavailable_reason=REASON_CORRIDOR_UNKNOWN,
            )
        return StageOutcome(
            stage=STAGE_OVERLAP,
            status=STATUS_NOT_REACHED,
            detail="the cars were never side by side with clear footprints",
        )

    def _pass_outcome(self) -> StageOutcome:
        if self._pass_at_s is None:
            return StageOutcome(
                stage=STAGE_PASS_COMPLETE,
                status=STATUS_NOT_REACHED,
                detail="the follower never got a full clearance ahead in unwrapped progress",
            )
        lost = "" if self._lost_at_s is None else f"; later lost at t={self._lost_at_s:.3f} s"
        return StageOutcome(
            stage=STAGE_PASS_COMPLETE,
            status=STATUS_REACHED,
            session_time_s=self._pass_at_s,
            detail=f"a full clearance ahead in unwrapped progress{lost}",
        )

    def record(self, world: WorldState) -> OvertakeRecord:
        """The typed four-stage record as it stands now."""
        follower = world.cars[self.overtaking_car_id]
        return OvertakeRecord(
            overtaking_car_id=self.overtaking_car_id,
            overtaken_car_id=self.overtaken_car_id,
            track_id=world.track.id,
            corridor_known=corridor_known(world, follower.s_m),
            lateral_geometry_surveyed=corridor_surveyed(world),
            separation_m=self._separation_m,
            stages=(
                self._close_outcome(),
                self._overlap_outcome(world),
                self._pass_outcome(),
                self._retained_outcome(),
            ),
            contact=self._contact,
        )

    # -- convenience -------------------------------------------------------- #

    @property
    def separation_m(self) -> float:
        """Nose-to-tail separation at the last observed step; ``nan`` before the first."""
        return self._separation_m

    def as_dict(self, world: WorldState) -> dict[str, Any]:
        return self.record(world).as_dict()


def stage_report(
    world: WorldState,
    overtaking_car_id: str,
    overtaken_car_id: str,
    *,
    retention_checkpoint_id: str | None = None,
) -> OvertakeRecord:
    """One-shot evaluation of the stages at the current instant.

    Convenience for a caller that has not been tracking the pair: it observes
    the world once and reports. Latching stages that happened earlier are
    invisible to it, so a run that cares about history keeps an
    :class:`OvertakeTracker` instead.
    """
    tracker = OvertakeTracker(
        overtaking_car_id, overtaken_car_id, retention_checkpoint_id=retention_checkpoint_id
    )
    tracker.update(world)
    return tracker.record(world)


__all__ = [
    "CLOSE_RELEASE_M",
    "CLOSE_SEPARATION_M",
    "CONTACT_CLEAR",
    "CONTACT_TOUCHING",
    "CORRIDOR_UNKNOWN_DETAIL",
    "REASON_CORRIDOR_UNKNOWN",
    "SOURCE",
    "STAGES",
    "STAGE_CLOSE",
    "STAGE_OVERLAP",
    "STAGE_PASS_COMPLETE",
    "STAGE_RETAINED",
    "STATUS_NOT_REACHED",
    "STATUS_PENDING",
    "STATUS_REACHED",
    "STATUS_UNAVAILABLE",
    "ContactAssessment",
    "OvertakeRecord",
    "OvertakeTracker",
    "StageOutcome",
    "clearance_m",
    "corridor_known",
    "corridor_surveyed",
    "stage_report",
]
