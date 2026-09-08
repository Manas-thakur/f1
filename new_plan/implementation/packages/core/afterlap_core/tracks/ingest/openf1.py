"""OpenF1 ``/location`` ingestion: select clean laps and persist them as raw sources.

OpenF1 (https://openf1.org/) publishes car position at roughly 3.7 Hz as integer
``x, y, z`` in an undocumented local frame. This adapter does three things and
nothing more:

1. fetch the session, its lap table and per-lap ``/location`` windows through
   :class:`~afterlap_core.tracks.provenance.RawSourceCache`, so each payload is
   stored immutably under ``artifacts/tracks/raw/openf1/<sha256>/`` with URL,
   retrieval time, permission and hash;
2. reject laps that cannot represent the circuit (first lap, pit-out laps,
   laps without a duration, laps more than 2 % away from the session median);
3. write a small summary under ``artifacts/tracks/<track_id>/ingest/`` that the
   compiler reads offline.

Units are *not* decided here. The compiler infers the coordinate scale from the
official length and records the evidence; this module stores raw integers.

Licence. The brief expected CC BY 4.0. The OpenF1 site footer, verified on
2026-09-08, states "Licensed under CC BY-NC-SA 4.0" linking to
https://creativecommons.org/licenses/by-nc-sa/4.0/ and describes the data as
"intended solely for non-commercial analysis". That is what is recorded.
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ...paths import Paths
from ..package import SourceRecord
from ..provenance import CachedSource, RawSourceCache

OPENF1_BASE_URL = "https://api.openf1.org/v1"
OPENF1_LICENCE_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/"
OPENF1_PERMISSION = (
    "OpenF1 public API (https://openf1.org/); site footer states 'Licensed under CC BY-NC-SA 4.0' "
    f"linking {OPENF1_LICENCE_URL} (verified 2026-09-08); the site describes the data as unofficial and "
    "'intended solely for non-commercial analysis'. Attribution required; non-commercial; share-alike."
)
OPENF1_SOURCE = "openf1"
OPENF1_PRIORITY = 3
"""Priority-3 geometry source per TRACK_DATA_PIPELINE.md (empirical racing line only)."""

LAP_DURATION_TOLERANCE = 0.02
"""Laps more than this fraction away from the session median duration are rejected."""

LOCATION_WINDOW_MARGIN_S = 1.5
"""Seconds fetched on either side of a lap so the timing-line crossing can be interpolated."""

MIN_REQUEST_INTERVAL_S = 2.1
"""OpenF1 free tier: 3 req/s and 30 req/min (https://openf1.org/, verified 2026-09-08)."""

DEFAULT_MAX_LAPS = 12


class OpenF1IngestError(RuntimeError):
    """Ingestion could not produce clean laps; the reason is named."""


@dataclass(frozen=True, slots=True)
class LapRecord:
    """One selected clean lap and the raw location payload that covers it."""

    lap_number: int
    driver_number: int
    date_start: str
    lap_duration_s: float
    window_start: str
    window_end: str
    sector_durations_s: tuple[float | None, float | None, float | None]
    location_sha256: str
    location_url: str
    sample_count: int
    retrieved_at: str


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What one ``ingest_location_session`` call selected and persisted."""

    session_key: int
    track_id: str
    driver_number: int
    session: dict[str, Any]
    laps: tuple[LapRecord, ...]
    rejected: dict[str, int]
    median_lap_duration_s: float
    clean_laps_by_driver: dict[int, int]
    sources: tuple[SourceRecord, ...]
    summary_path: Path
    notes: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_key": self.session_key,
            "track_id": self.track_id,
            "driver_number": self.driver_number,
            "session": self.session,
            "laps": [asdict(lap) for lap in self.laps],
            "rejected": self.rejected,
            "median_lap_duration_s": self.median_lap_duration_s,
            "clean_laps_by_driver": {str(k): v for k, v in self.clean_laps_by_driver.items()},
            "sources": [s.model_dump(mode="json") for s in self.sources],
            "summary_path": str(self.summary_path),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IngestResult:
        return cls(
            session_key=int(data["session_key"]),
            track_id=str(data["track_id"]),
            driver_number=int(data["driver_number"]),
            session=dict(data["session"]),
            laps=tuple(
                LapRecord(
                    **{
                        **lap,
                        "sector_durations_s": tuple(lap["sector_durations_s"]),
                    }
                )
                for lap in data["laps"]
            ),
            rejected=dict(data["rejected"]),
            median_lap_duration_s=float(data["median_lap_duration_s"]),
            clean_laps_by_driver={int(k): int(v) for k, v in data["clean_laps_by_driver"].items()},
            sources=tuple(SourceRecord.model_validate(s) for s in data["sources"]),
            summary_path=Path(data["summary_path"]),
            notes=tuple(data.get("notes", ())),
        )


# -- pure selection logic (unit-tested without network) ----------------------- #


def select_clean_laps(
    laps: list[dict[str, Any]], *, tolerance: float = LAP_DURATION_TOLERANCE
) -> tuple[list[dict[str, Any]], dict[str, int], float]:
    """Apply the clean-lap rules to an OpenF1 ``/laps`` table.

    Returns the accepted laps (all drivers), a count of rejections by reason and
    the median duration the tolerance was measured against. The median is taken
    over every lap in ``laps`` that has a duration, is not a pit-out lap and is
    not lap 1; with a whole-session table that is the session median.
    """
    rejected: dict[str, int] = {
        "first_lap": 0,
        "pit_out_lap": 0,
        "no_lap_duration": 0,
        "duration_outside_tolerance": 0,
    }
    pool: list[dict[str, Any]] = []
    for lap in laps:
        if int(lap.get("lap_number", 0)) <= 1:
            rejected["first_lap"] += 1
            continue
        if bool(lap.get("is_pit_out_lap")):
            rejected["pit_out_lap"] += 1
            continue
        duration = lap.get("lap_duration")
        if duration is None or not isinstance(duration, int | float) or duration <= 0.0:
            rejected["no_lap_duration"] += 1
            continue
        pool.append(lap)
    if not pool:
        raise OpenF1IngestError("no lap in the table has a duration outside lap 1 and pit-out laps")
    median = float(statistics.median(float(lap["lap_duration"]) for lap in pool))
    accepted: list[dict[str, Any]] = []
    for lap in pool:
        if abs(float(lap["lap_duration"]) - median) > tolerance * median:
            rejected["duration_outside_tolerance"] += 1
            continue
        accepted.append(lap)
    return accepted, rejected, median


def choose_driver(accepted: list[dict[str, Any]]) -> tuple[int, dict[int, int]]:
    """The driver with the most clean laps; ties resolve to the lower number."""
    counts: dict[int, int] = {}
    for lap in accepted:
        driver = int(lap["driver_number"])
        counts[driver] = counts.get(driver, 0) + 1
    if not counts:
        raise OpenF1IngestError("no clean laps for any driver")
    best = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return best, counts


def pick_representative(laps: list[dict[str, Any]], median_s: float, max_laps: int) -> list[dict[str, Any]]:
    """Up to ``max_laps`` laps closest to the median duration, in lap order."""

    def rank(lap: dict[str, Any]) -> tuple[float, int]:
        return abs(float(lap["lap_duration"]) - median_s), int(lap["lap_number"])

    ranked = sorted(laps, key=rank)
    chosen = ranked[: max(0, max_laps)]
    return sorted(chosen, key=lambda lap: int(lap["lap_number"]))


def location_window(
    date_start: str, lap_duration_s: float, margin_s: float = LOCATION_WINDOW_MARGIN_S
) -> tuple[str, str]:
    start = parse_openf1_time(date_start)
    lo = start - timedelta(seconds=margin_s)
    hi = start + timedelta(seconds=lap_duration_s + margin_s)
    return _format_openf1_time(lo), _format_openf1_time(hi)


def location_url(session_key: int, driver_number: int, window: tuple[str, str]) -> str:
    """Hand-built query: OpenF1 rejects a URL-encoded ``>=`` in the key, so only ``>``/``<`` are escaped."""
    lo, hi = (w.replace("+", "%2B") for w in window)
    return (
        f"{OPENF1_BASE_URL}/location?session_key={session_key}&driver_number={driver_number}"
        f"&date%3E={lo}&date%3C={hi}"
    )


def parse_openf1_time(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _format_openf1_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "+00:00"


# -- paths and persistence ------------------------------------------------------ #


def ingest_summary_path(track_id: str, session_key: int, paths: Paths) -> Path:
    return paths.artifacts / "tracks" / track_id / "ingest" / f"openf1-{session_key}.json"


def load_ingest_summary(track_id: str, session_key: int, paths: Paths) -> IngestResult:
    path = ingest_summary_path(track_id, session_key, paths)
    if not path.exists():
        raise FileNotFoundError(
            f"no OpenF1 ingest summary for track {track_id!r} session {session_key} at {path}; "
            "run `afterlap tracks ingest --source openf1` first (compile does not touch the network)"
        )
    return IngestResult.from_dict(json.loads(path.read_text(encoding="utf-8")))


class _PacedFetcher:
    """Wraps ``RawSourceCache.fetch`` so only cache misses count against the rate limit."""

    def __init__(self, cache: RawSourceCache, min_interval_s: float) -> None:
        self.cache = cache
        self.min_interval_s = min_interval_s
        self._last: float | None = None
        self.network_calls = 0

    def fetch(self, url: str, *, source_id: str, title: str, locator: str) -> CachedSource:
        cached = self.cache.find(OPENF1_SOURCE, url)
        if cached is not None:
            return cached
        if self._last is not None:
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0.0:
                time.sleep(wait)
        self._last = time.monotonic()
        self.network_calls += 1
        return self.cache.fetch(
            url,
            source=OPENF1_SOURCE,
            source_id=source_id,
            title=title,
            permission=OPENF1_PERMISSION,
            priority=OPENF1_PRIORITY,
            locator=locator,
            filename="payload.json",
        )


def _decode(cached: CachedSource) -> Any:
    return json.loads(cached.read_bytes().decode("utf-8"))


def ingest_location_session(
    session_key: int,
    track_id: str,
    paths: Paths,
    driver_number: int | None = None,
    *,
    max_laps: int = DEFAULT_MAX_LAPS,
    min_request_interval_s: float = MIN_REQUEST_INTERVAL_S,
    cache: RawSourceCache | None = None,
) -> IngestResult:
    """Fetch, select and persist clean OpenF1 location laps for one session.

    ``cache`` may be supplied pre-populated (tests do this with fixture bytes via
    :meth:`RawSourceCache.put`); every URL found in the cache is served from disk
    and never re-fetched, so a second run is offline and byte-identical.
    """
    cache = cache or RawSourceCache(paths=paths)
    fetcher = _PacedFetcher(cache, min_request_interval_s)

    session_source = fetcher.fetch(
        f"{OPENF1_BASE_URL}/sessions?session_key={session_key}",
        source_id=f"openf1-sessions-{session_key}",
        title=f"OpenF1 /sessions session_key={session_key}",
        locator=f"session_key={session_key}",
    )
    sessions = _decode(session_source)
    if not isinstance(sessions, list) or len(sessions) != 1:
        count = len(sessions) if isinstance(sessions, list) else "non-list"
        raise OpenF1IngestError(f"OpenF1 /sessions returned {count} rows for session_key={session_key}")
    session = dict(sessions[0])

    laps_source = fetcher.fetch(
        f"{OPENF1_BASE_URL}/laps?session_key={session_key}",
        source_id=f"openf1-laps-{session_key}",
        title=f"OpenF1 /laps session_key={session_key}",
        locator=f"session_key={session_key}; all drivers",
    )
    laps_table = _decode(laps_source)
    if not isinstance(laps_table, list) or not laps_table:
        raise OpenF1IngestError(f"OpenF1 /laps returned no rows for session_key={session_key}")

    accepted, rejected, median_s = select_clean_laps(laps_table)
    chosen_driver, counts = choose_driver(accepted)
    if driver_number is not None:
        if driver_number not in counts:
            raise OpenF1IngestError(
                f"driver {driver_number} has no clean laps in session {session_key}; "
                f"clean laps by driver: {dict(sorted(counts.items()))}"
            )
        chosen_driver = driver_number
    driver_laps = [lap for lap in accepted if int(lap["driver_number"]) == chosen_driver]
    representative = pick_representative(driver_laps, median_s, max_laps)

    records: list[LapRecord] = []
    sources: list[SourceRecord] = [session_source.record, laps_source.record]
    for lap in representative:
        lap_number = int(lap["lap_number"])
        window = location_window(str(lap["date_start"]), float(lap["lap_duration"]))
        url = location_url(session_key, chosen_driver, window)
        cached = fetcher.fetch(
            url,
            source_id=f"openf1-location-{session_key}-{chosen_driver}-lap{lap_number}",
            title=f"OpenF1 /location session_key={session_key} driver={chosen_driver} lap={lap_number}",
            locator=f"session_key={session_key}; driver_number={chosen_driver}; lap_number={lap_number}; "
            f"date in [{window[0]}, {window[1]})",
        )
        samples = _decode(cached)
        if not isinstance(samples, list):
            raise OpenF1IngestError(f"OpenF1 /location payload for lap {lap_number} is not a list")
        sources.append(cached.record)
        records.append(
            LapRecord(
                lap_number=lap_number,
                driver_number=chosen_driver,
                date_start=str(lap["date_start"]),
                lap_duration_s=float(lap["lap_duration"]),
                window_start=window[0],
                window_end=window[1],
                sector_durations_s=(
                    _optional_float(lap.get("duration_sector_1")),
                    _optional_float(lap.get("duration_sector_2")),
                    _optional_float(lap.get("duration_sector_3")),
                ),
                location_sha256=cached.record.sha256 or "",
                location_url=url,
                sample_count=len(samples),
                retrieved_at=cached.record.retrieved_at,
            )
        )

    if not records:
        raise OpenF1IngestError(
            f"no representative laps selected for driver {chosen_driver} in session {session_key}"
        )

    summary_path = ingest_summary_path(track_id, session_key, paths)
    notes = (
        "Coordinate units are not decided at ingest; the compiler infers the scale from the official length.",
        f"Rate limit respected: {fetcher.network_calls} network call(s) this run at "
        f">= {min_request_interval_s:.1f} s spacing; the rest were served from the raw cache.",
        f"Representative laps are the {len(records)} clean laps closest to the session median duration "
        "for the chosen driver.",
    )
    result = IngestResult(
        session_key=session_key,
        track_id=track_id,
        driver_number=chosen_driver,
        session={
            key: session.get(key)
            for key in (
                "session_key",
                "meeting_key",
                "session_name",
                "session_type",
                "year",
                "circuit_key",
                "circuit_short_name",
                "location",
                "country_name",
                "date_start",
                "date_end",
            )
        },
        laps=tuple(records),
        rejected=rejected,
        median_lap_duration_s=median_s,
        clean_laps_by_driver=dict(sorted(counts.items())),
        sources=tuple(sources),
        summary_path=summary_path,
        notes=notes,
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    staging = summary_path.with_suffix(".json.staging")
    staging.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    staging.replace(summary_path)
    return result


def _optional_float(value: Any) -> float | None:
    if value is None or not isinstance(value, int | float):
        return None
    return float(value)


__all__ = [
    "DEFAULT_MAX_LAPS",
    "LAP_DURATION_TOLERANCE",
    "LOCATION_WINDOW_MARGIN_S",
    "MIN_REQUEST_INTERVAL_S",
    "OPENF1_BASE_URL",
    "OPENF1_LICENCE_URL",
    "OPENF1_PERMISSION",
    "OPENF1_PRIORITY",
    "OPENF1_SOURCE",
    "IngestResult",
    "LapRecord",
    "OpenF1IngestError",
    "choose_driver",
    "ingest_location_session",
    "ingest_summary_path",
    "load_ingest_summary",
    "location_url",
    "location_window",
    "parse_openf1_time",
    "pick_representative",
    "select_clean_laps",
]
