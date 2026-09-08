"""Real circuits and race conditions (A16).

Coordinator-owned package surface. Workers add modules here and propose export
changes through ``handoffs/``; the frozen types live in :mod:`package`.
"""

from __future__ import annotations

from .package import (
    CANONICAL_SPACING_M,
    READINESS_ORDER,
    SCHEMA_VERSION,
    CompiledCentreline,
    CorridorQuality,
    Direction,
    EventOverlay,
    GeometryDescriptor,
    GeometryProvenance,
    NamedRange,
    PowerCurveRow,
    ReadinessStatus,
    SourceRecord,
    SRange,
    TrackFeatures,
    TrackPackage,
    ValidationReport,
    readiness_rank,
)

__all__ = [
    "CANONICAL_SPACING_M",
    "READINESS_ORDER",
    "SCHEMA_VERSION",
    "CompiledCentreline",
    "CorridorQuality",
    "Direction",
    "EventOverlay",
    "GeometryDescriptor",
    "GeometryProvenance",
    "NamedRange",
    "PowerCurveRow",
    "ReadinessStatus",
    "SRange",
    "SourceRecord",
    "TrackFeatures",
    "TrackPackage",
    "ValidationReport",
    "readiness_rank",
]
