"""Rule-pack loading, composition and validation.

Three levels compose (``rules/TECHNICAL_SPEC.md``, "Rule packs"):

1. a **season revision** — the baseline articles for the season;
2. an **event/session pack** — circuit-specific curves, allowances and line
   locations that override the season baseline by key;
3. a **timestamped race-control state** — flags and invalidations that apply
   from a session time onwards.

Levels 1 and 2 compose into the immutable :class:`RuleManifest` that the
simulator, planner and independent checker all load; level 3 is an event
stream, so it does not move the ruleset hash.

Every implemented statement carries its article, source id, URL, published and
effective date, a human-readable machine representation and a reviewer field.
Where a referenced document could not be resolved the pack records an entry in
``unknown_conditions`` and the affected coverage row is ``review_required`` or
``unsupported`` — never a silently invented default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from afterlap_contracts import (
    SCHEMA_VERSION,
    CoverageEntry,
    CoverageStatus,
    DeploymentProfile,
    DetectionLine,
    FlagState,
    PowerCurve,
    PowerCurvePoint,
    RuleManifest,
    RuleReference,
)

from ..config import config_dir, load_yaml
from .state import RaceEvent, RaceEventKind

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from ..paths import Paths

__all__ = [
    "CoverageSpec",
    "CurveSpec",
    "DetectionLineSpec",
    "PackValidationError",
    "RaceControlSpec",
    "RulePack",
    "RulePackDocument",
    "RuleStatement",
    "ThermalDerateSpec",
    "UnknownConditionSpec",
    "compose_manifest",
    "list_rule_packs",
    "load_rule_pack",
    "load_rule_pack_file",
    "references_for_article",
]

FORBIDDEN_CLAIM_PHRASES: tuple[str, ...] = (
    "fia certified",
    "fia-certified",
    "fia approved",
    "fia-approved",
    "certified compliant",
    "fully compliant",
    "complete coverage",
    "guaranteed compliant",
)
"""A pack may not assert certification. See ``RULE_MATRIX.md``: coverage is a
per-concern status, never a blanket badge."""

SCALAR_STATEMENT_KEYS: tuple[str, ...] = (
    "absolute_power_ceiling_w",
    "battery_energy_min_j",
    "battery_energy_max_j",
    "recharge_allowance_per_lap_j",
    "max_power_ramp_w_per_s",
    "overtake_profile_extra_power_w",
    "recharge_measurement_bus",
)

REQUIRED_STATEMENT_KEYS: tuple[str, ...] = (
    "absolute_power_ceiling_w",
    "battery_energy_min_j",
    "battery_energy_max_j",
)


class PackValidationError(ValueError):
    """A rule pack is structurally loadable but not fit to be used."""


class _Spec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class RuleStatement(_Spec):
    """One machine-implemented regulatory statement with its full provenance."""

    representation: str = Field(min_length=1, description="How the statement is machine-encoded.")
    article: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    value: float | None = None
    text_value: str | None = None
    unit: str | None = None
    measurement_bus: str | None = Field(
        default=None, description="Where the quantity is measured, e.g. 'ers_k_dc' or 'cu_k_dc'."
    )
    source_url: str | None = None
    published_date: str | None = None
    effective_date: str | None = None
    reviewer: str | None = Field(default=None, description="Null until a human has reviewed this row.")
    note: str | None = None

    def reference(self) -> RuleReference:
        return RuleReference(
            article=self.article,
            source_id=self.source_id,
            source_url=self.source_url,
            published_date=self.published_date,
            effective_date=self.effective_date,
            reviewer=self.reviewer,
            note=self.note or self.representation,
        )


class _CurvePointSpec(_Spec):
    speed_mps: float = Field(ge=0.0)
    max_power_w: float = Field(ge=0.0)


class CurveSpec(_Spec):
    """A speed-dependent ceiling plus the statement that authorises it."""

    curve_id: str = Field(min_length=1)
    measurement_bus: str = Field(min_length=1)
    points: tuple[_CurvePointSpec, ...] = Field(min_length=2)
    applies_to_profiles: tuple[DeploymentProfile, ...] = ()
    sector_ids: tuple[str, ...] = ()
    statement: RuleStatement

    def to_contract(self) -> PowerCurve:
        return PowerCurve(
            curve_id=self.curve_id,
            measurement_bus=self.measurement_bus,
            points=tuple(
                PowerCurvePoint(speed_mps=p.speed_mps, max_power_w=p.max_power_w) for p in self.points
            ),
            applies_to_profiles=self.applies_to_profiles,
            sector_ids=self.sector_ids,
        )


class DetectionLineSpec(_Spec):
    line_id: str = Field(min_length=1)
    kind: str = Field(pattern="^(detection|activation|checkpoint|timing)$")
    s_m: float = Field(ge=0.0)
    statement: RuleStatement

    def to_contract(self) -> DetectionLine:
        return DetectionLine(line_id=self.line_id, kind=self.kind, s_m=self.s_m)


class ThermalDerateSpec(_Spec):
    """Temperature derating of the deployment ceiling.

    This is an engineering model, not a transcribed article: the coverage row
    for it is ``review_required`` in every pack shipped here.
    """

    onset_k: float = Field(gt=0.0)
    full_derate_k: float = Field(gt=0.0)
    min_factor: float = Field(ge=0.0, le=1.0)
    statement: RuleStatement

    @model_validator(mode="after")
    def _ordered(self) -> ThermalDerateSpec:
        if self.full_derate_k <= self.onset_k:
            raise ValueError("full_derate_k must be above onset_k")
        return self

    def factor(self, temperature_k: float | None) -> float | None:
        """Derating multiplier, or ``None`` when the temperature is unavailable.

        ``None`` propagates as an unknown condition rather than as ``1.0``.
        """
        if temperature_k is None:
            return None
        if temperature_k <= self.onset_k:
            return 1.0
        if temperature_k >= self.full_derate_k:
            return self.min_factor
        span = self.full_derate_k - self.onset_k
        frac = (temperature_k - self.onset_k) / span
        return 1.0 + frac * (self.min_factor - 1.0)


class CoverageSpec(_Spec):
    """One row of the regulatory coverage matrix, as declared by the pack."""

    concern: str = Field(min_length=1)
    status: CoverageStatus
    test_ids: tuple[str, ...] = ()
    reference_keys: tuple[str, ...] = Field(
        default=(), description="Statement keys in this pack whose provenance justifies the row."
    )
    note: str | None = None

    @model_validator(mode="after")
    def _tested_claims_need_tests(self) -> CoverageSpec:
        if self.status is CoverageStatus.IMPLEMENTED_AND_TESTED and not self.test_ids:
            raise ValueError(f"coverage row {self.concern!r} claims implemented_and_tested without test ids")
        return self


class UnknownConditionSpec(_Spec):
    """A referenced condition the pack could not resolve.

    ``critical`` conditions are applicable to the resolution and therefore
    suppress advice: the resolved context lists them and its
    ``admissible_profiles`` is empty. A non-critical (``scope: advisory``)
    condition is still recorded on the manifest — so no consumer can claim
    complete coverage — but it does not gate a quantity this pack resolves.
    Marking one non-critical is a reviewable assertion, not a way to hide it.

    Scopes: ``session`` (always applicable), ``advisory`` (recorded only),
    ``overtake_permission`` (applicable; named for auditability) and
    ``sector:<sector_id>`` (applicable only inside that sector). An
    unrecognised scope is treated as applicable, so a typo fails closed.
    """

    condition: str = Field(min_length=1)
    critical: bool = True
    scope: str = Field(default="session", min_length=1)
    note: str | None = None

    @model_validator(mode="after")
    def _advisory_is_not_critical(self) -> UnknownConditionSpec:
        if self.scope == "advisory" and self.critical:
            raise ValueError(f"unknown condition {self.condition!r} is advisory but marked critical")
        return self

    def applies_to(self, *, sector_id: str | None) -> bool:
        if not self.critical or self.scope == "advisory":
            return False
        if self.scope.startswith("sector:"):
            return self.scope.split(":", 1)[1] == sector_id
        return True


class RaceControlSpec(_Spec):
    """A timestamped race-control state — composition level 3."""

    at_session_time_s: float = Field(ge=0.0)
    label: str = Field(min_length=1)
    flags: tuple[FlagState, ...] = (FlagState.UNKNOWN,)
    invalidates_eligibility: bool = False
    unknown_conditions: tuple[str, ...] = ()
    note: str | None = None

    def to_events(self) -> tuple[RaceEvent, ...]:
        events: list[RaceEvent] = [
            RaceEvent(
                at_session_time_s=self.at_session_time_s,
                kind=RaceEventKind.FLAG,
                flags=self.flags,
                reason=self.label,
            )
        ]
        if self.invalidates_eligibility:
            events.append(
                RaceEvent(
                    at_session_time_s=self.at_session_time_s,
                    kind=RaceEventKind.INVALIDATION,
                    reason=self.label,
                )
            )
        events.extend(
            RaceEvent(
                at_session_time_s=self.at_session_time_s,
                kind=RaceEventKind.UNKNOWN_CONDITION,
                condition=condition,
                reason=self.label,
            )
            for condition in self.unknown_conditions
        )
        return tuple(events)


class LevelSpec(_Spec):
    """One composition level (season baseline or event/session override)."""

    id: str = Field(min_length=1)
    statements: dict[str, RuleStatement] = Field(default_factory=dict)
    power_curves: tuple[CurveSpec, ...] = ()
    detection_lines: tuple[DetectionLineSpec, ...] = ()
    thermal_derate: ThermalDerateSpec | None = None
    coverage: tuple[CoverageSpec, ...] = ()
    unknown_conditions: tuple[UnknownConditionSpec, ...] = ()

    @model_validator(mode="after")
    def _known_statement_keys(self) -> LevelSpec:
        unknown = sorted(set(self.statements) - set(SCALAR_STATEMENT_KEYS))
        if unknown:
            raise ValueError(f"level {self.id!r} declares unrecognised statement keys: {unknown}")
        return self


class RulePackDocument(_Spec):
    """The on-disk YAML rule pack."""

    id: str = Field(min_length=1)
    synthetic: bool
    reviewed: bool = False
    description: str | None = None
    season_revision: str = Field(min_length=1)
    season: LevelSpec
    event_pack: LevelSpec | None = None
    race_control: tuple[RaceControlSpec, ...] = ()

    @model_validator(mode="after")
    def _honest_identity(self) -> RulePackDocument:
        if self.id.startswith("synthetic") and not self.synthetic:
            raise ValueError(f"pack {self.id!r} is named synthetic but does not declare synthetic=true")
        if not self.synthetic and not self.reviewed:
            raise ValueError(f"pack {self.id!r} is not synthetic and has not been reviewed")
        haystack = " ".join(
            part.lower()
            for part in (self.description or "", *(c.note or "" for c in self.all_coverage()))
            if part
        )
        for phrase in FORBIDDEN_CLAIM_PHRASES:
            if phrase in haystack:
                raise ValueError(f"pack {self.id!r} makes a blanket compliance claim: {phrase!r}")
        times = [rc.at_session_time_s for rc in self.race_control]
        if times != sorted(times):
            raise ValueError(f"pack {self.id!r} race-control states must be in non-decreasing time order")
        return self

    def levels(self) -> tuple[LevelSpec, ...]:
        return (self.season,) if self.event_pack is None else (self.season, self.event_pack)

    def all_coverage(self) -> tuple[CoverageSpec, ...]:
        merged: dict[str, CoverageSpec] = {}
        for level in self.levels():
            for row in level.coverage:
                merged[row.concern] = row
        return tuple(merged.values())

    def merged_statements(self) -> dict[str, RuleStatement]:
        merged: dict[str, RuleStatement] = {}
        for level in self.levels():
            merged.update(level.statements)
        return merged

    def merged_unknown_conditions(self) -> tuple[UnknownConditionSpec, ...]:
        merged: dict[str, UnknownConditionSpec] = {}
        for level in self.levels():
            for spec in level.unknown_conditions:
                merged[spec.condition] = spec
        return tuple(merged[key] for key in sorted(merged))


def _merge_by_id[T](groups: Iterable[Sequence[T]], key: str) -> tuple[T, ...]:
    merged: dict[str, T] = {}
    for group in groups:
        for item in group:
            merged[getattr(item, key)] = item
    return tuple(merged.values())


def compose_manifest(document: RulePackDocument) -> RuleManifest:
    """Compose season and event levels into the immutable frozen manifest."""
    statements = document.merged_statements()
    missing = [key for key in REQUIRED_STATEMENT_KEYS if key not in statements]
    if missing:
        raise PackValidationError(f"pack {document.id!r} is missing required statements: {missing}")

    def scalar(key: str) -> float | None:
        statement = statements.get(key)
        if statement is None:
            return None
        if statement.value is None:
            raise PackValidationError(f"statement {key!r} in pack {document.id!r} has no numeric value")
        return statement.value

    curves = _merge_by_id((level.power_curves for level in document.levels()), "curve_id")
    lines = _merge_by_id((level.detection_lines for level in document.levels()), "line_id")

    bus_statement = statements.get("recharge_measurement_bus")
    recharge_bus = (bus_statement.text_value if bus_statement else None) or "cu_k_dc"

    unknown_conditions = {spec.condition for spec in document.merged_unknown_conditions()}

    references = _dedupe_references(statement.reference() for statement in statements.values())
    curve_references = _dedupe_references(curve.statement.reference() for curve in curves)
    line_references = _dedupe_references(line.statement.reference() for line in lines)
    derate = _merged_derate(document)
    derate_references = () if derate is None else (derate.statement.reference(),)
    all_references = _dedupe_references(
        (*references, *curve_references, *line_references, *derate_references)
    )

    coverage = tuple(
        CoverageEntry(
            concern=row.concern,
            status=row.status,
            references=_dedupe_references(
                statements[key].reference() for key in row.reference_keys if key in statements
            ),
            test_ids=row.test_ids,
            note=row.note,
        )
        for row in document.all_coverage()
    )

    absolute_ceiling = scalar("absolute_power_ceiling_w")
    battery_min = scalar("battery_energy_min_j")
    battery_max = scalar("battery_energy_max_j")
    assert absolute_ceiling is not None
    assert battery_min is not None
    assert battery_max is not None

    return RuleManifest(
        schema_version=SCHEMA_VERSION,
        ruleset_id=document.id,
        season_revision=document.season_revision,
        event_pack_id=None if document.event_pack is None else document.event_pack.id,
        synthetic=document.synthetic,
        reviewed=document.reviewed,
        references=all_references,
        coverage=coverage,
        absolute_power_ceiling_w=absolute_ceiling,
        power_curves=tuple(curve.to_contract() for curve in curves),
        battery_energy_min_j=battery_min,
        battery_energy_max_j=battery_max,
        recharge_allowance_per_lap_j=scalar("recharge_allowance_per_lap_j"),
        recharge_measurement_bus=recharge_bus,
        max_power_ramp_w_per_s=scalar("max_power_ramp_w_per_s"),
        overtake_profile_extra_power_w=scalar("overtake_profile_extra_power_w"),
        detection_lines=tuple(line.to_contract() for line in lines),
        unknown_conditions=tuple(sorted(unknown_conditions)),
    )


def _dedupe_references(references: Iterable[RuleReference]) -> tuple[RuleReference, ...]:
    merged: dict[tuple[str, str], RuleReference] = {}
    for reference in references:
        merged.setdefault((reference.source_id, reference.article), reference)
    return tuple(merged[key] for key in sorted(merged))


def _merged_derate(document: RulePackDocument) -> ThermalDerateSpec | None:
    derate: ThermalDerateSpec | None = None
    for level in document.levels():
        if level.thermal_derate is not None:
            derate = level.thermal_derate
    return derate


@dataclass(frozen=True, slots=True)
class RulePack:
    """A loaded pack: the frozen manifest plus the level-3 race-control stream.

    ``ruleset_hash`` covers levels 1 and 2 only. Race control is an event
    stream applied on top; a flag does not silently rewrite the ruleset a plan
    was checked against.
    """

    document: RulePackDocument
    manifest: RuleManifest
    thermal_derate: ThermalDerateSpec | None = None
    unknown_conditions: tuple[UnknownConditionSpec, ...] = ()
    source_path: Path | None = None

    @property
    def ruleset_hash(self) -> str:
        return self.manifest.content_hash()

    @property
    def critical_unknown_conditions(self) -> tuple[UnknownConditionSpec, ...]:
        return tuple(spec for spec in self.unknown_conditions if spec.critical)

    @property
    def advisory_unknown_conditions(self) -> tuple[UnknownConditionSpec, ...]:
        return tuple(spec for spec in self.unknown_conditions if not spec.critical)

    @property
    def race_control(self) -> tuple[RaceControlSpec, ...]:
        return self.document.race_control

    def race_control_at(self, session_time_s: float) -> RaceControlSpec | None:
        """The most recent race-control state at or before ``session_time_s``."""
        applicable = [rc for rc in self.race_control if rc.at_session_time_s <= session_time_s]
        return applicable[-1] if applicable else None

    def race_events_until(self, session_time_s: float) -> tuple[RaceEvent, ...]:
        """Every race-control event in force at or before ``session_time_s``."""
        events: list[RaceEvent] = []
        for state in self.race_control:
            if state.at_session_time_s <= session_time_s:
                events.extend(state.to_events())
        return tuple(events)

    def line(self, line_id: str) -> DetectionLine | None:
        for line in self.manifest.detection_lines:
            if line.line_id == line_id:
                return line
        return None

    def lines_of_kind(self, kind: str) -> tuple[DetectionLine, ...]:
        return tuple(line for line in self.manifest.detection_lines if line.kind == kind)

    def coverage_status(self, concern: str) -> CoverageStatus | None:
        for entry in self.manifest.coverage:
            if entry.concern == concern:
                return entry.status
        return None


def _build_pack(payload: Mapping[str, Any], source_path: Path | None) -> RulePack:
    document = RulePackDocument.model_validate(payload)
    manifest = compose_manifest(document)
    return RulePack(
        document=document,
        manifest=manifest,
        thermal_derate=_merged_derate(document),
        unknown_conditions=document.merged_unknown_conditions(),
        source_path=source_path,
    )


def load_rule_pack_file(path: Path) -> RulePack:
    """Load and validate one rule pack from an explicit YAML path."""
    return _build_pack(load_yaml(path), path)


def load_rule_pack(pack_id: str, paths: Paths | None = None) -> RulePack:
    """Load ``configs/rules/<pack_id>.yaml``."""
    return load_rule_pack_file(config_dir("rules", paths) / f"{pack_id}.yaml")


def list_rule_packs(paths: Paths | None = None) -> tuple[str, ...]:
    return tuple(sorted(p.stem for p in config_dir("rules", paths).glob("*.yaml")))


def references_for_article(
    manifest: RuleManifest | None, articles: Sequence[str]
) -> tuple[RuleReference, ...]:
    """Manifest references whose article matches one of ``articles``."""
    if manifest is None:
        return ()
    wanted = set(articles)
    return tuple(ref for ref in manifest.references if ref.article in wanted)
