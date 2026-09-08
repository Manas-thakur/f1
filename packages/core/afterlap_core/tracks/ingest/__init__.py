"""Raw telemetry ingestion for real circuits (A16-2).

Each adapter here fetches through :class:`~afterlap_core.tracks.provenance.RawSourceCache`
so every byte the compiler later consumes is hashed and permission-labelled on
disk first. Adapters never compile geometry; they select and persist clean laps.
"""

from __future__ import annotations

from .openf1 import (
    OPENF1_BASE_URL,
    OPENF1_PERMISSION,
    IngestResult,
    LapRecord,
    ingest_location_session,
    ingest_summary_path,
    load_ingest_summary,
    select_clean_laps,
)

__all__ = [
    "OPENF1_BASE_URL",
    "OPENF1_PERMISSION",
    "IngestResult",
    "LapRecord",
    "ingest_location_session",
    "ingest_summary_path",
    "load_ingest_summary",
    "select_clean_laps",
]
