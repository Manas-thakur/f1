"""The factor registry, loaded and cross-checked against what the code does.

``17_real_tracks_conditions/FACTOR_AND_INFLUENCE.md`` asks for
``configs/factors/factor-registry.yaml`` and is explicit that three different
things are confused when people say "every factor has a weight": physics
parameters with units, frozen reward coefficients, and emergent policy-feature
influence. This module keeps them apart structurally.

Two cross-checks make the registry load-bearing rather than decorative:

* :func:`check_reward_terms` refuses a registry whose reward-term ids are not
  present in the frozen objective document, so the rationale text cannot drift
  away from the coefficient it explains.
* :func:`check_no_track_identity` refuses a registry that claims track identity
  is excluded from the actor while the feature manifest still contains a field
  whose name implies it.

Nothing here publishes a per-feature importance number, because the actor does
not have one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from .paths import Paths

REGISTRY_ID = "factor-registry-v1"

TRACK_IDENTITY_TOKENS = ("track_id", "track_name", "circuit_id", "circuit_name", "track_hash", "track_index")
"""Substrings that would betray a circuit shortcut if they appeared in a feature name."""


class Availability(StrEnum):
    """Whether the product can supply a factor at all."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class PhysicsFactor:
    """One physical quantity with units that changes the state transition."""

    id: str
    meaning: str
    units: str
    simulator_role: str
    source: str
    missing_behaviour: str
    correlation_group: str
    causal_parents: tuple[str, ...]
    verification: str
    validation_owner: str
    availability: Availability
    supported_range: tuple[float, float] | None
    caveat: str | None

    @property
    def is_measured(self) -> bool:
        """True only for a factor backed by a measurement, not an assumption."""
        return self.verification not in {"synthetic_assumption", "unavailable"}


@dataclass(frozen=True, slots=True)
class FactorRegistry:
    """The loaded registry, with its three sections kept separate."""

    id: str
    physics: tuple[PhysicsFactor, ...]
    reward_objective_revision: str
    reward_term_ids: tuple[str, ...]
    reward_rationales: dict[str, str]
    feature_revision: str
    excluded_feature_ids: tuple[str, ...]
    influence_method_ids: tuple[str, ...]
    open_questions: tuple[str, ...]
    raw: dict[str, Any]

    def physics_factor(self, factor_id: str) -> PhysicsFactor:
        for factor in self.physics:
            if factor.id == factor_id:
                return factor
        raise KeyError(f"no physics factor {factor_id!r} in {self.id}")

    @property
    def unavailable_ids(self) -> tuple[str, ...]:
        """Factors the product refuses to supply rather than substituting a number."""
        return tuple(f.id for f in self.physics if f.availability is Availability.UNAVAILABLE)

    @property
    def assumed_ids(self) -> tuple[str, ...]:
        """Factors carried as engineering assumptions with no measurement behind them."""
        return tuple(f.id for f in self.physics if f.verification == "synthetic_assumption")


def registry_path(paths: Paths | None = None) -> Path:
    return (paths or Paths.default()).configs / "factors" / "factor-registry.yaml"


def load_factor_registry(paths: Paths | None = None) -> FactorRegistry:
    """Read and structurally validate the registry document."""
    path = registry_path(paths)
    if not path.exists():
        raise FileNotFoundError(f"no factor registry at {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"factor registry at {path} is not a mapping")

    physics: list[PhysicsFactor] = []
    for entry in document.get("physics_parameters") or ():
        span = entry.get("supported_range")
        physics.append(
            PhysicsFactor(
                id=str(entry["id"]),
                meaning=str(entry["meaning"]),
                units=str(entry["units"]),
                simulator_role=str(entry["simulator_role"]),
                source=str(entry["source"]),
                missing_behaviour=str(entry["missing_behaviour"]),
                correlation_group=str(entry["correlation_group"]),
                causal_parents=tuple(str(p) for p in entry.get("causal_parents") or ()),
                verification=str(entry["verification"]),
                validation_owner=str(entry["validation_owner"]),
                availability=Availability(str(entry["availability"])),
                supported_range=(float(span[0]), float(span[1])) if span else None,
                caveat=None if entry.get("caveat") is None else str(entry["caveat"]),
            )
        )
    if not physics:
        raise ValueError("a factor registry with no physics parameters is not usable")
    duplicates = {f.id for f in physics if sum(1 for g in physics if g.id == f.id) > 1}
    if duplicates:
        raise ValueError(f"factor registry lists {sorted(duplicates)} more than once")

    reward = document.get("reward_coefficients") or {}
    terms = reward.get("terms") or ()
    features = document.get("policy_features") or {}
    return FactorRegistry(
        id=str(document.get("id", "")),
        physics=tuple(physics),
        reward_objective_revision=str(reward.get("objective_revision", "")),
        reward_term_ids=tuple(str(t["id"]) for t in terms),
        reward_rationales={str(t["id"]): str(t["rationale"]) for t in terms},
        feature_revision=str(features.get("feature_revision", "")),
        excluded_feature_ids=tuple(str(e["id"]) for e in (features.get("excluded_deliberately") or ())),
        influence_method_ids=tuple(
            str(m["id"]) for m in ((document.get("influence_methods") or {}).get("methods") or ())
        ),
        open_questions=tuple(str(q) for q in document.get("open_evidence_questions") or ()),
        raw=document,
    )


def check_reward_terms(registry: FactorRegistry, paths: Paths | None = None) -> tuple[str, ...]:
    """Every rationale must explain a coefficient that the objective really declares.

    Returns the term ids that were matched; raises when one is not in the frozen
    objective document, because a rationale for a coefficient that does not
    exist is worse than none.
    """
    objective = (
        (paths or Paths.default()).configs / "objectives" / f"{registry.reward_objective_revision}.yaml"
    )
    if not objective.exists():
        raise FileNotFoundError(
            f"registry names objective {registry.reward_objective_revision!r} but {objective} is absent"
        )
    document = yaml.safe_load(objective.read_text(encoding="utf-8"))
    declared: set[str] = set()
    for section in document.values():
        if isinstance(section, dict):
            declared.update(str(k) for k in section)
    unknown = [term for term in registry.reward_term_ids if term not in declared]
    if unknown:
        raise ValueError(
            f"factor registry gives a rationale for {unknown}, which objective "
            f"{registry.reward_objective_revision} does not declare"
        )
    return registry.reward_term_ids


def check_no_track_identity(registry: FactorRegistry) -> tuple[str, ...]:
    """The registry's exclusion claim must match the feature manifest it names.

    Returns the checked feature names. Raises when the registry claims track
    identity is excluded while a field name implies it is present.
    """
    from .feature_manifest import ENERGY_V1

    if registry.feature_revision != ENERGY_V1.revision:
        raise ValueError(
            f"registry names feature revision {registry.feature_revision!r} but the manifest is "
            f"{ENERGY_V1.revision!r}"
        )
    if "track_identity" not in registry.excluded_feature_ids:
        return ()
    names = tuple(field.name for field in ENERGY_V1.fields)
    offenders = [name for name in names if any(token in name.lower() for token in TRACK_IDENTITY_TOKENS)]
    if offenders:
        raise ValueError(
            f"the registry claims track identity is excluded from the actor, but feature "
            f"revision {ENERGY_V1.revision} contains {offenders}"
        )
    return names


__all__ = [
    "REGISTRY_ID",
    "TRACK_IDENTITY_TOKENS",
    "Availability",
    "FactorRegistry",
    "PhysicsFactor",
    "check_no_track_identity",
    "check_reward_terms",
    "load_factor_registry",
    "registry_path",
]
