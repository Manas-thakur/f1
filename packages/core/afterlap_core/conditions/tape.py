"""Time-indexed weather samples with provenance and a content hash.

A :class:`ConditionsTape` is the replayable record of one session's
atmosphere: air and track temperature (K), pressure (Pa), relative humidity
(fraction), wind speed (m/s), meteorological wind direction (rad, blowing
*from*, clockwise from north) and a rainfall flag. Values the source did not
report are ``None`` -- never zero -- and interpolation skips them.

Interpolation is linear in session time for continuous fields, shortest-arc
for wind direction, zero-order hold for the rainfall flag, and **clamped** at
both ends: a query before the first sample returns the first sample, one after
the last returns the last. That is deterministic and requires no assumption
about what happened outside the recorded window.

The content hash covers the samples, the altitude and the identifying
provenance fields, so changing any single sample changes the hash. An optional
keyed gust specification is carried on the tape but is **off by default**; the
environment applies it (see :mod:`field`).
"""

from __future__ import annotations

import bisect
import itertools
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ..paths import atomic_write_text, sha256_json
from .wind import interpolate_direction_rad

TAPE_SCHEMA_VERSION = "conditions-tape/1"
_CONTINUOUS_FIELDS = (
    "air_temperature_k",
    "track_temperature_k",
    "pressure_pa",
    "humidity_fraction",
    "wind_speed_mps",
)


@dataclass(frozen=True, slots=True)
class ConditionsSample:
    """One observation in SI units; unknown fields are ``None``."""

    session_time_s: float
    air_temperature_k: float | None = None
    track_temperature_k: float | None = None
    pressure_pa: float | None = None
    humidity_fraction: float | None = None
    wind_speed_mps: float | None = None
    wind_direction_rad: float | None = None
    rainfall: bool | None = None

    def __post_init__(self) -> None:
        if self.humidity_fraction is not None and not (0.0 <= self.humidity_fraction <= 1.0):
            raise ValueError(f"humidity {self.humidity_fraction} must be a fraction in [0, 1]")
        if self.wind_speed_mps is not None and self.wind_speed_mps < 0.0:
            raise ValueError("wind speed cannot be negative")
        if self.pressure_pa is not None and self.pressure_pa < 30000.0:
            raise ValueError(
                f"pressure {self.pressure_pa} Pa is implausibly low; was a mbar value stored unconverted?"
            )
        if self.air_temperature_k is not None and self.air_temperature_k < 150.0:
            raise ValueError(f"air temperature {self.air_temperature_k} K looks like Celsius; convert first")


class ConditionsProvenance(BaseModel):
    """Where a tape came from and how its units were converted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_kind: str = Field(pattern=r"^(openf1|synthetic)$")
    label: str = Field(min_length=1)
    permission: str | None = None
    url: str | None = None
    raw_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    retrieved_at: str | None = None
    session_key: int | None = None
    time_origin_utc: str | None = Field(
        default=None, description="ISO-8601 instant that session_time_s = 0 refers to, if known."
    )
    conversions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def is_synthetic(self) -> bool:
        return self.source_kind == "synthetic"


class GustSpec(BaseModel):
    """Keyed stochastic perturbation of wind speed. Disabled unless declared."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    sigma_mps: float = Field(default=0.0, ge=0.0)
    bin_width_s: float = Field(default=2.0, gt=0.0)
    event_type: str = "wind_gust"
    source: str = "synthetic:afterlap-conditions-gust-v1"


