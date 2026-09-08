"""Read-only catalogue of circuits, conditions tapes and scenarios.

These routes exist so a consumer can *prove* identity rather than trust a
label. Every entry carries the hash of the artefact it describes, so the same
`track_package_hash` can be checked against a session manifest, the persisted
session row and the stream event that announced the session.

Four rules the payloads follow, all of them AGENTS.md invariants:

* **A missing artefact appears, it is not omitted.** A registry circuit with no
  compiled package is listed with its registry readiness and null hashes. An
  openf1 conditions tape whose frozen file is absent is listed as unavailable
  with the reason. Hiding it would look identical to "we have it".
* **Unknown is null with provenance, never zero.** An unretrieved official
  length is ``null`` with ``official_length_verified: false``, never ``0``.
* **No raw arrays outside the centreline route.** The summary and detail
  payloads carry counts, hashes and quality labels; the dense geometry has its
  own route with an explicit stride.
* **No real-track claim below the ladder.** Readiness comes from the package's
  validation report, which the independent validator derives from evidence;
  ``simulation_ready`` means only that the package is at or above
  ``geometry_validated`` and may drive the simulator as a
  ``real_circuit_synthetic_energy`` run.

The route paths sit under the single ``/api/v1`` prefix the rest of the control
plane uses; a second prefix would be a second API surface.
"""

from __future__ import annotations

import math
from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from afterlap_contracts import SCHEMA_VERSION, ErrorCode
from afterlap_core.conditions import ConditionsUnavailable, load_conditions
from afterlap_core.conditions.loader import load_conditions_config, tape_cache_path
from afterlap_core.config import list_configs
from afterlap_core.paths import Paths
from afterlap_core.simulation.config import load_scenario
from afterlap_core.tracks.loader import (
    TrackPackageError,
    centreline_path,
    list_track_packages,
    load_centreline,
    load_event_overlay,
    load_track_package,
    package_dir,
)
from afterlap_core.tracks.package import TrackPackage, readiness_rank

from ..db import LifecycleError
from ..session.circuit import (
    MINIMUM_READINESS,
    REAL_CIRCUIT_LABEL,
    has_synthetic_sketch,
    overlay_content_hash,
)

router = APIRouter()

CATALOGUE_NOTICE = (
    "Compiled circuit geometry only. Car, battery and driver parameters are synthetic documents, so "
    f"a session on any circuit here is labelled {REAL_CIRCUIT_LABEL}."
)

MAX_CENTRELINE_POINTS = 20000
"""A stride that would return more than this is refused rather than silently coarsened."""


def catalogue_paths(request: Request) -> Paths:
    """The artefact tree the catalogue reads.

    Deliberately the *session factory's* tree: if these two ever disagree, a
    hash an operator reads here is not the hash a session used, which is the
    exact disconnection this module exists to make impossible.
    """
    explicit = getattr(request.app.state, "track_paths", None)
    if explicit is not None:
        return explicit  # type: ignore[no-any-return]
    factory = getattr(request.app.state, "session_factory", None)
    from_factory = getattr(factory, "paths", None) if factory is not None else None
    return from_factory or Paths.default()


class _Payload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceSummary(_Payload):
    """One hashed raw input of a package, with its permission text verbatim."""

    source_id: str
    title: str
    url: str
    retrieved_at: str
    sha256: str | None = None
    permission: str
    priority: int | None = None
    document_revision: str | None = None


class EventOverlaySummary(_Payload):
    """An event overlay and how far through the two-reviewer queue it is."""

    event_id: str
    review_status: str
    reviewer_count: int
    confirmed: bool
    overlay_hash: str
    ruleset_hash: str
    detection_line_count: int
    activation_line_count: int
    standard_curve_points: int
    overtake_curve_points: int
    unknown_fields: tuple[str, ...] = ()
    fia_document_hashes: tuple[str, ...] = ()
    effective_values_resolved: tuple[str, ...] = ()
    effective_values_unknown: tuple[str, ...] = ()


