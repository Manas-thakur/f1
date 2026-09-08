"""``configs/conditions/<id>.yaml`` to a tape, and a tape to an environment.

A conditions document declares either::

    source: openf1
    session_key: 9912

or::

    source: synthetic
    synthetic:
      air_temperature_k: 288.15
      ...

Real tapes are fetched once through the raw-source cache and frozen under
``artifacts/conditions/<id>.json`` with their content hash; a later load reads
the frozen file and refuses it if the hash no longer matches. When the file
is absent and network access is not permitted the loader raises
:class:`ConditionsUnavailable` rather than inventing weather.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..config import load_config
from ..paths import Paths
from ..tracks.provenance import RawSourceCache
from .field import TapeEnvironment
from .openf1_weather import fetch_openf1_weather, tape_from_cached_source
from .tape import ConditionsProvenance, ConditionsSample, ConditionsTape, GustSpec


class ConditionsUnavailable(FileNotFoundError):
    """The tape cannot be produced honestly from what is on disk."""


class SyntheticConstants(BaseModel):
    """Constant SI conditions for a synthetic scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    air_temperature_k: float = Field(ge=200.0, le=350.0)
    track_temperature_k: float | None = Field(default=None, ge=200.0, le=380.0)
    pressure_pa: float | None = Field(default=None, ge=30000.0, le=110000.0)
    humidity_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    wind_speed_mps: float | None = Field(default=None, ge=0.0)
    wind_direction_deg: float | None = Field(default=None, ge=0.0, lt=360.0)
    rainfall: bool | None = None
    duration_s: float = Field(default=7200.0, gt=0.0)
    sample_interval_s: float = Field(default=60.0, gt=0.0)


class ConditionsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    description: str | None = None
    source: Literal["openf1", "synthetic"]
    session_key: int | None = None
    altitude_m: float | None = None
    altitude_source: str | None = None
    synthetic: SyntheticConstants | None = None
    gust: GustSpec = GustSpec()
    rubber_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _shape(self) -> ConditionsConfig:
        if self.source == "openf1" and self.session_key is None:
            raise ValueError("an openf1 conditions document needs a session_key")
        if self.source == "synthetic" and self.synthetic is None:
            raise ValueError("a synthetic conditions document needs explicit constants")
        if self.altitude_m is not None and not self.altitude_source:
            raise ValueError("altitude_m needs an altitude_source")
        if self.gust.enabled and self.gust.sigma_mps <= 0.0:
            raise ValueError("an enabled gust model needs a positive sigma_mps")
        return self


def load_conditions_config(conditions_id: str, paths: Paths | None = None) -> ConditionsConfig:
    return ConditionsConfig.model_validate(load_config("conditions", conditions_id, paths))


def tape_cache_path(conditions_id: str, paths: Paths | None = None) -> Path:
    return (paths or Paths.default()).artifacts / "conditions" / f"{conditions_id}.json"


def synthetic_tape(config: ConditionsConfig) -> ConditionsTape:
    constants = config.synthetic
    assert constants is not None
    count = max(2, math.floor(constants.duration_s / constants.sample_interval_s) + 1)
    direction = None if constants.wind_direction_deg is None else math.radians(constants.wind_direction_deg)
    samples = [
        ConditionsSample(
            session_time_s=i * constants.sample_interval_s,
            air_temperature_k=constants.air_temperature_k,
            track_temperature_k=constants.track_temperature_k,
            pressure_pa=constants.pressure_pa,
            humidity_fraction=constants.humidity_fraction,
            wind_speed_mps=constants.wind_speed_mps,
            wind_direction_rad=direction,
            rainfall=constants.rainfall,
        )
        for i in range(count)
    ]
    provenance = ConditionsProvenance(
        source_kind="synthetic",
        label=f"synthetic constants from configs/conditions/{config.id}.yaml",
        permission="synthetic scenario; no external rights involved",
        conversions=("wind_direction_deg -> rad (x pi/180); all other values authored in SI",),
        notes=config.notes,
    )
    return ConditionsTape(
        config.id,
        samples,
        provenance,
        altitude_m=config.altitude_m,
        altitude_source=config.altitude_source,
        gust=config.gust,
    )


def load_conditions(
    conditions_id: str, paths: Paths | None = None, *, allow_network: bool = True, refresh: bool = False
) -> ConditionsTape:
    """Resolve a conditions id to a tape; see the module docstring."""
    paths = paths or Paths.default()
    config = load_conditions_config(conditions_id, paths)
    if config.source == "synthetic":
        return synthetic_tape(config)

    assert config.session_key is not None
    cache_path = tape_cache_path(conditions_id, paths)
    if cache_path.exists() and not refresh:
        tape = ConditionsTape.read_json(cache_path)
        if tape.provenance.session_key != config.session_key:
            raise ConditionsUnavailable(
                f"cached tape {cache_path} is for session {tape.provenance.session_key}, "
                f"config names {config.session_key}"
            )
        return tape

    raw = RawSourceCache(paths=paths)
    cached = raw.find("openf1", "https://api.openf1.org/v1/weather", {"session_key": config.session_key})
    if cached is None:
        if not allow_network:
            raise ConditionsUnavailable(
                f"conditions {conditions_id!r} (openf1 session {config.session_key}) has no frozen tape at "
                f"{cache_path} and network access is not permitted"
            )
        cached = fetch_openf1_weather(config.session_key, raw, refresh=refresh)
    tape = tape_from_cached_source(
        cached,
        tape_id=conditions_id,
        session_key=config.session_key,
        altitude_m=config.altitude_m,
        altitude_source=config.altitude_source,
        gust=config.gust,
    )
    tape.write_json(cache_path)
    return tape


def environment_for(
    tape: ConditionsTape, track: Any, *, seed: int = 0, rubber_fraction: float | None = None
) -> TapeEnvironment:
    """Bind a tape to a track's frame.

    The engine's heading is relative to the start direction; a compiled
    package exposes ``yaw_at`` so the absolute ENU yaw at ``s = 0`` becomes the
    offset. A synthetic sketch has no absolute orientation, so the offset is
    recorded as unknown and the wind is projected in the relative frame.
    """
    yaw_at = getattr(track, "yaw_at", None)
    offset = float(yaw_at(0.0)) if callable(yaw_at) else None
    return TapeEnvironment(
        tape,
        heading_offset_rad=offset,
        rubber_fraction=0.0 if rubber_fraction is None else rubber_fraction,
        seed=seed,
    )


__all__ = [
    "ConditionsConfig",
    "ConditionsUnavailable",
    "SyntheticConstants",
    "environment_for",
    "load_conditions",
    "load_conditions_config",
    "synthetic_tape",
    "tape_cache_path",
]
