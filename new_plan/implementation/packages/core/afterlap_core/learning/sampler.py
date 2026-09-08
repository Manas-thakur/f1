"""Scenario sampling across real circuits (A16-7).

``RL_TRACK_GENERALISATION.md``: sample a circuit first, then a coherent
condition regime, then car/opponent/human uncertainties; balance by decision
opportunities rather than lap count; sample own energy from a declared synthetic
distribution and label the run ``real_circuit_synthetic_energy``.

:class:`ScenarioSampler` does exactly that order. Every draw is a pure function
of ``(split_hash, group, sampler seed, draw index)`` through
:class:`~afterlap_core.rng.KeyedRandom`, so a sample stream can be reproduced
and audited without replaying the stream that produced it. A draw is *data*
(:class:`ScenarioDraw`); turning it into a runnable :class:`ScenarioBundle` is a
separate step that goes through ``load_track`` and therefore refuses a package
below ``geometry_validated`` instead of defaulting.

Circuits the split lists but whose packages cannot be simulated are skipped
*before* any draw is made, with the loader's own reason recorded on
:attr:`ScenarioSampler.pending` and in the sampler manifest. Skipping is not
substitution: the sampler never swaps in a different circuit, and a group with
no usable circuit refuses to be constructed at all.

:func:`resolve_bundle` is the load-bundle-style resolution the Gym environment
uses: the scenario document's ``conditions_id`` becomes a bound
``TapeEnvironment`` and its content hash is recorded on the bundle.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..config import Parameter, VerificationStatus
from ..paths import Paths
from ..rng import KeyedRandom
from ..simulation.config import (
    ScenarioBundle,
    ScenarioConfig,
    load_scenario,
)
from ..simulation.config import resolve_bundle as _resolve_bundle
from .circuits import (
    REQUIRED_READINESS,
    CircuitReadiness,
    CircuitSplit,
    GroupAvailability,
    group_availability,
    load_circuit_split,
)

__all__ = [
    "ScenarioDraw",
    "ScenarioSampler",
    "ScenarioUnavailable",
    "resolve_bundle",
]


class ScenarioUnavailable(LookupError):
    """A draw cannot be turned into a bundle honestly from what is declared on disk."""


@dataclass(frozen=True, slots=True)
class ScenarioDraw:
    """One sampled episode specification. Data only; nothing here has been loaded."""

    index: int
    group: str
    track_id: str
    conditions_id: str | None
    energy_j: float
    energy_label: str
    seed: int
    scenario_id: str | None
    split_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "group": self.group,
            "track_id": self.track_id,
            "conditions_id": self.conditions_id,
            "energy_j": self.energy_j,
            "energy_label": self.energy_label,
            "seed": self.seed,
            "scenario_id": self.scenario_id,
            "split_hash": self.split_hash,
        }


def resolve_bundle(
    scenario: str | ScenarioConfig,
    *,
    seed: int | None = None,
    paths: Paths | None = None,
    allow_network: bool = False,
) -> ScenarioBundle:
    """``load_bundle`` plus the scenario's conditions tape bound to its track.

    Kept as a name here for the training code that calls it, but the
    resolution itself lives in :func:`afterlap_core.simulation.config.resolve_bundle`
    so the planner and the control plane resolve a scenario identically. Two
    copies of this would let a planner and its episode disagree about the
    weather without anything noticing.
    """
    return _resolve_bundle(scenario, paths, seed=seed, allow_network=allow_network)


class ScenarioSampler:
    """Circuit -> coherent conditions tape -> synthetic own energy -> seed.

    ``group`` names one split group. Circuit weights are decision opportunities
    per race, ``race_laps * official_length_m / decision_interval_m``, from the
    season registry; a circuit the registry cannot weight is an error, not a
    unit weight.

    A circuit whose compiled package is below ``geometry_validated`` cannot be
    simulated, so it is **skipped** and its reason is recorded on
    :attr:`pending` and in :meth:`as_manifest`. Nothing takes its place: the
    remaining circuits keep their own decision-opportunity weights and the
    sampled distribution simply covers fewer circuits, which the manifest says.
    A group whose circuits are all pending raises
    :class:`ScenarioUnavailable` at construction rather than sampling something
    else.
    """

    def __init__(
        self,
        split: CircuitSplit | None = None,
        group: str = "train",
        *,
        seed: int,
        paths: Paths | None = None,
        registry: Any | None = None,
        readiness: Mapping[str, CircuitReadiness] | None = None,
    ) -> None:
        self.split = split or load_circuit_split(paths=paths)
        self.group = group
        self.seed = int(seed)
        self._paths = paths
        if not self.split.group(group):
            raise ValueError(f"split group {group!r} is empty; nothing to sample")
        availability = group_availability(self.split, group, paths=paths, readiness=readiness)
        if not availability.any_usable:
            raise ScenarioUnavailable(availability.refusal())
        self.availability: GroupAvailability = availability
        self.track_ids = availability.usable
        self.pending: dict[str, str] = dict(availability.pending)
        if registry is None:
            from ..tracks.registry import load_registry

            registry = load_registry(paths)
        self._weights = self._decision_opportunity_weights(registry)
        self._keyed = KeyedRandom(f"sampler:{self.split.split_hash}:{group}", self.seed, bin_width_s=1.0)

    # -- weights ------------------------------------------------------------- #

    def _decision_opportunity_weights(self, registry: Any) -> dict[str, float]:
        weights: dict[str, float] = {}
        for track_id in self.track_ids:
            try:
                entry = registry.get(track_id)
            except KeyError as error:
                raise ValueError(
                    f"track {track_id!r} is in split group {self.group!r} but not in the season registry; "
                    "it cannot be weighted by decision opportunities"
                ) from error
            length = entry.official_length_m.value
            laps = [event.race_laps for event in entry.events if event.race_laps is not None]
            if length is None or not laps:
                raise ValueError(
                    f"registry entry {track_id!r} lacks an official length or race lap count; the "
                    "decision-opportunity weight is unknown and is not guessed"
                )
            weights[track_id] = float(laps[0]) * float(length) / self.split.decision_interval_m
        return weights

    @property
    def weights(self) -> dict[str, float]:
        """Decision opportunities per race, per circuit (unnormalised)."""
        return dict(self._weights)

    @property
    def probabilities(self) -> dict[str, float]:
        total = sum(self._weights.values())
        return {track_id: weight / total for track_id, weight in self._weights.items()}

    # -- draws --------------------------------------------------------------- #

    def draw(self, index: int) -> ScenarioDraw:
        """The ``index``-th draw of this sampler. Pure: the same inputs give the same draw."""
        if index < 0:
            raise ValueError("draw index must be non-negative")
        time = float(index)
        ids = list(self.track_ids)
        p = np.asarray([self._weights[t] for t in ids], dtype=np.float64)
        p = p / p.sum()
        circuit = int(self._keyed.generator("circuit", time).choice(len(ids), p=p))
        track_id = ids[circuit]

        tapes = self.split.tapes_for(track_id, self.group)
        conditions_id: str | None = None
        if tapes:
            conditions_id = tapes[int(self._keyed.generator("conditions", time).integers(0, len(tapes)))]

        energy = self.split.energy
        energy_j = float(self._keyed.uniform("energy", time, low=energy.low_j, high=energy.high_j))
        seed = int(self._keyed.generator("seed", time).integers(self.split.seed_low, self.split.seed_high))
        return ScenarioDraw(
            index=index,
            group=self.group,
            track_id=track_id,
            conditions_id=conditions_id,
            energy_j=energy_j,
            energy_label=energy.label,
            seed=seed,
            scenario_id=self.split.scenario_documents.get(track_id),
            split_hash=self.split.split_hash,
        )

    def draws(self, count: int, *, start: int = 0) -> tuple[ScenarioDraw, ...]:
        return tuple(self.draw(index) for index in range(start, start + count))

    # -- bundles ------------------------------------------------------------- #

    def scenario(self, draw: ScenarioDraw) -> ScenarioConfig:
        """The scenario document for a draw with the sampled values written in.

        Only the seed, the conditions tape and the ego's starting energy change;
        every other Parameter is the document's own. The energy Parameter carries
        the split's declared synthetic source and the required label.
        """
        if draw.scenario_id is None:
            raise ScenarioUnavailable(
                f"circuit {draw.track_id!r} has no scenario document declared in split "
                f"{self.split.revision}; no episode can be built for it"
            )
        if draw.conditions_id is None:
            raise ScenarioUnavailable(
                f"circuit {draw.track_id!r} has no coherent conditions tape declared for group "
                f"{self.group!r}; the static reference is not substituted"
            )
        base = load_scenario(draw.scenario_id, self._paths)
        if base.track_id != draw.track_id:
            raise ScenarioUnavailable(
                f"scenario {draw.scenario_id!r} is written for track {base.track_id!r}, not {draw.track_id!r}"
            )
        if base.status_note is None or self.split.energy.label not in base.status_note:
            raise ScenarioUnavailable(
                f"scenario {draw.scenario_id!r} does not carry the {self.split.energy.label!r} label"
            )
        ego = base.ego_car_id
        energy = Parameter(
            value=draw.energy_j,
            unit="J",
            source=self.split.energy.source,
            verification=VerificationStatus.SYNTHETIC_ASSUMPTION,
            lower_bound=0.0,
            note=f"{self.split.energy.label}: sampled from the declared synthetic distribution",
        )
        states = dict(base.initial_states)
        states[ego] = states[ego].model_copy(update={"energy_j": energy})
        return base.model_copy(
            update={"seed": draw.seed, "conditions_id": draw.conditions_id, "initial_states": states}
        )

    def bundle(self, draw: ScenarioDraw) -> ScenarioBundle:
        """Resolve a draw. Refuses, rather than defaults, anything not honestly loadable."""
        return resolve_bundle(self.scenario(draw), seed=draw.seed, paths=self._paths)

    def as_manifest(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "seed": self.seed,
            "split": self.split.as_manifest(),
            "circuits": {
                "required_readiness": REQUIRED_READINESS,
                "sampled": list(self.track_ids),
                "skipped_pending_readiness": dict(sorted(self.pending.items())),
            },
            "balance": {
                "method": "decision_opportunities",
                "decision_interval_m": self.split.decision_interval_m,
                "probabilities": self.probabilities,
            },
            "energy": {
                "label": self.split.energy.label,
                "distribution": self.split.energy.distribution,
                "low_j": self.split.energy.low_j,
                "high_j": self.split.energy.high_j,
            },
        }
