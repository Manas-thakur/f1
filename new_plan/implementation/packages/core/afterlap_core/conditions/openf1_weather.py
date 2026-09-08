"""OpenF1 ``/v1/weather`` records into a :class:`ConditionsTape`.

Source: ``https://api.openf1.org/v1/weather?session_key=K`` (priority 3 in
``TRACK_DATA_PIPELINE.md``). Every byte goes through
:class:`~afterlap_core.tracks.provenance.RawSourceCache` first, so the tape
records the SHA-256 of the raw response and the retrieval time.

Units per the OpenF1 documentation (https://openf1.org, "Weather"), and the
conversions applied here, recorded verbatim on the tape's provenance:

    air_temperature    degC   -> K      (+273.15)
    track_temperature  degC   -> K      (+273.15)
    pressure           mbar   -> Pa     (x100)
    humidity           %      -> 1      (/100)
    wind_direction     deg    -> rad    (clockwise from north, blowing from; x pi/180)
    wind_speed         m/s    -> m/s    (unchanged)
    rainfall           0/1    -> bool
    date               ISO-8601 UTC -> session_time_s relative to the first record

A missing or null field stays ``None``. Records whose ``session_key`` does not
match the request are refused rather than silently merged.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

from ..tracks.package import SourceRecord
from ..tracks.provenance import CachedSource, RawSourceCache
from .atmosphere import CELSIUS_OFFSET_K
from .tape import ConditionsProvenance, ConditionsSample, ConditionsTape, GustSpec

OPENF1_WEATHER_URL = "https://api.openf1.org/v1/weather"
OPENF1_PERMISSION = "OpenF1 public API; free for non-commercial use per openf1.org"
OPENF1_PRIORITY = 3

CONVERSIONS: tuple[str, ...] = (
    "air_temperature: degC -> K (+273.15)",
    "track_temperature: degC -> K (+273.15)",
    "pressure: mbar -> Pa (x100)",
    "humidity: % -> fraction (/100)",
    "wind_direction: deg clockwise from north (from) -> rad (x pi/180)",
    "wind_speed: m/s unchanged",
    "rainfall: 0/1 -> bool",
    "date: ISO-8601 UTC -> session_time_s since first record",
)


def fetch_openf1_weather(session_key: int, cache: RawSourceCache, *, refresh: bool = False) -> CachedSource:
    """Retrieve (or reuse) the raw weather response for one session."""
    return cache.fetch(
        OPENF1_WEATHER_URL,
        params={"session_key": int(session_key)},
        source="openf1",
        source_id=f"openf1-weather-{int(session_key)}",
        title=f"OpenF1 weather, session {int(session_key)}",
        permission=OPENF1_PERMISSION,
        priority=OPENF1_PRIORITY,
        locator=f"session_key={int(session_key)}",
        filename="payload.json",
        refresh=refresh,
    )


def _float(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return None if math.isnan(number) else number


def _parse_utc(text: str) -> datetime:
    stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError(f"OpenF1 timestamp {text!r} carries no timezone")
    return stamp


def sample_from_record(record: dict[str, Any], origin: datetime) -> ConditionsSample:
    humidity = _float(record.get("humidity"))
    direction = _float(record.get("wind_direction"))
    pressure = _float(record.get("pressure"))
    air = _float(record.get("air_temperature"))
    track = _float(record.get("track_temperature"))
    rain = record.get("rainfall")
    return ConditionsSample(
        session_time_s=(_parse_utc(record["date"]) - origin).total_seconds(),
        air_temperature_k=None if air is None else air + CELSIUS_OFFSET_K,
        track_temperature_k=None if track is None else track + CELSIUS_OFFSET_K,
        pressure_pa=None if pressure is None else pressure * 100.0,
        humidity_fraction=None if humidity is None else humidity / 100.0,
        wind_speed_mps=_float(record.get("wind_speed")),
        wind_direction_rad=None if direction is None else math.radians(direction % 360.0),
        rainfall=None if rain is None else bool(int(rain)),
    )


def tape_from_openf1_records(
    records: list[dict[str, Any]],
    *,
    tape_id: str,
    session_key: int,
    source: SourceRecord | None,
    altitude_m: float | None = None,
    altitude_source: str | None = None,
    gust: GustSpec | None = None,
    notes: tuple[str, ...] = (),
) -> ConditionsTape:
    """Convert decoded OpenF1 records; ``source`` is the raw-cache record when real."""
    if not records:
        raise ValueError(f"OpenF1 returned no weather records for session {session_key}")
    wrong = {str(r.get("session_key")) for r in records if r.get("session_key") != session_key}
    if wrong:
        raise ValueError(f"records for session {sorted(wrong)} mixed into session {session_key}")
    ordered = sorted(records, key=lambda r: _parse_utc(r["date"]))
    origin = _parse_utc(ordered[0]["date"])
    samples: list[ConditionsSample] = []
    last_t: float | None = None
    for record in ordered:
        sample = sample_from_record(record, origin)
        if last_t is not None and sample.session_time_s <= last_t:
            continue  # duplicate timestamp: keep the first, do not fabricate an ordering
        samples.append(sample)
        last_t = sample.session_time_s
    provenance = ConditionsProvenance(
        source_kind="openf1",
        label=f"openf1 weather session {session_key}",
        permission=OPENF1_PERMISSION if source is None else source.permission,
        url=None if source is None else source.url,
        raw_sha256=None if source is None else source.sha256,
        retrieved_at=None if source is None else source.retrieved_at,
        session_key=session_key,
        time_origin_utc=origin.isoformat(),
        conversions=CONVERSIONS,
        notes=notes,
    )
    return ConditionsTape(
        tape_id, samples, provenance, altitude_m=altitude_m, altitude_source=altitude_source, gust=gust
    )


def tape_from_cached_source(
    cached: CachedSource,
    *,
    tape_id: str,
    session_key: int,
    altitude_m: float | None = None,
    altitude_source: str | None = None,
    gust: GustSpec | None = None,
) -> ConditionsTape:
    records = json.loads(cached.read_bytes().decode("utf-8"))
    if not isinstance(records, list):
        raise ValueError("OpenF1 weather payload must be a JSON array")
    return tape_from_openf1_records(
        records,
        tape_id=tape_id,
        session_key=session_key,
        source=cached.record,
        altitude_m=altitude_m,
        altitude_source=altitude_source,
        gust=gust,
    )


__all__ = [
    "CONVERSIONS",
    "OPENF1_PERMISSION",
    "OPENF1_PRIORITY",
    "OPENF1_WEATHER_URL",
    "fetch_openf1_weather",
    "sample_from_record",
    "tape_from_cached_source",
    "tape_from_openf1_records",
]
