"""Generate JSON Schema and a TypeScript declaration file from the Pydantic models.

Pydantic is the single schema authority. CI regenerates and fails on drift, so a
hand-edited generated file is a build error rather than a silent divergence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import SCHEMA_VERSION
from .catalogue import (
    CentrelineResponse,
    ConditionsListResponse,
    ConditionsSummary,
    EventOverlaySummary,
    FeatureSummary,
    ScenarioListResponse,
    ScenarioSummary,
    SourceSummary,
    TrackDetailResponse,
    TrackListResponse,
    TrackSummary,
    ValidationSummary,
)
from .errors import ApiError, ApiErrorResponse
from .estimate import StateEstimate
from .events import StreamEnvelope
from .lifecycle import (
    ControlLease,
    ExecutionEvent,
    LifecycleTransition,
    OperatorEvent,
    OutcomeRecord,
    SessionCommand,
)
from .models import (
    BenchmarkReport,
    ExperimentJob,
    ExperimentManifest,
    FeatureManifest,
    ModelManifest,
)
from .planning import (
    CandidatePlan,
    LearnedContribution,
    OutcomeRange,
    PlanningResult,
    Recommendation,
    RecommendationAlternative,
)
from .requests import (
    AcquireLeaseRequest,
    AcquireLeaseResponse,
    CancelExperimentRequest,
    CreateExperimentRequest,
    CreateExperimentResponse,
    CreateExportRequest,
    CreateSessionRequest,
    CreateSessionResponse,
    CreateSnapshotRequest,
    CreateSnapshotResponse,
    DecisionEvidenceResponse,
    DriverActionRequest,
    DriverActionResponse,
    ExperimentStatusResponse,
    ExportJobResponse,
    HealthResponse,
    ModelListResponse,
    RecommendationActionRequest,
    RecommendationActionResponse,
    RulesetResponse,
    SessionCommandRequest,
    SessionCommandResponse,
    SessionListResponse,
)
from .rules import ConstraintResult, RuleContext, RuleManifest
from .session import SessionManifest, SessionSnapshot, SessionSummary, SnapshotReference
from .telemetry import QualityEvent, SourceCapability, TelemetryChunkManifest, TelemetryEvent

if TYPE_CHECKING:
    from pydantic import BaseModel

EXPORTED_MODELS: tuple[type[BaseModel], ...] = (
    SourceCapability,
    TelemetryEvent,
    TelemetryChunkManifest,
    QualityEvent,
    SessionManifest,
    SessionSummary,
    SessionSnapshot,
    SnapshotReference,
    StateEstimate,
    RuleManifest,
    RuleContext,
    ConstraintResult,
    CandidatePlan,
    OutcomeRange,
    LearnedContribution,
    PlanningResult,
    Recommendation,
    RecommendationAlternative,
    ControlLease,
    OperatorEvent,
    SessionCommand,
    ExecutionEvent,
    LifecycleTransition,
    OutcomeRecord,
    FeatureManifest,
    ModelManifest,
    ExperimentManifest,
    ExperimentJob,
    BenchmarkReport,
    StreamEnvelope,
    ApiError,
    ApiErrorResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    SessionListResponse,
    AcquireLeaseRequest,
    AcquireLeaseResponse,
    SessionCommandRequest,
    SessionCommandResponse,
    RecommendationActionRequest,
    RecommendationActionResponse,
    DriverActionRequest,
    DriverActionResponse,
    CreateSnapshotRequest,
    CreateSnapshotResponse,
    CreateExperimentRequest,
    CreateExperimentResponse,
    CancelExperimentRequest,
    ExperimentStatusResponse,
    ModelListResponse,
    RulesetResponse,
    CreateExportRequest,
    ExportJobResponse,
    HealthResponse,
    DecisionEvidenceResponse,
    SourceSummary,
    EventOverlaySummary,
    TrackSummary,
    ValidationSummary,
    FeatureSummary,
    TrackListResponse,
    TrackDetailResponse,
    CentrelineResponse,
    ConditionsSummary,
    ConditionsListResponse,
    ScenarioSummary,
    ScenarioListResponse,
)


def build_json_schemas() -> dict[str, dict[str, Any]]:
    """One JSON Schema document per exported model, keyed by model name."""
    schemas: dict[str, dict[str, Any]] = {}
    for model in EXPORTED_MODELS:
        schema = model.model_json_schema(mode="serialization")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["title"] = model.__name__
        schemas[model.__name__] = schema
    return schemas


def build_bundle() -> dict[str, Any]:
    """A single manifest describing the whole contract revision."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AFTERLAP contract bundle",
        "schema_version": SCHEMA_VERSION,
        "models": sorted(m.__name__ for m in EXPORTED_MODELS),
        "definitions": build_json_schemas(),
    }


