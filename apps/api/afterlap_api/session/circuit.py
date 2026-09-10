"""Real-circuit identity for a session: track package, event overlay, conditions.

A session that runs on a compiled circuit must be able to *prove* which
circuit it ran on. That means three separate things, all resolved before the
runtime exists and all recorded on the manifest:

* the **track package** — its ``package_hash``, the readiness rung the
  independent validator derived from evidence, and the geometry provenance;
* the **event overlay** — the hashed FIA document set for one calendar event.
  An unreviewed overlay is *accepted* (the queue must be visible) but every
  numeric value it carries resolves to unknown, and that is recorded rather
  than quietly treated as a permission;
* the **conditions tape** — its ``content_hash``, bound to the track frame as
  an :class:`~afterlap_core.simulation.track_source.EnvironmentField`.

Every failure here is an explicit refusal that names the reason. There is no
silent default and no substitution: an unknown track id, an unknown event id,
an unknown conditions id and a package below ``geometry_validated`` are four
different messages, because they need four different operator actions.

Nothing in this module makes a run *real*. Car, battery and driver parameters
remain the shipped synthetic documents, so a session on a compiled package is
labelled :data:`REAL_CIRCUIT_LABEL` and the label travels with every
operator-facing status string for that session (D-10).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from afterlap_contracts import MINIMUM_READINESS_TO_DRIVE, REAL_CIRCUIT_LABEL, ErrorCode
from afterlap_core.conditions import ConditionsTape, ConditionsUnavailable, environment_for, load_conditions
from afterlap_core.config import list_configs
from afterlap_core.paths import Paths, sha256_json
from afterlap_core.tracks.fia_overlay import overlay_effective_values
from afterlap_core.tracks.loader import (
    TrackPackageError,
    list_track_packages,
    load_event_overlay,
    load_track_package,
    require_readiness,
)
from afterlap_core.tracks.package import (
    CorridorQuality,
    EventOverlay,
    ReadinessStatus,
    TrackPackage,
    readiness_rank,
)
from afterlap_core.tracks.registry import load_registry

from ..db import LifecycleError

MINIMUM_READINESS = ReadinessStatus(MINIMUM_READINESS_TO_DRIVE)
"""``load_track`` refuses anything below this rung; so does this module, first, with a reason.

