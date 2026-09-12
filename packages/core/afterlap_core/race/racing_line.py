from __future__ import annotations

import math

import numpy as np

from ..rng import StreamRegistry
from ..simulation.track_source import TrackSource
from .settings import RacingLineSettings


def _smooth_periodic(values: np.ndarray, distance_m: float, spacing_m: float) -> np.ndarray:
    radius = max(1, math.ceil(3 * distance_m / spacing_m))
    offsets = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (offsets * spacing_m / distance_m) ** 2)
    kernel /= kernel.sum()
    return np.convolve(np.pad(values, (radius, radius), mode="wrap"), kernel, mode="valid")


class RacingLine:
    def __init__(
        self,
        track: TrackSource,
        settings: RacingLineSettings,
        streams: StreamRegistry,
        car_id: str,
        car_width_m: float,
        preferred_line_m: float,
    ) -> None:
        self.length_m = track.length
        count = max(256, math.ceil(track.length / 4))
        spacing = track.length / count
        positions = np.arange(count, dtype=np.float64) * spacing
        limits = np.maximum(0, 0.5 * (track.width_array(positions) - car_width_m) - 0.25)
        if not settings.enabled:
            targets = np.full(count, preferred_line_m, dtype=np.float64)
        else:
            curvature = _smooth_periodic(track.curvature_array(positions), settings.smoothing_m, spacing)
            magnitude = np.abs(curvature)
            active = magnitude[magnitude > 1e-6]
            reference = max(1e-4, float(np.percentile(active, 65)) if active.size else 1e-4)
            inside = np.tanh(curvature / reference)
            corner = np.tanh(magnitude / reference)
            shift = max(1, round(settings.lookahead_m / spacing))
            future = np.roll(inside * corner, -shift)
            past = np.roll(inside * corner, shift)
            nearby = np.where(np.abs(future) >= np.abs(past), future, past)
            shape = inside * corner - nearby * (1 - corner) * 0.82
            shape = np.clip(_smooth_periodic(shape, max(5, settings.smoothing_m * 0.65), spacing), -1, 1)
            rng = streams.stream(f"racing_line:{car_id}")
            phase = float(rng.uniform(0, 2 * math.pi, size=1)[0])
            harmonics = np.zeros(count, dtype=np.float64)
            lap_phase = positions / track.length * 2 * math.pi
            for frequency in range(2, 8):
                amplitude = float(rng.normal()) / frequency
                phase += float(rng.uniform(0.7, 2.3, size=1)[0])
                harmonics += amplitude * np.sin(frequency * lap_phase + phase)
            peak = float(np.max(np.abs(harmonics)))
            if peak > 0:
                harmonics /= peak
            amplitude = float(rng.uniform(0.82, 1.0, size=1)[0])
            targets = (
                settings.corner_strength * amplitude * limits * shape
                + preferred_line_m * (1 - corner)
                + settings.randomness * settings.wander_m * harmonics
            )
            targets = _smooth_periodic(targets, settings.smoothing_m, spacing)
        clipped = np.clip(targets, -limits, limits)
        self._positions = np.append(positions, track.length)
        self._targets = np.append(clipped, clipped[0])

    def target_at(self, progress_m: float) -> float:
        return float(np.interp(progress_m % self.length_m, self._positions, self._targets))

    def preview(self, count: int = 128) -> tuple[float, ...]:
        positions = np.linspace(0, self.length_m, count, endpoint=False)
        return tuple(self.target_at(float(position)) for position in positions)

    def __deepcopy__(self, memo: dict[int, object]) -> RacingLine:
        del memo
        return self
