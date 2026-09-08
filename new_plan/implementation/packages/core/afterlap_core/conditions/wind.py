"""Wind vectors and their projection onto the direction of travel.

Conventions (documented here, tested in ``tests/conditions/test_wind.py``)
--------------------------------------------------------------------------
* The track frame is local ENU: ``x`` east, ``y`` north. A heading is the
  direction of travel measured **counter-clockwise from +x (east)** in
  radians, the mathematical convention used by ``CompiledCentreline.yaw_rad``.
* A meteorological wind direction is the bearing the wind blows **from**,
  measured **clockwise from north** in degrees (OpenF1 ``wind_direction``,
  WMO convention). A 0 deg "north wind" blows towards the south.
* ``headwind_mps`` is the wind component **opposing** travel: positive slows
  the car, negative is a tailwind. This is the sign the engine adds to ground
  speed to obtain air speed.
* ``crosswind_mps`` is positive when the wind pushes the car towards its left.

Reversing the heading negates the headwind exactly (antisymmetry), which is
the property a closed circuit needs: a single global sign is wrong.
"""

from __future__ import annotations

import math


def meteorological_direction_rad(direction_from_deg: float) -> float:
    """Degrees clockwise from north (blowing from) to radians, same convention."""
    return math.radians(direction_from_deg % 360.0)


def wind_vector_enu(speed_mps: float, direction_from_rad: float) -> tuple[float, float]:
    """East and north components of the wind velocity.

    The wind blows *towards* ``direction_from + pi``. A bearing ``beta``
    (clockwise from north) maps to the mathematical angle ``pi/2 - beta``.
    """
    if speed_mps < 0.0:
        raise ValueError("wind speed is a magnitude and cannot be negative")
    phi = math.pi / 2.0 - (direction_from_rad + math.pi)
    return speed_mps * math.cos(phi), speed_mps * math.sin(phi)


def headwind_mps(speed_mps: float, direction_from_rad: float, heading_rad: float) -> float:
    """Component of the wind opposing travel at ``heading_rad``; positive slows the car."""
    u_east, v_north = wind_vector_enu(speed_mps, direction_from_rad)
    along_track = u_east * math.cos(heading_rad) + v_north * math.sin(heading_rad)
    return -along_track


def crosswind_mps(speed_mps: float, direction_from_rad: float, heading_rad: float) -> float:
    """Component of the wind across travel; positive pushes towards the car's left."""
    u_east, v_north = wind_vector_enu(speed_mps, direction_from_rad)
    left_x, left_y = -math.sin(heading_rad), math.cos(heading_rad)
    return u_east * left_x + v_north * left_y


def interpolate_direction_rad(direction_a_rad: float, direction_b_rad: float, weight_b: float) -> float:
    """Interpolate two bearings along the shorter arc; safe across the 0/2pi seam."""
    if not (0.0 <= weight_b <= 1.0):
        raise ValueError("interpolation weight must lie in [0, 1]")
    x = (1.0 - weight_b) * math.cos(direction_a_rad) + weight_b * math.cos(direction_b_rad)
    y = (1.0 - weight_b) * math.sin(direction_a_rad) + weight_b * math.sin(direction_b_rad)
    if math.hypot(x, y) < 1e-12:
        return direction_a_rad % (2.0 * math.pi)
    return math.atan2(y, x) % (2.0 * math.pi)


__all__ = [
    "crosswind_mps",
    "headwind_mps",
    "interpolate_direction_rad",
    "meteorological_direction_rad",
    "wind_vector_enu",
]
