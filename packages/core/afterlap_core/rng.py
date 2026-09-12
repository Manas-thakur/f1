from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

_MASK64 = (1 << 64) - 1


def derive_seed(*parts: Any) -> int:

    payload = "\x1f".join(repr(p) for p in parts).encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return struct.unpack("<Q", digest)[0] & _MASK64


@dataclass(frozen=True, slots=True)
class StreamKey:
    scenario: str
    seed: int
    event_type: str
    time_bin: int

    def as_seed(self) -> int:
        return derive_seed(self.scenario, self.seed, self.event_type, self.time_bin)


@lru_cache(maxsize=8192)
def _normal_sample(key: StreamKey, scale: float) -> float:
    return float(np.random.default_rng(key.as_seed()).normal(0.0, scale))


class KeyedRandom:
    def __init__(self, scenario: str, seed: int, *, bin_width_s: float = 0.5) -> None:
        if bin_width_s <= 0.0:
            raise ValueError("bin width must be positive")
        self.scenario = scenario
        self.seed = seed
        self.bin_width_s = bin_width_s

    def key(self, event_type: str, physical_time_s: float) -> StreamKey:
        return StreamKey(
            scenario=self.scenario,
            seed=self.seed,
            event_type=event_type,
            time_bin=int(physical_time_s // self.bin_width_s),
        )

    def generator(self, event_type: str, physical_time_s: float) -> np.random.Generator:
        return np.random.default_rng(self.key(event_type, physical_time_s).as_seed())

    def normal(self, event_type: str, physical_time_s: float, *, scale: float = 1.0) -> float:
        return _normal_sample(self.key(event_type, physical_time_s), scale)

    def uniform(
        self, event_type: str, physical_time_s: float, *, low: float = 0.0, high: float = 1.0
    ) -> float:
        return float(self.generator(event_type, physical_time_s).uniform(low, high))


class StreamRegistry:
    def __init__(self, root_seed: int, names: tuple[str, ...] = ()) -> None:
        self.root_seed = root_seed
        self._generators: dict[str, np.random.Generator] = {}
        for name in names:
            self.stream(name)

    def stream(self, name: str) -> np.random.Generator:
        if name not in self._generators:
            self._generators[name] = np.random.default_rng(derive_seed(self.root_seed, name))
        return self._generators[name]

    def capture(self) -> dict[str, Any]:

        return {
            "root_seed": self.root_seed,
            "streams": {
                name: generator.bit_generator.state for name, generator in sorted(self._generators.items())
            },
        }

    def restore(self, state: dict[str, Any]) -> None:
        self.root_seed = state["root_seed"]
        self._generators = {}
        for name, bit_state in state["streams"].items():
            generator = np.random.default_rng()
            generator.bit_generator.state = bit_state
            self._generators[name] = generator

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._generators))


__all__ = ["KeyedRandom", "StreamKey", "StreamRegistry", "derive_seed"]
