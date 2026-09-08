"""Fixtures for the conditions suite. No network; every record here is synthetic.

The engine tests drive the shipped ``two-straight-counterattack`` scenario on
its synthetic sketch track through ``Simulator.reset(..., environment=)``, the
same pattern as ``tests/tracks/test_compiled_source_drives_simulator.py``, so
no package builder needs copying across test packages.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from afterlap_core.conditions.tape import ConditionsProvenance, ConditionsSample, ConditionsTape
from afterlap_core.paths import Paths

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_WEATHER = FIXTURES / "openf1_weather_synthetic.json"


@pytest.fixture(scope="session")
def synthetic_openf1_records() -> dict[str, list[dict[str, Any]]]:
    payload = json.loads(FIXTURE_WEATHER.read_text(encoding="utf-8"))
    assert "SYNTHETIC" in payload.pop("_label")
    return payload


def synthetic_provenance(label: str = "unit-test constants") -> ConditionsProvenance:
    return ConditionsProvenance(
        source_kind="synthetic", label=label, permission="synthetic fixture; no external rights involved"
    )


def simple_tape(
    *,
    tape_id: str = "unit-tape",
    times: tuple[float, ...] = (0.0, 60.0, 120.0),
    air_k: tuple[float, ...] = (293.15, 294.15, 295.15),
    pressure_pa: float | None = 101000.0,
    humidity: float | None = 0.5,
    wind_speed: float | None = 5.0,
    wind_dir_rad: tuple[float, ...] | None = (0.0, 0.0, 0.0),
    rainfall: tuple[bool, ...] | None = (False, False, False),
    track_k: float | None = 305.0,
    altitude_m: float | None = None,
) -> ConditionsTape:
    samples = [
        ConditionsSample(
            session_time_s=t,
            air_temperature_k=air_k[i],
            track_temperature_k=track_k,
            pressure_pa=pressure_pa,
            humidity_fraction=humidity,
            wind_speed_mps=wind_speed,
            wind_direction_rad=None if wind_dir_rad is None else wind_dir_rad[i],
            rainfall=None if rainfall is None else rainfall[i],
        )
        for i, t in enumerate(times)
    ]
    return ConditionsTape(
        tape_id,
        samples,
        synthetic_provenance(),
        altitude_m=altitude_m,
        altitude_source=None if altitude_m is None else "unit test constant",
    )


def scratch_paths(root: Path, *, with_conditions_configs: bool = True) -> Paths:
    """Temporary configs/ and artifacts/ trees; cars and scenarios are not needed here."""
    artifacts = root / "artifacts"
    configs = root / "configs"
    if with_conditions_configs:
        (configs / "conditions").mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    return Paths(
        root=root,
        configs=configs,
        artifacts=artifacts,
        trajectories=artifacts / "trajectories",
        models=artifacts / "models",
        reports=artifacts / "reports",
        exports=artifacts / "exports",
        spool=artifacts / "spool",
    )
