"""The seams that let a compiled real circuit drive the existing simulator.

Two protocols and two adapters, all coordinator-owned:

* :class:`TrackSource` is the interface the engine, geometry, ledger and
  learning encoder already consume from ``TrackConfig``. A compiled real-circuit
  package satisfies it through :class:`CompiledTrackSource`, so physics code
  does not change when the geometry source does.
* :class:`EnvironmentField` supplies air density, wind and a grip modifier at a
  point on the lap. :class:`StaticEnvironment` reproduces the pre-A16 behaviour
  bit for bit (density from the car document, no wind, unit grip), so every
  existing numerical test keeps its meaning; a conditions model replaces it for
  real-circuit scenarios.

The engine reads the environment at exactly two sites — the drag/downforce
density and the surface grip — and nowhere else.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from ..config import Parameter, VerificationStatus
from ..tracks.package import CompiledCentreline, GeometryProvenance, TrackPackage
from .config import TrackCheckpoint, TrackSegment


@runtime_checkable
class TrackSource(Protocol):
    """What the simulator, ledger and encoder need from a circuit.

    ``TrackConfig`` satisfies this structurally already. Anything new that
    wants to be driven must satisfy it too; the engine is typed against the
    protocol, not the class.
    """

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
    """Atmosphere and surface state at a lap position and session time."""

    def air_density_kgpm3(self, s_m: float, session_time_s: float, fallback: float) -> float:
        """Density used in drag and downforce. ``fallback`` is the car document's value."""
        ...

    def headwind_mps(self, s_m: float, heading_rad: float, session_time_s: float) -> float:
        """Wind component opposing travel at this heading; positive slows the car."""
        ...

    def grip_multiplier(self, s_m: float, session_time_s: float) -> float:
        """Multiplies the surface ``mu``; 1.0 is the dry reference."""
        ...

    @property
    def describes(self) -> str:
        """Short provenance label recorded on every run."""
        ...


@dataclass(frozen=True, slots=True)
class StaticEnvironment:
    """Pre-A16 behaviour: car-document density, still air, dry reference grip.

    Kept so every existing conservation and convergence test is unchanged. A
    scenario that does not name a conditions tape gets this and says so.
    """

    def air_density_kgpm3(self, s_m: float, session_time_s: float, fallback: float) -> float:
        return fallback

    def headwind_mps(self, s_m: float, heading_rad: float, session_time_s: float) -> float:
        return 0.0

    def grip_multiplier(self, s_m: float, session_time_s: float) -> float:
        return 1.0

    @property
    def describes(self) -> str:
        return "static: car-document density, still air, dry reference grip"


DEFAULT_ENVIRONMENT = StaticEnvironment()


