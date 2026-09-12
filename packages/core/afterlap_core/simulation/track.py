from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from ..timebase import wrap_s

if TYPE_CHECKING:
    from .track_source import TrackSource

_INTEGRATION_STEP_M = 0.5


@dataclass(frozen=True, slots=True)
class CarFootprint:
    x_m: float
    y_m: float
    heading_rad: float
    length_m: float
    width_m: float
    car_id: str = ""

    def corners(self) -> tuple[tuple[float, float], ...]:

        cos_h = math.cos(self.heading_rad)
        sin_h = math.sin(self.heading_rad)
        half_l = 0.5 * self.length_m
        half_w = 0.5 * self.width_m
        offsets = ((half_l, half_w), (-half_l, half_w), (-half_l, -half_w), (half_l, -half_w))
        return tuple(
            (self.x_m + dx * cos_h - dy * sin_h, self.y_m + dx * sin_h + dy * cos_h) for dx, dy in offsets
        )

    @property
    def bounding_radius_m(self) -> float:
        return 0.5 * math.hypot(self.length_m, self.width_m)


def _project(corners: tuple[tuple[float, float], ...], axis: tuple[float, float]) -> tuple[float, float]:
    values = [corner[0] * axis[0] + corner[1] * axis[1] for corner in corners]
    return min(values), max(values)


def overlap(a: CarFootprint, b: CarFootprint) -> bool:

    gap = math.hypot(a.x_m - b.x_m, a.y_m - b.y_m)
    if gap > a.bounding_radius_m + b.bounding_radius_m:
        return False
    corners_a = a.corners()
    corners_b = b.corners()
    axes = (
        (math.cos(a.heading_rad), math.sin(a.heading_rad)),
        (-math.sin(a.heading_rad), math.cos(a.heading_rad)),
        (math.cos(b.heading_rad), math.sin(b.heading_rad)),
        (-math.sin(b.heading_rad), math.cos(b.heading_rad)),
    )
    for axis in axes:
        min_a, max_a = _project(corners_a, axis)
        min_b, max_b = _project(corners_b, axis)
        if max_a < min_b or max_b < min_a:
            return False
    return True


def separation_distance(a: CarFootprint, b: CarFootprint) -> float:

    return math.hypot(a.x_m - b.x_m, a.y_m - b.y_m)