class TrackSummary(_Payload):
    """Registry identity joined with whatever the compiled package proves."""

    track_id: str
    display_name: str
    country: str | None = None
    registry_readiness: str | None = None
    official_length_m: float | None = None
    official_length_verified: bool = False
    official_length_source_url: str | None = None
    official_length_sha256: str | None = None
    event_ids: tuple[str, ...] = ()

    package_present: bool = False
    package_hash: str | None = None
    readiness: str | None = None
    geometry_provenance: str | None = None
    corridor_quality: str | None = None
    lateral_geometry_surveyed: bool | None = None
    nominal_length_m: float | None = None
    point_count: int | None = None
    sample_spacing_m: float | None = None
    arrays_sha256: str | None = None
    source_count: int | None = None
    licence_labels: tuple[str, ...] = ()
    closure_error_m: float | None = None
    length_error_fraction: float | None = None
    simulation_ready: bool = False
    event_overlay_ids: tuple[str, ...] = ()
    unavailable_reason: str | None = None
    notes: tuple[str, ...] = ()


class TrackListResponse(_Payload):
    schema_version: str = SCHEMA_VERSION
    season: int | None = None
    snapshot_date: str | None = None
    minimum_readiness_to_drive: str = MINIMUM_READINESS.value
    notice: str = CATALOGUE_NOTICE
    tracks: tuple[TrackSummary, ...] = ()


class ValidationSummary(_Payload):
    status: str
    closure_error_m: float | None = None
    length_error_fraction: float | None = None
    official_length_m: float | None = None
    report_path: str | None = None
    checks: dict[str, str] = Field(default_factory=dict)
    notes: tuple[str, ...] = ()


class FeatureSummary(_Payload):
    start_finish_s_m: float
    sector_count: int
    corner_count: int
    corner_ids: tuple[str, ...] = ()
    pit_lane_excluded: bool = True


class TrackDetailResponse(_Payload):
    schema_version: str = SCHEMA_VERSION
    notice: str = CATALOGUE_NOTICE
    track: TrackSummary
    validation: ValidationSummary | None = None
    features: FeatureSummary | None = None
    sources: tuple[SourceSummary, ...] = ()
    event_overlays: tuple[EventOverlaySummary, ...] = ()


class CentrelineResponse(_Payload):
    """Downsampled geometry, with the hashes that pin the arrays it came from."""

    schema_version: str = SCHEMA_VERSION
    track_id: str
    package_hash: str
    arrays_sha256: str | None = None
    readiness: str
    geometry_provenance: str
    corridor_quality: str
    length_m: float
    source_point_count: int
    sample_spacing_m: float
    stride_m: float
    index_stride: int
    point_count: int
    units: dict[str, str] = Field(default_factory=dict)
    s_m: tuple[float, ...] = ()
    x_m: tuple[float, ...] = ()
    y_m: tuple[float, ...] = ()
    curvature_1pm: tuple[float, ...] = ()
    notice: str = CATALOGUE_NOTICE


class ConditionsSummary(_Payload):
    conditions_id: str
    description: str | None = None
    source: str
    available: bool
    content_hash: str | None = None
    sample_count: int | None = None
    duration_s: float | None = None
    rainfall_minutes: float | None = None
    session_key: int | None = None
    altitude_m: float | None = None
    altitude_source: str | None = None
    permission: str | None = None
    retrieved_at: str | None = None
    time_origin_utc: str | None = None
    gust_enabled: bool = False
    frozen_tape_path: str | None = None
    unavailable_reason: str | None = None


class ConditionsListResponse(_Payload):
    schema_version: str = SCHEMA_VERSION
    conditions: tuple[ConditionsSummary, ...] = ()
    notice: str = (
        "A conditions tape is a station reading or declared synthetic constants, never a certified "
        "condition. Tapes are resolved offline: nothing here triggers a network fetch."
    )


