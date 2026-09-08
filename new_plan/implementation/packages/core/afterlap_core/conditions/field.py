"""``TapeEnvironment``: a conditions tape presented through ``EnvironmentField``.

At each engine query the environment interpolates the tape at
``session_time_s``, turns pressure/temperature/humidity into density
(:mod:`atmosphere`), projects the wind onto the car's heading (:mod:`wind`) and
maps rainfall and track temperature to a grip multiplier (:mod:`grip`). The
tape is uniform along the lap: one weather station per circuit is what the
sources provide, so ``s_m`` is accepted and ignored. A spatial field is a
later extension of the same seam.

Heading convention: the engine passes ``TrackGeometry.heading_at(s)``, the
curvature integral anchored at zero at ``s = 0``. That is a heading *relative
to the start direction*. ``heading_offset_rad`` is the absolute ENU yaw at
``s = 0`` (``CompiledCentreline.yaw_at(0.0)``) and is added before projection;
``environment_for`` in :mod:`loader` supplies it. With an offset of zero the
wind is projected as if the start straight pointed east, and ``describes``
says so.

Gusts: when the tape's ``GustSpec`` is enabled, a zero-mean normal perturbation
of the wind speed is drawn from a :class:`~afterlap_core.rng.KeyedRandom`
stream keyed by the tape hash, the seed and the physical time bin, so two
branches of one paired experiment see the same gust at the same instant and
the same seed reproduces the same tape. Off by default.
"""

from __future__ import annotations

from ..rng import KeyedRandom
from .atmosphere import DensityMethod, air_density
from .grip import surface_grip_multiplier
from .tape import ConditionsSample, ConditionsTape
from .wind import headwind_mps as project_headwind


class TapeEnvironment:
    """Implements ``EnvironmentField`` structurally; see the module docstring."""

    def __init__(
        self,
        tape: ConditionsTape,
        *,
        heading_offset_rad: float | None = 0.0,
        rubber_fraction: float = 0.0,
        seed: int = 0,
    ) -> None:
        self.tape = tape
        self.heading_offset_rad = heading_offset_rad
        self.rubber_fraction = float(rubber_fraction)
        self.seed = int(seed)
        self._keyed = (
            KeyedRandom(f"conditions:{tape.content_hash}", self.seed, bin_width_s=tape.gust.bin_width_s)
            if tape.gust.enabled
            else None
        )
        self._last: tuple[float, ConditionsSample] | None = None
        self.density_fallback_queries = 0
        self.last_density_method: DensityMethod | None = None

    def _sample(self, session_time_s: float) -> ConditionsSample:
        if self._last is not None and self._last[0] == session_time_s:
            return self._last[1]
        sample = self.tape.at(session_time_s)
        self._last = (session_time_s, sample)
        return sample

    # -- EnvironmentField ------------------------------------------------------- #

    def air_density_kgpm3(self, s_m: float, session_time_s: float, fallback: float) -> float:
        sample = self._sample(session_time_s)
        result = air_density(
            temperature_k=sample.air_temperature_k,
            pressure_pa=sample.pressure_pa,
            humidity_fraction=sample.humidity_fraction,
            altitude_m=self.tape.altitude_m,
        )
        self.last_density_method = result.method
        if result.value_kgpm3 is None:
            self.density_fallback_queries += 1
            return fallback
        return result.value_kgpm3

    def wind_speed_mps(self, session_time_s: float) -> float | None:
        """Tape wind speed plus the keyed gust when enabled; never negative."""
        sample = self._sample(session_time_s)
        if sample.wind_speed_mps is None:
            return None
        speed = sample.wind_speed_mps
        if self._keyed is not None:
            gust = self.tape.gust
            speed += self._keyed.normal(gust.event_type, session_time_s, scale=gust.sigma_mps)
        return max(0.0, speed)

    def headwind_mps(self, s_m: float, heading_rad: float, session_time_s: float) -> float:
        sample = self._sample(session_time_s)
        speed = self.wind_speed_mps(session_time_s)
        if speed is None or sample.wind_direction_rad is None:
            return 0.0  # no wind information: still air, not an invented breeze
        absolute = heading_rad + (self.heading_offset_rad or 0.0)
        return project_headwind(speed, sample.wind_direction_rad, absolute)

    def grip_multiplier(self, s_m: float, session_time_s: float) -> float:
        sample = self._sample(session_time_s)
        rain = 1.0 if sample.rainfall else 0.0
        return surface_grip_multiplier(
            rain_intensity=rain,
            track_temperature_k=sample.track_temperature_k,
            rubber_fraction=self.rubber_fraction,
        )

    @property
    def describes(self) -> str:
        heading = (
            "heading=relative-only(no absolute yaw)"
            if self.heading_offset_rad is None
            else f"heading_offset={self.heading_offset_rad:.4f}rad"
        )
        gust = f"gust=on(sigma={self.tape.gust.sigma_mps}m/s,seed={self.seed})" if self._keyed else "gust=off"
        return (
            f"conditions:{self.tape.tape_id} {self.tape.content_hash[:19]} "
            f"source={self.tape.provenance.source_kind}:{self.tape.provenance.label} "
            f"{gust} {heading} rubber={self.rubber_fraction:.2f}"
        )


__all__ = ["TapeEnvironment"]