class ConditionsTape:
    """Sorted samples plus provenance; see the module docstring for semantics."""

    def __init__(
        self,
        tape_id: str,
        samples: Iterable[ConditionsSample],
        provenance: ConditionsProvenance,
        *,
        altitude_m: float | None = None,
        altitude_source: str | None = None,
        gust: GustSpec | None = None,
    ) -> None:
        ordered = tuple(sorted(samples, key=lambda s: s.session_time_s))
        if not ordered:
            raise ValueError("a conditions tape needs at least one sample")
        times = [s.session_time_s for s in ordered]
        if any(b <= a for a, b in itertools.pairwise(times)):
            raise ValueError("sample times must be strictly increasing")
        if altitude_m is not None and altitude_source is None:
            raise ValueError("an altitude needs a source note")
        self.tape_id = tape_id
        self.samples = ordered
        self.provenance = provenance
        self.altitude_m = altitude_m
        self.altitude_source = altitude_source
        self.gust = gust or GustSpec()
        self._times = np.asarray(times, dtype=np.float64)
        self._fields: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for name in _CONTINUOUS_FIELDS:
            known = [(s.session_time_s, getattr(s, name)) for s in ordered if getattr(s, name) is not None]
            if known:
                t, v = zip(*known, strict=True)
                self._fields[name] = (np.asarray(t, dtype=np.float64), np.asarray(v, dtype=np.float64))
        self._direction: list[tuple[float, float]] = [
            (s.session_time_s, s.wind_direction_rad) for s in ordered if s.wind_direction_rad is not None
        ]
        self._rain: list[tuple[float, bool]] = [
            (s.session_time_s, s.rainfall) for s in ordered if s.rainfall is not None
        ]

    @property
    def start_time_s(self) -> float:
        return float(self._times[0])

    @property
    def end_time_s(self) -> float:
        return float(self._times[-1])

    @property
    def duration_s(self) -> float:
        return self.end_time_s - self.start_time_s

    def _hashed_payload(self) -> dict[str, Any]:
        return {
            "schema": TAPE_SCHEMA_VERSION,
            "tape_id": self.tape_id,
            "samples": [asdict(s) for s in self.samples],
            "altitude_m": self.altitude_m,
            "source_kind": self.provenance.source_kind,
            "session_key": self.provenance.session_key,
            "raw_sha256": self.provenance.raw_sha256,
        }

    @property
    def content_hash(self) -> str:
        return sha256_json(self._hashed_payload())

    def _continuous(self, name: str, t: float) -> float | None:
        entry = self._fields.get(name)
        if entry is None:
            return None
        times, values = entry
        return float(np.interp(t, times, values))

    def _direction_at(self, t: float) -> float | None:
        if not self._direction:
            return None
        times = [d[0] for d in self._direction]
        if t <= times[0]:
            return self._direction[0][1]
        if t >= times[-1]:
            return self._direction[-1][1]
        index = bisect.bisect_right(times, t)
        t0, d0 = self._direction[index - 1]
        t1, d1 = self._direction[index]
        return interpolate_direction_rad(d0, d1, (t - t0) / (t1 - t0))

    def _rain_at(self, t: float) -> bool | None:
        if not self._rain:
            return None
        times = [r[0] for r in self._rain]
        if t < times[0]:
            return self._rain[0][1]
        index = bisect.bisect_right(times, t) - 1
        return self._rain[index][1]

    def at(self, session_time_s: float) -> ConditionsSample:
        """Interpolated conditions at ``session_time_s``, clamped to the recorded window."""
        t = float(session_time_s)
        clamped = min(max(t, self.start_time_s), self.end_time_s)
        return ConditionsSample(
            session_time_s=clamped,
            air_temperature_k=self._continuous("air_temperature_k", clamped),
            track_temperature_k=self._continuous("track_temperature_k", clamped),
            pressure_pa=self._continuous("pressure_pa", clamped),
            humidity_fraction=self._continuous("humidity_fraction", clamped),
            wind_speed_mps=self._continuous("wind_speed_mps", clamped),
            wind_direction_rad=self._direction_at(clamped),
            rainfall=self._rain_at(clamped),
        )

    def rainfall_seconds(self) -> float | None:
        """Time with the rainfall flag set, integrating the zero-order hold."""
        if not self._rain:
            return None
        total = 0.0
        for (t0, flag), (t1, _) in itertools.pairwise(self._rain):
            if flag:
                total += t1 - t0
        return total

    def summary(self) -> dict[str, Any]:
        """Descriptive numbers for the handoff; density needs :mod:`atmosphere`."""
        from .atmosphere import air_density

        densities = []
        for s in self.samples:
            result = air_density(
                temperature_k=s.air_temperature_k,
                pressure_pa=s.pressure_pa,
                humidity_fraction=s.humidity_fraction,
                altitude_m=self.altitude_m,
            )
            if result.value_kgpm3 is not None:
                densities.append(result.value_kgpm3)

        def mean(name: str) -> float | None:
            entry = self._fields.get(name)
            return None if entry is None else float(np.mean(entry[1]))

        rain_s = self.rainfall_seconds()
        return {
            "tape_id": self.tape_id,
            "content_hash": self.content_hash,
            "samples": len(self.samples),
            "duration_s": self.duration_s,
            "mean_air_density_kgpm3": float(np.mean(densities)) if densities else None,
            "mean_air_temperature_k": mean("air_temperature_k"),
            "mean_track_temperature_k": mean("track_temperature_k"),
            "mean_pressure_pa": mean("pressure_pa"),
            "mean_humidity_fraction": mean("humidity_fraction"),
            "mean_wind_speed_mps": mean("wind_speed_mps"),
            "rainfall_minutes": None if rain_s is None else rain_s / 60.0,
            "altitude_m": self.altitude_m,
            "retrieved_at": self.provenance.retrieved_at,
            "source_kind": self.provenance.source_kind,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": TAPE_SCHEMA_VERSION,
            "tape_id": self.tape_id,
            "content_hash": self.content_hash,
            "altitude_m": self.altitude_m,
            "altitude_source": self.altitude_source,
            "provenance": self.provenance.model_dump(mode="json"),
            "gust": self.gust.model_dump(mode="json"),
            "samples": [asdict(s) for s in self.samples],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ConditionsTape:
        if payload.get("schema") != TAPE_SCHEMA_VERSION:
            raise ValueError(f"unsupported conditions tape schema {payload.get('schema')!r}")
        tape = cls(
            payload["tape_id"],
            (ConditionsSample(**s) for s in payload["samples"]),
            ConditionsProvenance.model_validate(payload["provenance"]),
            altitude_m=payload.get("altitude_m"),
            altitude_source=payload.get("altitude_source"),
            gust=GustSpec.model_validate(payload.get("gust") or {}),
        )
        recorded = payload.get("content_hash")
        if recorded is not None and recorded != tape.content_hash:
            raise ValueError(
                f"conditions tape {tape.tape_id!r} changed since it was written: "
                f"{tape.content_hash[:19]} != {str(recorded)[:19]}"
            )
        return tape

    def write_json(self, path: Path) -> str:
        atomic_write_text(path, json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")
        return self.content_hash

    @classmethod
    def read_json(cls, path: Path) -> ConditionsTape:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


__all__ = [
    "TAPE_SCHEMA_VERSION",
    "ConditionsProvenance",
    "ConditionsSample",
    "ConditionsTape",
    "GustSpec",
]