class TrackGeometry:
    def __init__(self, track: TrackSource) -> None:
        self.track = track
        self.length_m = track.length
        count = max(2, round(self.length_m / _INTEGRATION_STEP_M) + 1)
        self._s_grid = np.linspace(0.0, self.length_m, count, dtype=np.float64)
        curvature = track.curvature_array(self._s_grid)
        step = np.diff(self._s_grid)
        increments = 0.5 * (curvature[:-1] + curvature[1:]) * step
        self._theta = np.concatenate(([0.0], np.cumsum(increments)))
        cos_t = np.cos(self._theta)
        sin_t = np.sin(self._theta)
        self._x = np.concatenate(([0.0], np.cumsum(0.5 * (cos_t[:-1] + cos_t[1:]) * step)))
        self._y = np.concatenate(([0.0], np.cumsum(0.5 * (sin_t[:-1] + sin_t[1:]) * step)))

    def wrap(self, s_m: float) -> float:
        return wrap_s(s_m, self.length_m)

    def signed_arc_gap(self, s_from: float, s_to: float) -> float:

        raw = (s_to - s_from) % self.length_m
        return raw - self.length_m if raw > 0.5 * self.length_m else raw

    def heading_at(self, s_m: float) -> float:

        return float(np.interp(self.wrap(s_m), self._s_grid, self._theta))

    def _theta_unwrapped(self, s_m: np.ndarray | float) -> np.ndarray:

        s = np.asarray(s_m, dtype=np.float64)
        laps = np.floor(s / self.length_m)
        remainder = s - laps * self.length_m
        return laps * self._theta[-1] + np.interp(remainder, self._s_grid, self._theta)

    def heading_change(self, s_from: float, s_to: float) -> float:

        anchor = self.wrap(s_from)
        delta = self.signed_arc_gap(s_from, s_to)
        return float(self._theta_unwrapped(anchor + delta) - self._theta_unwrapped(anchor))

    def centreline_point(self, s_m: float) -> tuple[float, float, float]:

        s = self.wrap(s_m)
        return (
            float(np.interp(s, self._s_grid, self._x)),
            float(np.interp(s, self._s_grid, self._y)),
            float(np.interp(s, self._s_grid, self._theta)),
        )

    @property
    def closure_residual_m(self) -> float:

        return float(math.hypot(self._x[-1] - self._x[0], self._y[-1] - self._y[0]))

    @property
    def closure_heading_residual_rad(self) -> float:

        turn = 2.0 * math.pi
        total = float(self._theta[-1])
        return total - turn * round(total / turn)

    def local_position(
        self, reference_s_m: float, s_m: float, lateral_d_m: float, heading_error_rad: float
    ) -> tuple[float, float, float]:

        anchor = self.wrap(reference_s_m)
        along = self.signed_arc_gap(reference_s_m, s_m)
        theta_anchor = float(self._theta_unwrapped(anchor))
        heading = float(self._theta_unwrapped(anchor + along)) - theta_anchor + heading_error_rad
        if abs(along) < 1e-12:
            return 0.0, lateral_d_m, heading
        samples = np.linspace(0.0, along, 17)
        headings = self._theta_unwrapped(anchor + samples) - theta_anchor
        x = float(np.trapezoid(np.cos(headings), samples))
        y = float(np.trapezoid(np.sin(headings), samples))
        normal_heading = headings[-1] + 0.5 * math.pi
        x += lateral_d_m * math.cos(normal_heading)
        y += lateral_d_m * math.sin(normal_heading)
        return x, y, heading

    def footprint(
        self,
        reference_s_m: float,
        s_m: float,
        lateral_d_m: float,
        heading_error_rad: float,
        length_m: float,
        width_m: float,
        car_id: str = "",
    ) -> CarFootprint:
        x, y, heading = self.local_position(reference_s_m, s_m, lateral_d_m, heading_error_rad)
        return CarFootprint(
            x_m=x,
            y_m=y,
            heading_rad=heading,
            length_m=length_m,
            width_m=width_m,
            car_id=car_id,
        )

    def lateral_limit(self, s_m: float, car_width_m: float) -> float:

        width = self.track.width_at(s_m)
        if math.isnan(width):
            return 0.0
        return max(0.0, 0.5 * (width - car_width_m))


_GEOMETRY_CACHE: dict[int, tuple[TrackSource, TrackGeometry]] = {}


def geometry_for(track: TrackSource) -> TrackGeometry:

    entry = _GEOMETRY_CACHE.get(id(track))
    if entry is not None and entry[0] is track:
        return entry[1]
    if len(_GEOMETRY_CACHE) > 16:
        _GEOMETRY_CACHE.clear()
    geometry = TrackGeometry(track)
    _GEOMETRY_CACHE[id(track)] = (track, geometry)
    return geometry


def footprints_overlap(
    geometry: TrackGeometry,
    a_s_m: float,
    a_d_m: float,
    a_heading_rad: float,
    a_length_m: float,
    a_width_m: float,
    b_s_m: float,
    b_d_m: float,
    b_heading_rad: float,
    b_length_m: float,
    b_width_m: float,
) -> bool:

    along = abs(geometry.signed_arc_gap(a_s_m, b_s_m))
    broad_radius = 0.5 * (a_length_m + b_length_m) + 0.5 * (a_width_m + b_width_m)
    if along > broad_radius:
        return False
    first = geometry.footprint(a_s_m, a_s_m, a_d_m, a_heading_rad, a_length_m, a_width_m, "a")
    second = geometry.footprint(a_s_m, b_s_m, b_d_m, b_heading_rad, b_length_m, b_width_m, "b")
    return overlap(first, second)


__all__ = [
    "CarFootprint",
    "TrackGeometry",
    "footprints_overlap",
    "geometry_for",
    "overlap",
    "separation_distance",
]