class ScenarioSummary(_Payload):
    """One scenario document and the circuit it actually resolves to.

    Every field but ``scenario_id`` is nullable: a document that fails to parse
    is still listed, with ``unavailable_reason`` and nulls, because omitting it
    would look identical to it not existing. A null is "not known from this
    document", never a zero standing in for one.
    """

    scenario_id: str
    description: str | None = None
    track_id: str | None = None
    conditions_id: str | None = None
    event_id: str | None = None
    synthetic: bool | None = None
    status_note: str | None = None
    rule_pack: str | None = None
    ego_car_id: str | None = None
    car_ids: tuple[str, ...] = ()
    duration_s: float | None = None
    seed: int | None = None
    real_circuit: bool = False
    track_readiness: str | None = None
    track_package_hash: str | None = None
    run_label: str | None = None
    unavailable_reason: str | None = None


class ScenarioListResponse(_Payload):
    schema_version: str = SCHEMA_VERSION
    scenarios: tuple[ScenarioSummary, ...] = ()
    notice: str = (
        "Every scenario is synthetic in its car, battery and driver parameters. A scenario whose track "
        f"resolves to a compiled package runs as {REAL_CIRCUIT_LABEL}."
    )


def _licence_labels(package: TrackPackage) -> tuple[str, ...]:
    return tuple(dict.fromkeys(source.permission for source in package.sources))


def _load_package_or_reason(track_id: str, paths: Paths) -> tuple[TrackPackage | None, str | None]:
    """Load a package, returning the refusal reason instead of raising."""
    if not (package_dir(track_id, paths) / "package.json").exists():
        return None, None
    try:
        return load_track_package(track_id, paths), None
    except TrackPackageError as exc:
        return None, str(exc)
    except ValueError as exc:
        return None, f"package document is invalid: {exc}"


def _overlay_ids(track_id: str, paths: Paths) -> tuple[str, ...]:
    root = package_dir(track_id, paths) / "events"
    if not root.is_dir():
        return ()
    return tuple(sorted(p.stem for p in root.glob("*.json") if p.name.count(".") == 1))


def _summary(
    track_id: str,
    paths: Paths,
    *,
    registry_entry: Any | None,
) -> TrackSummary:
    package, reason = _load_package_or_reason(track_id, paths)
    length = getattr(registry_entry, "official_length_m", None)
    base: dict[str, Any] = {
        "track_id": track_id,
        "display_name": (
            getattr(registry_entry, "display_name", None)
            or (package.display_name if package is not None else track_id)
        ),
        "country": getattr(registry_entry, "country", None),
        "registry_readiness": (registry_entry.readiness.value if registry_entry is not None else None),
        "official_length_m": getattr(length, "value", None),
        "official_length_verified": bool(getattr(length, "verified", False)),
        "official_length_source_url": getattr(length, "source_url", None),
        "official_length_sha256": getattr(length, "sha256", None),
        "event_ids": tuple(getattr(registry_entry, "event_ids", ()) or ()),
        "event_overlay_ids": _overlay_ids(track_id, paths),
        "unavailable_reason": reason,
    }
    if package is None:
        notes: list[str] = []
        if reason is None:
            notes.append(
                "No compiled package under artifacts/tracks: registry identity only. Hashes are null "
                "because nothing has been compiled, not because they are unknown."
            )
        if has_synthetic_sketch(track_id, paths):
            notes.append("A synthetic sketch exists at configs/tracks/<id>.yaml; it is not a real circuit.")
        return TrackSummary(**base, notes=tuple(notes))

    validation = package.validation
    return TrackSummary(
        **base,
        package_present=True,
        package_hash=package.package_hash,
        readiness=validation.status.value,
        geometry_provenance=package.geometry.provenance.value,
        corridor_quality=package.geometry.corridor_quality.value,
        lateral_geometry_surveyed=package.lateral_geometry_known,
        nominal_length_m=package.nominal_length_m,
        point_count=package.geometry.point_count,
        sample_spacing_m=package.geometry.sample_spacing_m,
        arrays_sha256=package.geometry.arrays_sha256,
        source_count=len(package.sources),
        licence_labels=_licence_labels(package),
        closure_error_m=validation.closure_error_m,
        length_error_fraction=validation.length_error_fraction,
        simulation_ready=readiness_rank(validation.status) >= readiness_rank(MINIMUM_READINESS),
        notes=validation.notes,
    )


