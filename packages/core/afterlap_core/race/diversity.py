from __future__ import annotations

from typing import Any

import numpy as np

from ..rng import StreamRegistry
from .settings import RaceSettings

EPISODE_SEED_LIMIT = 2**31 - 1


def next_episode_seed(rng: np.random.Generator, seed: int | None) -> int:
    if seed is not None:
        return int(seed)
    return int(rng.integers(0, EPISODE_SEED_LIMIT))


def episode_race_settings(settings: RaceSettings, episode_seed: int) -> RaceSettings:
    updates: dict[str, Any] = {"seed": episode_seed}
    diversity = settings.training_diversity
    if diversity.enabled:
        rng = StreamRegistry(episode_seed).stream("training-conditions")
        wetness = min(
            1.0,
            max(0.0, settings.wetness + float(rng.uniform(-diversity.wetness_span, diversity.wetness_span))),
        )
        temperature = min(
            323.15,
            max(
                273.15,
                settings.temperature_k
                + float(rng.uniform(-diversity.temperature_span_k, diversity.temperature_span_k)),
            ),
        )
        wind = min(
            20.0,
            max(
                -20.0,
                settings.wind_mps + float(rng.uniform(-diversity.wind_span_mps, diversity.wind_span_mps)),
            ),
        )
        updates.update(
            {
                "wetness": wetness,
                "temperature_k": temperature,
                "wind_mps": wind,
                "weather": "rainy" if wetness >= 0.35 else settings.weather,
            }
        )
        if diversity.circuits:
            updates["circuit"] = str(diversity.circuits[int(rng.integers(0, len(diversity.circuits)))])
    return settings.model_copy(update=updates)


def apply_command_diversity(
    settings: RaceSettings,
    requested: bool | None,
    *,
    default_enabled: bool,
) -> RaceSettings:
    if requested is None and not default_enabled:
        return settings
    enabled = default_enabled if requested is None else requested
    return settings.model_copy(
        update={"training_diversity": settings.training_diversity.model_copy(update={"enabled": enabled})}
    )