class CompiledTrackSource:
    """A hash-pinned real-circuit package presented through :class:`TrackSource`.

    Dense 1 m arrays are interpolated periodically. Where the package has no
    corridor, ``width_at`` returns ``nan`` and ``lateral_geometry_surveyed`` is
    False, so the engine's lateral limit and any contact claim are disabled
    rather than fabricated. Where the package has no surface model, ``mu`` comes
    from a declared reference value with synthetic provenance.
    """

    def __init__(
        self,
        package: TrackPackage,
        centreline: CompiledCentreline,
        *,
        reference_mu: float = 1.5,
        checkpoints: tuple[TrackCheckpoint, ...] = (),
        segment_stride_m: float = 25.0,
    ) -> None:
        if not math.isclose(centreline.length_m, centreline.length_m):
            raise ValueError("centreline length is not finite")
        self._package = package
        self._centreline = centreline
        self._reference_mu = float(reference_mu)
        self.id = package.track_id
        self.synthetic = False
        self.geometry_provenance = package.geometry.provenance.value
        self.lateral_geometry_surveyed = package.lateral_geometry_known
        self.timing_line_s_m = Parameter(
            value=float(package.features.start_finish_s_m),
            unit="m",
            source=f"track-package:{package.track_id}",
            verification=VerificationStatus.CALIBRATED_ON_SYNTHETIC
            if package.geometry.provenance is GeometryProvenance.SYNTHETIC_SKETCH
            else VerificationStatus.MEASURED,
            note="Official start/finish from the track package features.",
        )
        self.checkpoints = checkpoints or self._default_checkpoints()
        self.segments = self._segments(segment_stride_m)

    # -- identity ----------------------------------------------------------- #

    @property
    def package(self) -> TrackPackage:
        return self._package

    @property
    def centreline(self) -> CompiledCentreline:
        return self._centreline

    @property
    def length(self) -> float:
        return self._centreline.length_m

    @property
    def config_hash(self) -> str:
        """The package hash: geometry, sources and validation together."""
        return self._package.package_hash or self._package.content_hash()

    @property
    def checkpoint_ids(self) -> tuple[str, ...]:
        return tuple(cp.id for cp in self.checkpoints)

    def checkpoint(self, checkpoint_id: str) -> TrackCheckpoint:
        for candidate in self.checkpoints:
            if candidate.id == checkpoint_id:
                return candidate
        raise KeyError(f"track {self.id} has no checkpoint {checkpoint_id!r}")

    # -- geometry queries --------------------------------------------------- #

    def curvature_at(self, s_m: float) -> float:
        return self._centreline.curvature_at(s_m)

    def grade_at(self, s_m: float) -> float:
        return self._centreline.grade_at(s_m)

    def mu_at(self, s_m: float) -> float:
        value = float(self._centreline._periodic(self._centreline.mu, s_m))
        return self._reference_mu if math.isnan(value) else value

    def width_at(self, s_m: float) -> float:
        return self._centreline.width_at(s_m)

    def curvature_array(self, s_m: np.ndarray) -> np.ndarray:
        return self._centreline.curvature_array(s_m)

    def mu_array(self, s_m: np.ndarray) -> np.ndarray:
        values = self._centreline._periodic(self._centreline.mu, s_m)
        return np.where(np.isnan(values), self._reference_mu, values)

    def width_array(self, s_m: np.ndarray) -> np.ndarray:
        left = self._centreline._periodic(self._centreline.width_left_m, s_m)
        right = self._centreline._periodic(self._centreline.width_right_m, s_m)
        return left + right

    def yaw_at(self, s_m: float) -> float:
        return self._centreline.yaw_at(s_m)

    def position_at(self, s_m: float) -> tuple[float, float, float]:
        return self._centreline.position_at(s_m)

    # -- views for consumers that still read segments ------------------------ #

    def _segments(self, stride_m: float) -> tuple[TrackSegment, ...]:
        """A coarse breakpoint view for the independent ledger.

        The ledger interpolates between segment nodes; sampling the dense arrays
        at ``stride_m`` keeps that cross-check independent of the engine's own
        1 m interpolation while staying faithful to the compiled geometry.
        """
        source = f"track-package:{self._package.track_id}"
        verification = (
            VerificationStatus.SYNTHETIC_ASSUMPTION
            if self._package.geometry.provenance is GeometryProvenance.SYNTHETIC_SKETCH
            else VerificationStatus.MEASURED
        )
        count = max(4, int(self.length // max(stride_m, 1.0)))
        grid = np.linspace(0.0, self.length, count, endpoint=False)
        width_default = 12.0
        out: list[TrackSegment] = []
        for s in grid:
            width = self.width_at(float(s))
            out.append(
                TrackSegment(
                    s_m=Parameter(value=float(s), unit="m", source=source, verification=verification),
                    curvature_inv_m=Parameter(
                        value=self.curvature_at(float(s)),
                        unit="1/m",
                        source=source,
                        verification=verification,
                    ),
                    grade_rad=Parameter(
                        value=self.grade_at(float(s)), unit="rad", source=source, verification=verification
                    ),
                    width_m=Parameter(
                        value=width_default if math.isnan(width) else float(width),
                        unit="m",
                        source=source if not math.isnan(width) else f"{source}:corridor-unknown-placeholder",
                        verification=VerificationStatus.SYNTHETIC_ASSUMPTION
                        if math.isnan(width)
                        else verification,
                        lower_bound=1.0,
                    ),
                    mu=Parameter(
                        value=self.mu_at(float(s)),
                        unit="1",
                        source=f"{source}:reference-mu",
                        verification=VerificationStatus.SYNTHETIC_ASSUMPTION,
                        lower_bound=0.3,
                        upper_bound=2.5,
                    ),
                )
            )
        return tuple(out)

    def _default_checkpoints(self) -> tuple[TrackCheckpoint, ...]:
        """Corners and sector boundaries from the package become checkpoints."""
        source = f"track-package:{self._package.track_id}"
        out: list[TrackCheckpoint] = []
        for corner in self._package.features.corners:
            out.append(
                TrackCheckpoint(
                    id=corner.id,
                    s_m=Parameter(
                        value=float(corner.end_s_m),
                        unit="m",
                        source=source,
                        verification=VerificationStatus.MEASURED,
                    ),
                    description=f"exit of {corner.id}",
                )
            )
        for index, sector in enumerate(self._package.features.sectors, start=1):
            out.append(
                TrackCheckpoint(
                    id=f"sector-{index}-end",
                    s_m=Parameter(
                        value=float(sector.end_s_m) % self.length,
                        unit="m",
                        source=source,
                        verification=VerificationStatus.MEASURED,
                    ),
                    description=f"end of sector {index}",
                )
            )
        # Deduplicate by id, keeping first occurrence.
        seen: set[str] = set()
        unique: list[TrackCheckpoint] = []
        for cp in out:
            if cp.id not in seen:
                seen.add(cp.id)
                unique.append(cp)
        return tuple(unique)


__all__ = [
    "DEFAULT_ENVIRONMENT",
    "CompiledTrackSource",
    "EnvironmentField",
    "StaticEnvironment",
    "TrackSource",
]