def _overlay_summary(track_id: str, event_id: str, paths: Paths) -> EventOverlaySummary | None:
    from afterlap_core.tracks.fia_overlay import overlay_effective_values

    try:
        overlay = load_event_overlay(track_id, event_id, paths)
    except (TrackPackageError, ValueError):
        return None
    effective = overlay_effective_values(overlay)
    numeric = {k: v for k, v in effective.items() if k not in {"event_id", "review_status", "confirmed"}}
    return EventOverlaySummary(
        event_id=overlay.event_id,
        review_status=overlay.review_status,
        reviewer_count=len(set(overlay.reviewers)),
        confirmed=overlay.is_confirmed,
        overlay_hash=overlay_content_hash(overlay),
        ruleset_hash=overlay.ruleset_hash,
        detection_line_count=len(overlay.detection_lines_m),
        activation_line_count=len(overlay.activation_lines_m),
        standard_curve_points=len(overlay.standard_curve),
        overtake_curve_points=len(overlay.overtake_curve),
        unknown_fields=overlay.unknown_fields,
        fia_document_hashes=tuple(d.sha256 for d in overlay.fia_documents if d.sha256 is not None),
        effective_values_resolved=tuple(sorted(k for k, v in numeric.items() if v is not None)),
        effective_values_unknown=tuple(sorted(k for k, v in numeric.items() if v is None)),
    )


def _registry_or_none(paths: Paths) -> Any | None:
    from afterlap_core.tracks.registry import load_registry

    try:
        return load_registry(paths)
    except (FileNotFoundError, ValueError):
        return None


def _registry_track_ids(registry: Any | None) -> tuple[str, ...]:
    return tuple(getattr(registry, "track_ids", ()) or ())


@router.get("/tracks", response_model=TrackListResponse)
async def list_tracks(request: Request) -> TrackListResponse:
    """The season registry joined with the compiled packages actually on disk."""
    paths = catalogue_paths(request)
    registry = _registry_or_none(paths)
    entries = {entry.track_id: entry for entry in (registry.entries if registry is not None else ())}
    track_ids = sorted(set(entries) | set(list_track_packages(paths)))
    return TrackListResponse(
        season=getattr(registry, "season", None),
        snapshot_date=getattr(registry, "snapshot_date", None),
        tracks=tuple(_summary(tid, paths, registry_entry=entries.get(tid)) for tid in track_ids),
    )


@router.get("/tracks/{track_id}", response_model=TrackDetailResponse)
async def get_track(request: Request, track_id: str) -> TrackDetailResponse:
    """Package summary, validation report and event overlays. No raw arrays."""
    paths = catalogue_paths(request)
    registry = _registry_or_none(paths)
    entry = None
    if registry is not None:
        try:
            entry = registry.get(track_id)
        except KeyError:
            entry = None
    package, _reason = _load_package_or_reason(track_id, paths)
    if entry is None and package is None:
        raise LifecycleError(
            ErrorCode.NOT_FOUND,
            f"track {track_id!r} is neither in the circuit registry nor compiled under artifacts/tracks",
            track_id=track_id,
            available_tracks=", ".join(
                sorted(set(list_track_packages(paths)) | set(_registry_track_ids(registry)))
            ),
        )

    summary = _summary(track_id, paths, registry_entry=entry)
    overlays = tuple(
        s for s in (_overlay_summary(track_id, eid, paths) for eid in summary.event_overlay_ids) if s
    )
    if package is None:
        return TrackDetailResponse(track=summary, event_overlays=overlays)

    return TrackDetailResponse(
        track=summary,
        validation=ValidationSummary(
            status=package.validation.status.value,
            closure_error_m=package.validation.closure_error_m,
            length_error_fraction=package.validation.length_error_fraction,
            official_length_m=package.validation.official_length_m,
            report_path=package.validation.report_path,
            checks=dict(package.validation.checks),
            notes=package.validation.notes,
        ),
        features=FeatureSummary(
            start_finish_s_m=package.features.start_finish_s_m,
            sector_count=len(package.features.sectors),
            corner_count=len(package.features.corners),
            corner_ids=tuple(c.id for c in package.features.corners),
            pit_lane_excluded=package.features.pit_lane_excluded,
        ),
        sources=tuple(
            SourceSummary(
                source_id=s.source_id,
                title=s.title,
                url=s.url,
                retrieved_at=s.retrieved_at,
                sha256=s.sha256,
                permission=s.permission,
                priority=s.priority,
                document_revision=s.document_revision,
            )
            for s in package.sources
        ),
        event_overlays=overlays,
    )


