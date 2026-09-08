"""Wind sign conventions: the headwind must reverse as the heading rotates."""

from __future__ import annotations

import math

import pytest

from afterlap_core.conditions.wind import (
    crosswind_mps,
    headwind_mps,
    interpolate_direction_rad,
    meteorological_direction_rad,
    wind_vector_enu,
)

EAST, NORTH, WEST, SOUTH = 0.0, math.pi / 2.0, math.pi, -math.pi / 2.0


def test_a_north_wind_blows_south():
    u, v = wind_vector_enu(10.0, meteorological_direction_rad(0.0))
    assert u == pytest.approx(0.0, abs=1e-12)
    assert v == pytest.approx(-10.0)


def test_headwind_is_positive_when_wind_opposes_heading():

    assert headwind_mps(8.0, meteorological_direction_rad(90.0), EAST) == pytest.approx(8.0)

    assert headwind_mps(8.0, meteorological_direction_rad(0.0), NORTH) == pytest.approx(8.0)

    assert headwind_mps(8.0, meteorological_direction_rad(270.0), EAST) == pytest.approx(-8.0)


@pytest.mark.parametrize("direction_deg", [0.0, 37.0, 90.0, 181.0, 263.0, 359.0])
@pytest.mark.parametrize("heading", [EAST, NORTH, 0.7, 2.9, -1.3])
def test_headwind_is_antisymmetric_under_heading_reversal(direction_deg, heading):
    direction = meteorological_direction_rad(direction_deg)
    forward = headwind_mps(6.0, direction, heading)
    backward = headwind_mps(6.0, direction, heading + math.pi)
    assert forward == pytest.approx(-backward, abs=1e-12)


def test_headwind_and_crosswind_recover_the_speed():
    direction = meteorological_direction_rad(123.0)
    for heading in (0.1, 1.0, 2.5, 4.0):
        h = headwind_mps(7.0, direction, heading)
        c = crosswind_mps(7.0, direction, heading)
        assert math.hypot(h, c) == pytest.approx(7.0)


def test_crosswind_sign_is_towards_the_left():

    assert crosswind_mps(5.0, meteorological_direction_rad(0.0), EAST) == pytest.approx(-5.0)

    assert crosswind_mps(5.0, meteorological_direction_rad(180.0), EAST) == pytest.approx(5.0)


def test_pure_crosswind_has_no_headwind():
    assert headwind_mps(5.0, meteorological_direction_rad(0.0), EAST) == pytest.approx(0.0, abs=1e-12)


def test_direction_interpolation_crosses_the_north_seam():
    a = meteorological_direction_rad(350.0)
    b = meteorological_direction_rad(10.0)
    mid = interpolate_direction_rad(a, b, 0.5)
    assert mid == pytest.approx(0.0, abs=1e-9) or mid == pytest.approx(2.0 * math.pi, abs=1e-9)


def test_negative_speed_is_refused():
    with pytest.raises(ValueError):
        wind_vector_enu(-1.0, 0.0)
