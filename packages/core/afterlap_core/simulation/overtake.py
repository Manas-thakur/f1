from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..config import Parameter, VerificationStatus
from .track import footprints_overlap, geometry_for

if TYPE_CHECKING:
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


STATUS_UNAVAILABLE = "unavailable"


REASON_CORRIDOR_UNKNOWN = "corridor_unknown"


CORRIDOR_UNKNOWN_DETAIL = (
    "width_at returns nan: the track source carries no corridor at this position and reports "
    "lateral_geometry_surveyed=False, so lateral position is not established; longitudinal gap "
    "alone can estimate a tow but cannot establish side-by-side space or contact probability"
)

CONTACT_CLEAR = "clear"
CONTACT_TOUCHING = "contact"


@dataclass(frozen=True, slots=True)
class StageOutcome:
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
    overtaking_car_id: str
    overtaken_car_id: str
    track_id: str
    corridor_known: bool

    lateral_geometry_surveyed: bool

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

    return 0.5 * (float(world.car_configs[a].length_m.value) + float(world.car_configs[b].length_m.value))


def corridor_known(world: WorldState, s_m: float) -> bool:

    return not math.isnan(world.track.width_at(s_m))


def corridor_surveyed(world: WorldState) -> bool:

    return bool(getattr(world.track, "lateral_geometry_surveyed", False))


class OvertakeTracker:
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

        self._separation_m = float("nan")
        self._contact = ContactAssessment(status=STATUS_PENDING, detail="no step has been observed yet")

    def update(self, world: WorldState) -> None:

        a, b = self.overtaking_car_id, self.overtaken_car_id
        follower = world.cars[a]
        leader = world.cars[b]
        now = world.race.session_time_s
        clear = clearance_m(world, a, b)

        delta = follower.progress_m - leader.progress_m
        separation = -delta - clear
        self._separation_m = separation

        if self._close_at_s is None and separation <= self.close_separation_m and delta < clear:
            self._close_at_s = now
        elif self._close_at_s is not None and self._pass_at_s is None and separation > self.close_release_m:
            self._close_at_s = None

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
                self._overlap_at_s = now

        if self._pass_at_s is None and delta > clear:
            if known and self._contact.status == CONTACT_TOUCHING:
                pass
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

    def retention_checkpoint(self, world: WorldState, checkpoint_id: str) -> StageOutcome:

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

    @property
    def separation_m(self) -> float:

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