@router.get("/tracks/{track_id}/centreline", response_model=CentrelineResponse)
async def get_centreline(
    request: Request,
    track_id: str,
    stride_m: Annotated[float, Query(ge=1.0, le=2000.0)] = 25.0,
) -> CentrelineResponse:
    """Downsampled ``s/x/y/curvature`` from the compiled arrays, plus the hashes.

    The stride is honoured in index space at the package's own sample spacing,
    so ``stride_m=25`` on 1 m arrays returns every 25th sample. The response
    repeats ``package_hash`` and ``arrays_sha256`` so a consumer can prove the
    coordinates came from the geometry a session actually ran.
    """
    paths = catalogue_paths(request)
    package, reason = _load_package_or_reason(track_id, paths)
    if package is None:
        raise LifecycleError(
            ErrorCode.NOT_FOUND,
            reason or f"track {track_id!r} has no compiled package under artifacts/tracks",
            track_id=track_id,
        )
    if not centreline_path(track_id, paths).exists():
        raise LifecycleError(
            ErrorCode.NOT_FOUND,
            f"track {track_id!r} has a package document but no compiled centreline arrays",
            track_id=track_id,
        )
    try:
        centreline = load_centreline(track_id, package, paths)
    except (TrackPackageError, ValueError) as exc:
        raise LifecycleError(
            ErrorCode.VALIDATION_FAILED,
            f"centreline for {track_id!r} cannot be served: {exc}",
            track_id=track_id,
        ) from exc

    spacing = float(package.geometry.sample_spacing_m)
    index_stride = max(1, round(stride_m / spacing))
    count = math.ceil(centreline.point_count / index_stride)
    if count > MAX_CENTRELINE_POINTS:
        raise LifecycleError(
            ErrorCode.VALIDATION_FAILED,
            f"stride_m={stride_m} would return {count} points for {track_id!r}; the cap is "
            f"{MAX_CENTRELINE_POINTS}. Ask for a coarser stride rather than a silently truncated lap.",
            track_id=track_id,
            stride_m=stride_m,
        )

    def take(array: np.ndarray) -> tuple[float, ...]:
        return tuple(float(v) for v in np.asarray(array)[::index_stride])

    return CentrelineResponse(
        track_id=track_id,
        package_hash=package.package_hash or package.content_hash(),
        arrays_sha256=package.geometry.arrays_sha256,
        readiness=package.validation.status.value,
        geometry_provenance=package.geometry.provenance.value,
        corridor_quality=package.geometry.corridor_quality.value,
        length_m=centreline.length_m,
        source_point_count=centreline.point_count,
        sample_spacing_m=spacing,
        stride_m=float(index_stride) * spacing,
        index_stride=index_stride,
        point_count=count,
        units={"s_m": "m", "x_m": "m", "y_m": "m", "curvature_1pm": "1/m"},
        s_m=take(centreline.s_m),
        x_m=take(centreline.x_m),
        y_m=take(centreline.y_m),
        curvature_1pm=take(centreline.curvature_1pm),
    )


