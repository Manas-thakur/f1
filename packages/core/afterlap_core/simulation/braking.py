from __future__ import annotations

import math

import numpy as np
from numba import njit


@njit(cache=True, nogil=True)
def braking_speed(
    curvatures: np.ndarray,
    grips: np.ndarray,
    offsets: np.ndarray,
    factor: float,
    braking_fraction: float,
    brake_decel: float,
) -> float:
    limits = np.empty_like(curvatures)
    for i in range(len(curvatures)):
        denominator = curvatures[i] - grips[i] * factor
        limits[i] = min(math.sqrt(grips[i] * 9.80665 / denominator), 130.0) if denominator > 0 else 130.0
    speed = limits[-1]
    for index in range(len(limits) - 2, -1, -1):
        distance = offsets[index + 1] - offsets[index]
        envelope = grips[index + 1] * (9.80665 + factor * speed * speed)
        lateral = speed * speed * curvatures[index + 1]
        spare = envelope * envelope - lateral * lateral
        exit_decel = 0.97 * min(braking_fraction * math.sqrt(spare), brake_decel) if spare > 0 else 0.0
        predicted = math.sqrt(speed * speed + 2.0 * exit_decel * distance)
        envelope = grips[index] * (9.80665 + factor * predicted * predicted)
        lateral = predicted * predicted * curvatures[index]
        spare = envelope * envelope - lateral * lateral
        entry_decel = 0.97 * min(braking_fraction * math.sqrt(spare), brake_decel) if spare > 0 else 0.0
        decel = min(exit_decel, entry_decel)
        speed = min(limits[index], math.sqrt(speed * speed + 2.0 * decel * distance))
    return float(speed)


@njit(cache=True, nogil=True)
def sample_track(table: np.ndarray, nodes: np.ndarray, positions: np.ndarray, length: float) -> np.ndarray:
    result = np.empty_like(positions)
    for i in range(positions.size):
        s = positions.flat[i] % length
        index = min(max(np.searchsorted(nodes, s, side="right") - 1, 0), len(nodes) - 2)
        span = nodes[index + 1] - nodes[index]
        t = (s - nodes[index]) / span if span > 0.0 else 0.0
        weight = t * t * (3.0 - 2.0 * t)
        result.flat[i] = table[index] + weight * (table[index + 1] - table[index])
    return result


@njit(cache=True, nogil=True)
def track_braking_speed(
    curvature: np.ndarray,
    mu: np.ndarray,
    nodes: np.ndarray,
    length: float,
    positions: np.ndarray,
    grip_multipliers: np.ndarray,
    grip_share: float,
    offsets: np.ndarray,
    factor: float,
    braking_fraction: float,
    brake_decel: float,
) -> float:
    curvatures = np.empty_like(positions)
    grips = np.empty_like(positions)
    for i in range(len(positions)):
        s = positions[i] % length
        index = min(max(np.searchsorted(nodes, s, side="right") - 1, 0), len(nodes) - 2)
        span = nodes[index + 1] - nodes[index]
        t = (s - nodes[index]) / span if span > 0 else 0.0
        weight = t * t * (3.0 - 2.0 * t)
        curvatures[i] = abs(curvature[index] + weight * (curvature[index + 1] - curvature[index]))
        grips[i] = (mu[index] + weight * (mu[index + 1] - mu[index])) * grip_share * grip_multipliers[i]
    return float(braking_speed(curvatures, grips, offsets, factor, braking_fraction, brake_decel))
