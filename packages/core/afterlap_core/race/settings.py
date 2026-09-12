from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .circuit import default_laps
from .variability import Variability


class RacingLineSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    enabled: bool = True
    corner_strength: float = Field(default=0.9, ge=0, le=1)
    randomness: float = Field(default=0.7, ge=0, le=1)
    wander_m: float = Field(default=0.8, ge=0, le=2)
    lookahead_m: float = Field(default=65, ge=10, le=200)
    smoothing_m: float = Field(default=30, ge=5, le=100)
    overtake_in_corners: bool = True


class RaceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    circuit: str = Field(default="silverstone", pattern=r"^[a-z0-9-]+$")
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    cars: int = Field(default=20, ge=1, le=20)
    laps: int = Field(default=52, ge=1, le=80)
    dt_s: float = Field(default=0.01, ge=0.005, le=0.02)
    wetness: float = Field(default=0.0, ge=0.0, le=1.0)
    temperature_k: float = Field(default=303.15, ge=273.15, le=323.15)
    wind_mps: float = Field(default=0.0, ge=-20, le=20)
    wake: bool = True
    time_limit_s: float = Field(default=1800, ge=1, le=14400)
    contact_mode: Literal["ignore", "terminate"] = "ignore"

    variability: Variability = Field(default_factory=Variability)
    racing_line: RacingLineSettings = Field(default_factory=RacingLineSettings)

    @model_validator(mode="before")
    @classmethod
    def circuit_lap_default(cls, data: Any) -> Any:
        if isinstance(data, dict) and "laps" not in data:
            data = {**data, "laps": default_laps(data.get("circuit", "silverstone"))}
        return data

    @model_validator(mode="after")
    def known_drivers(self) -> RaceSettings:
        allowed = {f"car-{index + 1:02d}" for index in range(self.cars)}
        if self.variability.drivers.keys() - allowed:
            raise ValueError("driver overrides must name a car in this field")
        return self
