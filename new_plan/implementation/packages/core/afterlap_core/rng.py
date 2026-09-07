"""Keyed random streams for reproducible branching.

Exogenous draws are keyed by ``(scenario, seed, event_type, physical_time_bin)``
rather than by a mutable call counter. Two branches that make different
decisions therefore still see the *same* wind, grip and sensor noise, which is
what makes a paired comparison meaningful.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import Any

import numpy as np

_MASK64 = (1 << 64) - 1


def derive_seed(*parts: Any) -> int:
    """Derive a stable 64-bit seed from arbitrary key parts.

    Stable across processes and platforms because it hashes the textual key
    rather than relying on Python's salted ``hash()``.
    """
    payload = "\x1f".join(repr(p) for p in parts).encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return struct.unpack("<Q", digest)[0] & _MASK64


@dataclass(frozen=True, slots=True)
class StreamKey:
    """Identity of one exogenous disturbance draw."""

    scenario: str
    seed: int
    event_type: str
    time_bin: int

    def as_seed(self) -> int:
        return derive_seed(self.scenario, self.seed, self.event_type, self.time_bin)


class KeyedRandom:
    """Exogenous disturbance source shared by paired experiment branches.

    ``bin_width_s`` quantises physical time so that two branches which reach the
    same physical instant draw the same disturbance even if they arrived there
    after a different number of internal calls.
    """

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
        return float(self.generator(event_type, physical_time_s).normal(0.0, scale))

    def uniform(
        self, event_type: str, physical_time_s: float, *, low: float = 0.0, high: float = 1.0
    ) -> float:
        return float(self.generator(event_type, physical_time_s).uniform(low, high))


class StreamRegistry:
    """Named independent generators whose state is captured in a snapshot.

    Each name (sensor noise, driver response, opponent perturbation) advances
    independently, so adding a call in one subsystem cannot shift another's
    sequence.
    """

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
        """Serialisable state of every stream, for snapshot/restore."""
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
