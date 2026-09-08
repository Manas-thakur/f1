"""Read-only catalogue payloads: circuits, conditions tapes and scenarios.

These were route-local Pydantic models in ``afterlap_api.routes.catalog``, so
the generated JSON Schema and TypeScript did not describe them and the web
client carried a hand-written copy of their shape. A hand-written copy of a
wire contract drifts silently; that is the drift test's whole subject.

The shapes are unchanged by the move. Four rules they follow, all AGENTS.md
invariants:

* **A missing artefact appears, it is not omitted.** A registry circuit with no
  compiled package is listed with null hashes and its refusal reason. Hiding it
  would look identical to having it.
* **Unknown is null with provenance, never zero.** An unretrieved official
  length is ``null`` beside ``official_length_verified: false``.
* **No raw arrays outside the centreline payload.** Summaries carry counts,
  hashes and quality labels; the dense geometry has its own payload with an
  explicit stride.
* **No local filesystem path.** Source URLs, licence text, hashes and readiness
  reasons are the evidence a consumer needs; where the deployment happens to
  keep a file is not, and describes the machine rather than the artefact.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .base import SCHEMA_VERSION

REAL_CIRCUIT_LABEL = "real_circuit_synthetic_energy"
"""D-10: genuine geometry, synthetic energy. Never a claim of measured fidelity."""

MINIMUM_READINESS_TO_DRIVE = "geometry_validated"
"""The lowest rung of the readiness ladder that may drive the simulator."""


class CataloguePayload(BaseModel):
    """Immutable, strictly-validated read-only payload.

    Not a :class:`~afterlap_contracts.base.Contract`: a catalogue summary
    carries the ``content_hash`` *of the artefact it describes* as a field,
    which would shadow ``Contract.content_hash()``. The wire configuration is
    the same, so it fails closed on an unexpected field exactly as every other
    boundary type does.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
        use_enum_values=False,
        ser_json_inf_nan="strings",
    )


READINESS_PATTERN = (
    r"^(discovered|geometry_validated|event_rules_validated|condition_calibrated|"
    r"simulation_eligible|rejected)$"
)

CATALOGUE_NOTICE = (
    "Compiled circuit geometry only. Car, battery and driver parameters are synthetic documents, so "
    f"a session on any circuit here is labelled {REAL_CIRCUIT_LABEL}."
)

CONDITIONS_NOTICE = (
    "A conditions tape is a station reading or declared synthetic constants, never a certified "
    "condition. Tapes are resolved offline: nothing here triggers a network fetch."
)

SCENARIO_NOTICE = (
    "Every scenario is synthetic in its car, battery and driver parameters. A scenario whose track "
    f"resolves to a compiled package runs as {REAL_CIRCUIT_LABEL}."
)


class SourceSummary(CataloguePayload):
    """One hashed raw input of a package, with its permission text verbatim."""

    source_id: str
    title: str
    url: str
    retrieved_at: str
    sha256: str | None = None
    permission: str
    priority: int | None = None
    document_revision: str | None = None


class EventOverlaySummary(CataloguePayload):
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


class TrackSummary(CataloguePayload):
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


class TrackListResponse(CataloguePayload):
    schema_version: str = SCHEMA_VERSION
    season: int | None = None
    snapshot_date: str | None = None
    minimum_readiness_to_drive: str = MINIMUM_READINESS_TO_DRIVE
    notice: str = CATALOGUE_NOTICE
    tracks: tuple[TrackSummary, ...] = ()


class ValidationSummary(CataloguePayload):
    """The independent validator's verdict, as recorded in the package."""

    status: str
    closure_error_m: float | None = None
    length_error_fraction: float | None = None
    official_length_m: float | None = None
    report_path: str | None = Field(
        default=None,
        description="Filename of the report inside the package directory, never an absolute path.",
    )
    checks: dict[str, str] = Field(default_factory=dict)
    notes: tuple[str, ...] = ()


class FeatureSummary(CataloguePayload):
    start_finish_s_m: float
    sector_count: int
    corner_count: int
    corner_ids: tuple[str, ...] = ()
    pit_lane_excluded: bool = True


class TrackDetailResponse(CataloguePayload):
    schema_version: str = SCHEMA_VERSION
    notice: str = CATALOGUE_NOTICE
    track: TrackSummary
    validation: ValidationSummary | None = None
    features: FeatureSummary | None = None
    sources: tuple[SourceSummary, ...] = ()
    event_overlays: tuple[EventOverlaySummary, ...] = ()


class CentrelineResponse(CataloguePayload):
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


class ConditionsSummary(CataloguePayload):
    """One conditions document and the frozen tape it does or does not have."""

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
    frozen_tape_available: bool = Field(
        default=False,
        description=(
            "Whether a frozen tape exists in the deployment's cache. Whether, not where: the "
            "cache path describes the machine and a client cannot read it."
        ),
    )
    unavailable_reason: str | None = None


class ConditionsListResponse(CataloguePayload):
    schema_version: str = SCHEMA_VERSION
    conditions: tuple[ConditionsSummary, ...] = ()
    notice: str = CONDITIONS_NOTICE


class ScenarioSummary(CataloguePayload):
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


class ScenarioListResponse(CataloguePayload):
    schema_version: str = SCHEMA_VERSION
    scenarios: tuple[ScenarioSummary, ...] = ()
    notice: str = SCENARIO_NOTICE


__all__ = [
    "CATALOGUE_NOTICE",
    "CONDITIONS_NOTICE",
    "MINIMUM_READINESS_TO_DRIVE",
    "READINESS_PATTERN",
    "REAL_CIRCUIT_LABEL",
    "SCENARIO_NOTICE",
    "CataloguePayload",
    "CentrelineResponse",
    "ConditionsListResponse",
    "ConditionsSummary",
    "EventOverlaySummary",
    "FeatureSummary",
    "ScenarioListResponse",
    "ScenarioSummary",
    "SourceSummary",
    "TrackDetailResponse",
    "TrackListResponse",
    "TrackSummary",
    "ValidationSummary",
]
