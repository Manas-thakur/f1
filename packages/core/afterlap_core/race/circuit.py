from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import numpy as np

from ..config import Parameter
from ..paths import Paths
from ..simulation.config import TrackCheckpoint, TrackConfig, TrackSegment


def assumed(value: float, unit: str) -> Parameter:
    return Parameter(value=value, unit=unit, source="synthetic:race-lab-v1")


@lru_cache(maxsize=1)
def lap_presets() -> dict[str, dict[str, Any]]:
    path = Paths.default().configs / "race-lap-presets.json"
    return json.loads(path.read_text(encoding="utf-8"))


def default_laps(circuit_id: str) -> int:
    try:
        return int(lap_presets()[circuit_id]["default_laps"])
    except KeyError as exc:
        raise ValueError(f"unknown circuit: {circuit_id}") from exc


def catalogue() -> list[dict[str, Any]]:
    presets = lap_presets()
    entries = []
    for path in sorted((Paths.default().configs / "race-circuits").glob("*.json")):
        metadata = {
            key: value
            for key, value in json.loads(path.read_text(encoding="utf-8")).items()
            if key != "points"
        }
        preset = presets.get(metadata["id"])
        if preset is None:
            raise ValueError(f"circuit has no lap preset: {metadata['id']}")
        entries.append({**metadata, "lap_presets": [{"id": "grand-prix", **preset}]})
    if set(presets) != {entry["id"] for entry in entries}:
        raise ValueError("lap presets must exactly match the circuit catalogue")
    return entries


@lru_cache(maxsize=24)
def circuit(circuit_id: str, wetness: float = 0.0) -> tuple[TrackConfig, dict[str, Any]]:
    if circuit_id not in {entry["id"] for entry in catalogue()}:
        raise ValueError(f"unknown circuit: {circuit_id}")
    path = Paths.default().configs / "race-circuits" / f"{circuit_id}.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    points = np.asarray(metadata["points"], dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise ValueError("circuit needs finite two-dimensional coordinates")
    points = points[np.r_[True, np.linalg.norm(np.diff(points, axis=0), axis=1) > 1e-6]]
    if np.linalg.norm(points[-1] - points[0]) < 1e-6:
        points = points[:-1]
    closed = np.vstack((points, points[0]))
    distance = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))]
    length = float(metadata["length_m"])
    scale = length / distance[-1]
    distance *= scale
    closed *= scale
    count = max(100, round(length / 5))
    s = np.linspace(0, length, count, endpoint=False)
    xy = np.column_stack([np.interp(s, distance, closed[:, axis]) for axis in range(2)])
    xy = (np.roll(xy, 1, axis=0) + 2 * xy + np.roll(xy, -1, axis=0)) / 4
    tangent = np.roll(xy, -1, axis=0) - np.roll(xy, 1, axis=0)
    heading = np.arctan2(tangent[:, 1], tangent[:, 0])
    turn = (np.roll(heading, -1) - np.roll(heading, 1) + np.pi) % (2 * np.pi) - np.pi
    curvature = turn / (2 * length / count)
    checkpoints = tuple(TrackCheckpoint(id=f"sector-{i}", s_m=assumed(length * i / 3, "m")) for i in (1, 2))
    track = TrackConfig(
        id=f"race-{circuit_id}",
        length_m=assumed(length, "m"),
        timing_line_s_m=assumed(0, "m"),
        geometry_provenance="scaled_visual_artwork; synthetic 12 m corridor and flat elevation",
        checkpoints=checkpoints,
        segments=tuple(
            TrackSegment(
                s_m=assumed(float(position), "m"),
                curvature_inv_m=assumed(float(k), "1/m"),
                grade_rad=assumed(0, "rad"),
                width_m=assumed(12, "m"),
                mu=assumed(1.65 * (1 - 0.45 * wetness), "1"),
            )
            for position, k in zip(s, curvature, strict=True)
        ),
    )
    return track, {**metadata, "points": xy.tolist(), "sample_spacing_m": length / count}