_TS_PRELUDE = """// Generated from afterlap_contracts. Do not edit by hand.
// Regenerate with: python -m afterlap_contracts.schema_export
/* eslint-disable */

"""


def _ts_type(schema: dict[str, Any], defs: dict[str, Any], depth: int = 0) -> str:
    """Translate one JSON Schema node into a TypeScript type expression."""
    if depth > 24:  # pragma: no cover - guards pathological recursion
        return "unknown"
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "const" in schema:
        return json.dumps(schema["const"])
    if "enum" in schema:
        return " | ".join(json.dumps(v) for v in schema["enum"])
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return " | ".join(_ts_type(s, defs, depth + 1) for s in schema[key])
    if "allOf" in schema and len(schema["allOf"]) == 1:
        return _ts_type(schema["allOf"][0], defs, depth + 1)

    kind = schema.get("type")
    if isinstance(kind, list):
        return " | ".join(_ts_type({**schema, "type": k}, defs, depth + 1) for k in kind)
    if kind == "string":
        return "string"
    if kind in ("number", "integer"):
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "null":
        return "null"
    if kind == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            return f"Array<{_ts_type(items, defs, depth + 1)}>"
        prefix = schema.get("prefixItems")
        if isinstance(prefix, list):
            inner = ", ".join(_ts_type(i, defs, depth + 1) for i in prefix)
            return f"[{inner}]"
        return "unknown[]"
    if kind == "object":
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            return f"Record<string, {_ts_type(additional, defs, depth + 1)}>"
        if additional is True or (additional is None and "properties" not in schema):
            return "Record<string, unknown>"
        return _ts_object(schema, defs, depth)
    if "properties" in schema:
        return _ts_object(schema, defs, depth)
    return "unknown"


def _ts_object(schema: dict[str, Any], defs: dict[str, Any], depth: int) -> str:
    required = set(schema.get("required", ()))
    lines = ["{"]
    for name, prop in schema.get("properties", {}).items():
        optional = "" if name in required else "?"
        lines.append(f"  {json.dumps(name)}{optional}: {_ts_type(prop, defs, depth + 1)};")
    lines.append("}")
    return "\n".join(lines)


def build_typescript() -> str:
    """Emit interfaces for every exported model plus their shared definitions."""
    bundle = build_json_schemas()
    parts: list[str] = [_TS_PRELUDE, f'export const SCHEMA_VERSION = "{SCHEMA_VERSION}" as const;\n']
    emitted: set[str] = set()

    shared: dict[str, Any] = {}
    for schema in bundle.values():
        shared.update(schema.get("$defs", {}))

    for name, definition in sorted(shared.items()):
        if name in emitted:
            continue
        emitted.add(name)
        body = _ts_type(definition, shared)
        keyword = "interface" if body.startswith("{") else "type"
        if keyword == "interface":
            parts.append(f"export interface {name} {body}\n")
        else:
            parts.append(f"export type {name} = {body};\n")

    for name, schema in bundle.items():
        if name in emitted:
            continue
        emitted.add(name)
        body = _ts_type({k: v for k, v in schema.items() if k != "$defs"}, shared)
        if body.startswith("{"):
            parts.append(f"export interface {name} {body}\n")
        else:
            parts.append(f"export type {name} = {body};\n")

    return "\n".join(parts)


def write_generated(output_dir: Path) -> list[Path]:
    """Write ``schemas.json`` and ``contracts.ts``; return the paths written."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    schema_path = output_dir / "schemas.json"
    schema_path.write_text(json.dumps(build_bundle(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written.append(schema_path)

    ts_path = output_dir / "contracts.ts"
    ts_path.write_text(build_typescript(), encoding="utf-8")
    written.append(ts_path)

    return written


def default_output_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "generated"


def check_drift(output_dir: Path | None = None) -> list[str]:
    """Return a list of files whose on-disk content differs from a fresh render."""
    target = output_dir or default_output_dir()
    problems: list[str] = []

    expected_schema = json.dumps(build_bundle(), indent=2, sort_keys=True) + "\n"
    schema_path = target / "schemas.json"
    if not schema_path.exists():
        problems.append(f"{schema_path} is missing")
    elif schema_path.read_text(encoding="utf-8") != expected_schema:
        problems.append(f"{schema_path} differs from the models")

    ts_path = target / "contracts.ts"
    expected_ts = build_typescript()
    if not ts_path.exists():
        problems.append(f"{ts_path} is missing")
    elif ts_path.read_text(encoding="utf-8") != expected_ts:
        problems.append(f"{ts_path} differs from the models")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        problems = check_drift()
        if problems:
            for problem in problems:
                print(problem)
            return 1
        print("generated contracts match the models")
        return 0
    written = write_generated(default_output_dir())
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "EXPORTED_MODELS",
    "build_bundle",
    "build_json_schemas",
    "build_typescript",
    "check_drift",
    "default_output_dir",
    "write_generated",
]