@router.get("/conditions", response_model=ConditionsListResponse)
async def list_conditions_tapes(request: Request) -> ConditionsListResponse:
    """Every conditions document, resolved offline. An absent tape says so."""
    paths = catalogue_paths(request)
    out: list[ConditionsSummary] = []
    for conditions_id in list_configs("conditions", paths):
        try:
            config = load_conditions_config(conditions_id, paths)
        except (FileNotFoundError, ValueError) as exc:
            out.append(
                ConditionsSummary(
                    conditions_id=conditions_id,
                    source="unknown",
                    available=False,
                    unavailable_reason=f"conditions document is invalid: {exc}",
                )
            )
            continue
        cache = tape_cache_path(conditions_id, paths)
        try:
            tape = load_conditions(conditions_id, paths, allow_network=False)
        except (ConditionsUnavailable, FileNotFoundError, ValueError) as exc:
            out.append(
                ConditionsSummary(
                    conditions_id=conditions_id,
                    description=config.description,
                    source=config.source,
                    available=False,
                    session_key=config.session_key,
                    altitude_m=config.altitude_m,
                    altitude_source=config.altitude_source,
                    gust_enabled=config.gust.enabled,
                    frozen_tape_path=str(cache) if cache.exists() else None,
                    unavailable_reason=str(exc),
                )
            )
            continue
        summary = tape.summary()
        out.append(
            ConditionsSummary(
                conditions_id=conditions_id,
                description=config.description,
                source=tape.provenance.source_kind,
                available=True,
                content_hash=tape.content_hash,
                sample_count=int(summary["samples"]),
                duration_s=float(summary["duration_s"]),
                rainfall_minutes=summary["rainfall_minutes"],
                session_key=tape.provenance.session_key,
                altitude_m=tape.altitude_m,
                altitude_source=tape.altitude_source,
                permission=tape.provenance.permission,
                retrieved_at=tape.provenance.retrieved_at,
                time_origin_utc=tape.provenance.time_origin_utc,
                gust_enabled=tape.gust.enabled,
                frozen_tape_path=str(cache) if cache.exists() else None,
            )
        )
    return ConditionsListResponse(conditions=tuple(out))


@router.get("/scenarios", response_model=ScenarioListResponse)
async def list_scenario_documents(request: Request) -> ScenarioListResponse:
    """Every scenario with the circuit and conditions it actually resolves to.

    The web app hardcoded this list; a hardcoded list cannot tell an operator
    that a scenario's circuit is not compiled yet, so it would offer a session
    that is refused on creation.
    """
    paths = catalogue_paths(request)
    out: list[ScenarioSummary] = []
    for scenario_id in list_configs("scenarios", paths):
        try:
            scenario = load_scenario(scenario_id, paths)
        except (FileNotFoundError, ValueError) as exc:
            out.append(
                ScenarioSummary(
                    scenario_id=scenario_id,
                    unavailable_reason=f"scenario document is invalid: {exc}",
                )
            )
            continue

        sketch = has_synthetic_sketch(scenario.track_id, paths)
        package, reason = (None, None) if sketch else _load_package_or_reason(scenario.track_id, paths)
        unavailable = reason
        if not sketch and package is None and reason is None:
            unavailable = (
                f"circuit {scenario.track_id!r} has no compiled package under artifacts/tracks; "
                "a session on this scenario is refused until one is compiled and validated"
            )
        elif package is not None and readiness_rank(package.validation.status) < readiness_rank(
            MINIMUM_READINESS
        ):
            unavailable = (
                f"circuit {scenario.track_id!r} is {package.validation.status.value}; "
                f"{MINIMUM_READINESS.value} is required before it can drive the simulator"
            )
        out.append(
            ScenarioSummary(
                scenario_id=scenario.id,
                description=scenario.description,
                track_id=scenario.track_id,
                conditions_id=scenario.conditions_id,
                event_id=scenario.event_id,
                synthetic=scenario.synthetic,
                status_note=scenario.status_note,
                rule_pack=scenario.rule_pack,
                ego_car_id=scenario.ego_car_id,
                car_ids=tuple(sorted(scenario.cars)),
                duration_s=float(scenario.duration_s.value),
                seed=scenario.seed,
                real_circuit=package is not None,
                track_readiness=None if package is None else package.validation.status.value,
                track_package_hash=None if package is None else package.package_hash,
                run_label=REAL_CIRCUIT_LABEL if package is not None else None,
                unavailable_reason=unavailable,
            )
        )
    return ScenarioListResponse(scenarios=tuple(out))


__all__ = [
    "CATALOGUE_NOTICE",
    "CentrelineResponse",
    "ConditionsListResponse",
    "ScenarioListResponse",
    "TrackDetailResponse",
    "TrackListResponse",
    "catalogue_paths",
    "router",
]