Derived from the contract constant rather than restated, so the rung the
catalogue advertises as ``minimum_readiness_to_drive`` and the rung a session
is actually refused below cannot drift apart.
"""

SYNTHETIC_SKETCH_GEOMETRY_NOTE = (
    "Track geometry is a synthetic sketch, not a compiled real circuit: curvature, grade and "
    "corridor widths are invented parameters with declared provenance."
)

UNKNOWN_CORRIDOR_NOTE = (
    "The compiled package has no usable corridor (corridor_quality=unknown): lap width is unknown, "
    "the lateral degree of freedom is disabled and no contact or wheel-to-wheel claim is made."
)


class CircuitRefusal(LifecycleError):
    """A named refusal to resolve a circuit, event or conditions identifier."""

    def __init__(self, code: ErrorCode, message: str, **details: Any) -> None:
        super().__init__(code, message, **details)


@dataclass(frozen=True, slots=True)
class CircuitIdentity:
    """Everything about a session's circuit that a consumer can verify.

    Every hash here is reproducible from local artefacts: re-read the package
    document and re-hash it, re-read the overlay and re-hash it, re-read the
    frozen tape and re-hash it. A field is ``None`` only when the thing it
    describes genuinely does not exist for this session -- never as a
    placeholder for something unknown.
    """

    track_id: str
    compiled: bool
    track_package_hash: str | None = None
    track_readiness: str | None = None
    geometry_provenance: str | None = None
    corridor_quality: str | None = None
    lateral_geometry_surveyed: bool = False
    event_id: str | None = None
    event_package_hash: str | None = None
    event_review_status: str | None = None
    event_unknown_fields: tuple[str, ...] = ()
    conditions_id: str | None = None
    conditions_hash: str | None = None
    conditions_source_kind: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def real_circuit(self) -> bool:
        return self.compiled

    @property
    def status_label(self) -> str | None:
        """The operator-facing label for a run on a compiled circuit."""
        return REAL_CIRCUIT_LABEL if self.compiled else None

    def persisted_columns(self) -> dict[str, str | None]:
        """The identity columns on the ``session`` row, exactly as stored."""
        return {
            "track_id": self.track_id,
            "track_package_hash": self.track_package_hash,
            "event_id": self.event_id,
            "event_package_hash": self.event_package_hash,
            "conditions_id": self.conditions_id,
            "conditions_hash": self.conditions_hash,
            "track_readiness": self.track_readiness,
            "geometry_provenance": self.geometry_provenance,
        }


def overlay_content_hash(overlay: EventOverlay) -> str:
    """Content hash of an event overlay document.

    ``EventOverlay`` carries no hash of its own, so the identity of the overlay
    a session ran against is the hash of its canonical JSON. A consumer proves
    it by re-reading ``artifacts/tracks/<track>/events/<event>.json`` and
    hashing the parsed document the same way.
    """
    return sha256_json(overlay.model_dump(mode="json"))


def has_synthetic_sketch(track_id: str, paths: Paths | None = None) -> bool:
    """True when ``configs/tracks/<id>.yaml`` exists, i.e. a synthetic sketch."""
    return ((paths or Paths.default()).configs / "tracks" / f"{track_id}.yaml").exists()


def _known_track_ids(paths: Paths | None) -> list[str]:
    """Sketches and compiled packages, for a refusal that names what exists."""
    try:
        sketches = set(list_configs("tracks", paths))
    except FileNotFoundError:
        sketches = set()
    return sorted(sketches | set(list_track_packages(paths)))


def _known_conditions_ids(paths: Paths | None) -> list[str]:
    try:
        return list(list_configs("conditions", paths))
    except FileNotFoundError:
        return []


def resolve_track_package(track_id: str, paths: Paths | None = None) -> TrackPackage | None:
    """Resolve the compiled package for ``track_id``, or ``None`` for a sketch.

    Refusals are separated on purpose:

    * a synthetic sketch resolves to ``None`` and the caller stays on the
      pre-A16 path;
    * an id with neither sketch nor package is :data:`ErrorCode.NOT_FOUND` and
      names what does exist;
    * a package that is present but unhashed, tampered or mis-declared is
      ``VALIDATION_FAILED`` with the loader's reason;
    * a package below ``geometry_validated`` is ``VALIDATION_FAILED`` with the
      **readiness** reason and the rung it actually holds.
    """
    if has_synthetic_sketch(track_id, paths):
        return None

    try:
        package = load_track_package(track_id, paths)
    except TrackPackageError as exc:
        raise CircuitRefusal(
            ErrorCode.NOT_FOUND,
            f"track {track_id!r} has no synthetic sketch in configs/tracks and no loadable compiled "
            f"package: {exc}",
            track_id=track_id,
            available_tracks=", ".join(_known_track_ids(paths)),
        ) from exc

    try:
        require_readiness(package, MINIMUM_READINESS)
    except TrackPackageError as exc:
        raise CircuitRefusal(
            ErrorCode.VALIDATION_FAILED,
            str(exc),
            track_id=track_id,
            track_readiness=package.validation.status.value,
            required_readiness=MINIMUM_READINESS.value,
            track_package_hash=package.package_hash,
        ) from exc
    return package


def describe_track(track: Any, package: TrackPackage | None) -> CircuitIdentity:
    """Build the track half of the identity from the resolved source."""
    if package is None:
        return CircuitIdentity(
            track_id=str(track.id),
            compiled=False,
            geometry_provenance=str(getattr(track, "geometry_provenance", "unknown")),
            lateral_geometry_surveyed=bool(getattr(track, "lateral_geometry_surveyed", False)),
            notes=(SYNTHETIC_SKETCH_GEOMETRY_NOTE,),
        )

    corridor = package.geometry.corridor_quality
    notes: list[str] = [
        (
            f"{REAL_CIRCUIT_LABEL}: compiled circuit geometry with synthetic car, battery and driver "
            f"parameters. Geometry provenance {package.geometry.provenance.value}, readiness "
            f"{package.validation.status.value}."
        )
    ]
    if corridor is CorridorQuality.UNKNOWN:
        notes.append(UNKNOWN_CORRIDOR_NOTE)
    if readiness_rank(package.validation.status) < readiness_rank(ReadinessStatus.SIMULATION_ELIGIBLE):
        notes.append(
            f"Readiness is {package.validation.status.value}, below simulation_eligible: this session "
            "is not a validated real-track claim."
        )
    return CircuitIdentity(
        track_id=package.track_id,
        compiled=True,
        track_package_hash=package.package_hash or package.content_hash(),
        track_readiness=package.validation.status.value,
        geometry_provenance=package.geometry.provenance.value,
        corridor_quality=corridor.value,
        lateral_geometry_surveyed=package.lateral_geometry_known,
        notes=tuple(notes),
    )


def _available_overlays(track_id: str, paths: Paths | None) -> list[str]:
    from afterlap_core.tracks.loader import package_dir

    root = package_dir(track_id, paths) / "events"
    if not root.is_dir():
        return []
    return sorted(p.stem for p in root.glob("*.json") if p.name.count(".") == 1)


def resolve_event(
    identity: CircuitIdentity,
    event_id: str | None,
    paths: Paths | None = None,
) -> CircuitIdentity:
    """Attach the event overlay named by ``event_id``, refusing an unknown one.

    An unreviewed or one-reviewer overlay is accepted so the review queue is
    visible on the manifest, but :func:`overlay_effective_values` returns
    ``None`` for every numeric field and the identity records that. Unknown is
    never a permission.
    """
    if event_id is None:
        return identity
    if not identity.compiled:
        raise CircuitRefusal(
            ErrorCode.VALIDATION_FAILED,
            f"event {event_id!r} cannot be applied to track {identity.track_id!r}: an event overlay "
            "belongs to a compiled circuit package, and this session resolved a synthetic sketch",
            event_id=event_id,
            track_id=identity.track_id,
        )

    try:
        registry = load_registry(paths)
    except (FileNotFoundError, ValueError) as exc:
        raise CircuitRefusal(
            ErrorCode.NOT_FOUND,
            f"event {event_id!r} cannot be verified: the season registry is unavailable ({exc})",
            event_id=event_id,
        ) from exc

    try:
        entry, _calendar = registry.find_event(event_id)
    except KeyError as exc:
        raise CircuitRefusal(
            ErrorCode.NOT_FOUND,
            f"event {event_id!r} is not in the {registry.season} circuit registry",
            event_id=event_id,
            available_events=", ".join(sorted(e for x in registry.entries for e in x.event_ids)),
        ) from exc
    if entry.track_id != identity.track_id:
        raise CircuitRefusal(
            ErrorCode.VALIDATION_FAILED,
            f"event {event_id!r} is held at circuit {entry.track_id!r}, not {identity.track_id!r}; "
            "calendar event and physical circuit are separate identities",
            event_id=event_id,
            track_id=identity.track_id,
            event_track_id=entry.track_id,
        )

    try:
        overlay = load_event_overlay(identity.track_id, event_id, paths)
    except TrackPackageError as exc:
        raise CircuitRefusal(
            ErrorCode.NOT_FOUND,
            f"track {identity.track_id!r} has no ingested event overlay for {event_id!r}: {exc}",
            event_id=event_id,
            track_id=identity.track_id,
            available_overlays=", ".join(_available_overlays(identity.track_id, paths)),
        ) from exc
    except ValueError as exc:
        raise CircuitRefusal(
            ErrorCode.VALIDATION_FAILED,
            f"event overlay {event_id!r} for track {identity.track_id!r} is malformed: {exc}",
            event_id=event_id,
            track_id=identity.track_id,
        ) from exc

    effective = overlay_effective_values(overlay)
    unresolved = tuple(sorted(name for name, value in effective.items() if value is None))
    notes = list(identity.notes)
    if not overlay.is_confirmed:
        notes.append(
            f"Event overlay {event_id!r} is {overlay.review_status} ({len(set(overlay.reviewers))} of 2 "
            "reviewers): every numeric FIA value it carries resolves to unknown, never to a permission. "
            "event_curve_unknown applies."
        )
    if unresolved:
        notes.append(f"Unknown event values for {event_id!r}: {', '.join(unresolved)}.")
    return _replace(
        identity,
        event_id=event_id,
        event_package_hash=overlay_content_hash(overlay),
        event_review_status=overlay.review_status,
        event_unknown_fields=tuple(overlay.unknown_fields),
        notes=tuple(dict.fromkeys(notes)),
    )


def resolve_conditions(
    identity: CircuitIdentity,
    conditions_id: str | None,
    track: Any,
    *,
    seed: int,
    paths: Paths | None = None,
) -> tuple[CircuitIdentity, Any, ConditionsTape | None]:
    """Load a conditions tape and bind it to the track frame.

    Network access is never permitted from a session request: a tape either
    exists frozen under ``artifacts/conditions/`` with a verified content hash
    or the session is refused. Fetching weather while an operator waits would
    make the session's identity depend on when it was created.
    """
    if conditions_id is None:
        return identity, None, None

    try:
        tape = load_conditions(conditions_id, paths, allow_network=False)
    except ConditionsUnavailable as exc:
        raise CircuitRefusal(
            ErrorCode.CAPABILITY_UNAVAILABLE,
            f"conditions {conditions_id!r} cannot be resolved offline: {exc}",
            conditions_id=conditions_id,
        ) from exc
    except FileNotFoundError as exc:
        raise CircuitRefusal(
            ErrorCode.NOT_FOUND,
            f"conditions {conditions_id!r} does not exist in configs/conditions",
            conditions_id=conditions_id,
            available_conditions=", ".join(_known_conditions_ids(paths)),
        ) from exc
    except ValueError as exc:
        raise CircuitRefusal(
            ErrorCode.VALIDATION_FAILED,
            f"conditions {conditions_id!r} is malformed or failed hash verification: {exc}",
            conditions_id=conditions_id,
        ) from exc

    environment = environment_for(tape, track, seed=seed)
    notes = list(identity.notes)
    notes.append(
        f"Conditions tape {conditions_id!r} ({tape.provenance.source_kind}): {environment.describes}"
    )
    if tape.provenance.permission:
        notes.append(f"Conditions permission: {tape.provenance.permission}")
    updated = _replace(
        identity,
        conditions_id=conditions_id,
        conditions_hash=tape.content_hash,
        conditions_source_kind=tape.provenance.source_kind,
        notes=tuple(dict.fromkeys(notes)),
    )
    return updated, environment, tape


def _replace(identity: CircuitIdentity, **changes: Any) -> CircuitIdentity:
    from dataclasses import replace

    return replace(identity, **changes)


__all__ = [
    "MINIMUM_READINESS",
    "REAL_CIRCUIT_LABEL",
    "SYNTHETIC_SKETCH_GEOMETRY_NOTE",
    "UNKNOWN_CORRIDOR_NOTE",
    "CircuitIdentity",
    "CircuitRefusal",
    "describe_track",
    "has_synthetic_sketch",
    "overlay_content_hash",
    "resolve_conditions",
    "resolve_event",
    "resolve_track_package",
]
