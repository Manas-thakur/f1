from __future__ import annotations

import math
from functools import lru_cache
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ..rng import StreamRegistry


class DriverTraits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    headway_s: float = Field(default=0.8, ge=0.4, le=2.0)
    reaction_s: float = Field(default=0.18, ge=0, le=0.5)
    clearance_m: float = Field(default=0.65, ge=0.3, le=1.5)
    commitment_s: float = Field(default=1.5, ge=0.5, le=4)
    pace: float = Field(default=0.93, ge=0.7, le=0.98)
    braking_fraction: float = Field(default=0.92, ge=0.75, le=0.98)
    jerk_mps3: float = Field(default=5, ge=1, le=15)
    lateral_rate_mps: float = Field(default=1.5, ge=0.5, le=2.5)
    preferred_line_m: float = Field(default=0, ge=-3, le=3)
    reserve_j: float = Field(default=650000, ge=200000, le=1500000)


class Variability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    preset: Literal["baseline", "mild", "training", "stress"] = "mild"
    grid_scale: float = Field(default=1, ge=0, le=1)
    driver_scale: float = Field(default=1, ge=0, le=1)
    vehicle_scale: float = Field(default=1, ge=0, le=1)
    sensor_scale: float = Field(default=1, ge=0, le=2)
    surface_scale: float = Field(default=1, ge=0, le=1)
    wind_scale: float = Field(default=1, ge=0, le=1)
    wetness_target: float | None = Field(default=None, ge=0, le=1)
    weather_tau_s: float = Field(default=120, ge=30, le=1800)
    drivers: dict[str, DriverTraits] = Field(default_factory=dict)

    @property
    def strength(self) -> float:
        return {"baseline": 0.0, "mild": 0.25, "training": 0.65, "stress": 1.0}[self.preset]

    def sample_driver(self, streams: StreamRegistry, car_id: str) -> DriverTraits:
        if car_id in self.drivers:
            return self.drivers[car_id]
        rng = streams.stream(f"traits:{car_id}")
        scale = self.strength * self.driver_scale
        risk, response, line = np.clip(rng.normal(size=3), -2, 2) * scale
        return DriverTraits(
            headway_s=0.8 - 0.15 * risk,
            reaction_s=0.18 + 0.05 * response,
            clearance_m=0.65 - 0.12 * risk,
            commitment_s=1.5 + 0.5 * risk,
            pace=0.93 + 0.02 * risk,
            braking_fraction=0.92 + 0.02 * risk,
            jerk_mps3=5 + 1.5 * risk,
            lateral_rate_mps=1.5 + 0.3 * risk,
            preferred_line_m=float(line),
            reserve_j=650000 - 150000 * risk,
        )


@lru_cache(maxsize=16)
def _uniform_preview(shape: tuple[int, ...], grip: float) -> np.ndarray:
    values = np.full(shape, grip, dtype=np.float64)
    values.setflags(write=False)
    return values


class RaceWeather:
    def __init__(
        self,
        temperature_k: float,
        wind_mps: float,
        wetness: float,
        length_m: float,
        variability: Variability,
        seed: int,
    ) -> None:
        self.temperature_k = temperature_k
        self.wind_mps = wind_mps
        self.wetness = wetness
        self.length_m = length_m
        self.variability = variability
        rng = StreamRegistry(seed).stream("weather:episode")
        self.phases = tuple(float(value) for value in rng.uniform(0, 2 * math.pi, size=4))
        amplitude = variability.strength * variability.surface_scale
        self.target = variability.wetness_target
        if self.target is None:
            self.target = min(1.0, max(0.0, wetness + amplitude * float(rng.normal(0, 0.3))))
        self.patch_amplitude = 0.12 * amplitude
        self.gust_amplitude = 4 * variability.strength * variability.wind_scale

    def wetness_at(self, session_time_s: float) -> float:
        return self.target + (self.wetness - self.target) * math.exp(
            -max(0.0, session_time_s) / self.variability.weather_tau_s
        )

    def air_density_kgpm3(self, s_m: float, session_time_s: float, fallback: float) -> float:
        return 101325 / (287.05 * self.temperature_k)

    def headwind_mps(self, s_m: float, heading_rad: float, session_time_s: float) -> float:
        gust = (
            self.gust_amplitude
            * (math.sin(session_time_s / 7 + self.phases[2]) + math.sin(session_time_s / 17 + self.phases[3]))
            / 2
        )
        return (self.wind_mps + gust) * math.cos(heading_rad)

    def grip_multiplier(self, s_m: float, session_time_s: float) -> float:
        phase = 2 * math.pi * (s_m % self.length_m) / self.length_m
        patch = (2 + math.sin(3 * phase + self.phases[0]) + math.sin(7 * phase + self.phases[1])) / 4
        return (1 - 0.45 * self.wetness_at(session_time_s)) * (1 - self.patch_amplitude * patch)

    def grip_multiplier_array(self, s_m: np.ndarray, session_time_s: float) -> np.ndarray:
        phase = 2 * math.pi * (s_m % self.length_m) / self.length_m
        patch = (2 + np.sin(3 * phase + self.phases[0]) + np.sin(7 * phase + self.phases[1])) / 4
        return (1 - 0.45 * self.wetness_at(session_time_s)) * (1 - self.patch_amplitude * patch)

    def preview_grip(self, s_m: float, session_time_s: float) -> float:
        measured = self.wetness_at(max(0.0, session_time_s - 0.1))
        return (1 - 0.45 * measured) * (1 - self.patch_amplitude)

    def preview_grip_array(self, s_m: np.ndarray, session_time_s: float) -> np.ndarray:
        return _uniform_preview(s_m.shape, self.preview_grip(0, session_time_s))

    def manifest(self) -> dict[str, object]:
        return {
            "wetness_target": self.target,
            "phases_rad": self.phases,
            "patch_amplitude": self.patch_amplitude,
            "gust_amplitude_mps": self.gust_amplitude,
            "provenance": "configurable synthetic hypotheses, not measured distributions",
        }

    @property
    def describes(self) -> str:
        return "synthetic water-balance relaxation, periodic grip patches and band-limited wind"
