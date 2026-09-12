from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from ..config import Parameter
from .config import TrackCheckpoint, TrackSegment


@runtime_checkable
class TrackSource(Protocol):
    id: str
    synthetic: bool
    geometry_provenance: str
    lateral_geometry_surveyed: bool
    timing_line_s_m: Parameter
    checkpoints: tuple[TrackCheckpoint, ...]
    segments: tuple[TrackSegment, ...]

    @property
    def length(self) -> float: ...

    @property
    def config_hash(self) -> str: ...

    @property
    def checkpoint_ids(self) -> tuple[str, ...]: ...

    def checkpoint(self, checkpoint_id: str) -> TrackCheckpoint: ...

    def curvature_at(self, s_m: float) -> float: ...

    def grade_at(self, s_m: float) -> float: ...

    def mu_at(self, s_m: float) -> float: ...

    def width_at(self, s_m: float) -> float: ...

    def curvature_array(self, s_m: np.ndarray) -> np.ndarray: ...

    def mu_array(self, s_m: np.ndarray) -> np.ndarray: ...

    def width_array(self, s_m: np.ndarray) -> np.ndarray: ...


@runtime_checkable
class EnvironmentField(Protocol):
    def air_density_kgpm3(self, s_m: float, session_time_s: float, fallback: float) -> float: ...

    def headwind_mps(self, s_m: float, heading_rad: float, session_time_s: float) -> float: ...

    def grip_multiplier(self, s_m: float, session_time_s: float) -> float: ...

    def grip_multiplier_array(self, s_m: np.ndarray, session_time_s: float) -> np.ndarray: ...

    @property
    def describes(self) -> str: ...


@dataclass(frozen=True, slots=True)
class StaticEnvironment:
    def air_density_kgpm3(self, s_m: float, session_time_s: float, fallback: float) -> float:
        return fallback

    def headwind_mps(self, s_m: float, heading_rad: float, session_time_s: float) -> float:
        return 0.0

    def grip_multiplier(self, s_m: float, session_time_s: float) -> float:
        return 1.0

    def grip_multiplier_array(self, s_m: np.ndarray, session_time_s: float) -> np.ndarray:
        return np.asarray([self.grip_multiplier(float(s), session_time_s) for s in s_m])

    @property
    def describes(self) -> str:
        return "static: car-document density, still air, dry reference grip"


DEFAULT_ENVIRONMENT = StaticEnvironment()
