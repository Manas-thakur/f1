"""Readers for the learning module's own frozen configuration.

``configs/learning/`` holds three documents:

``env-v1.yaml``     the environment revision: scenarios, cadence, episode limits,
                    the declared reference pace behind the shaping potential and
                    the planner integration mode;
``sac-v1.yaml``     the SAC starting settings from ``SAC_IMPLEMENTATION.md``;
``value-v1.yaml``   the continuation ensemble's fitting settings and its frozen
                    support thresholds.

Every value is an engineering starting setting, not a measured optimum. They are
frozen here so that a run manifest can name the exact document it used, and so
that a coefficient can never be changed by editing code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from afterlap_contracts import SupportThresholds

from ..config import load_config
from ..paths import Paths, sha256_json

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "ENV_REVISION_PREFIX",
    "EnvConfig",
    "SacConfig",
    "ScenarioSpec",
    "ValueConfig",
    "load_env_config",
    "load_sac_config",
    "load_value_config",
]

ENV_REVISION_PREFIX = "afterlap-learning-env"


def _require(document: dict[str, Any], key: str) -> Any:
    if key not in document:
        raise KeyError(f"learning configuration is missing required key {key!r}")
    return document[key]


@dataclass(frozen=True, slots=True)
class ScenarioSpec:
    """One training/tuning scenario and the segment length it declares."""

    scenario_id: str
    family: str
    race_distance_m: float
    reference_pace_mps: float
    rule_pack: str
    seeds: tuple[int, ...]
    warmup_to_progress_m: float | None = None
    """Ego progress the episode starts from.

    The shipped rule pack resolves an overtake permission only at a detection
    line, and the independent checker returns ``unknown`` — never acceptance —
    until it has. A scenario whose ego starts before that line spends its first
    tens of seconds with every candidate rejected, so the environment integrates
    forward to this progress under a declared conserving warm-up first and
    starts the episode there. The warm-up is part of the *scenario starting
    state*: it is identical for every controller and it is recorded in the
    reset info."""

    def __post_init__(self) -> None:
        if self.race_distance_m <= 0.0:
            raise ValueError(f"scenario {self.scenario_id} declares a non-positive segment distance")
        if self.reference_pace_mps <= 0.0:
            raise ValueError(f"scenario {self.scenario_id} declares a non-positive reference pace")
        if not self.seeds:
            raise ValueError(f"scenario {self.scenario_id} declares no seeds")


@dataclass(frozen=True, slots=True)
class EnvConfig:
    """The environment revision.

    ``planner_mode`` is part of the revision string. A replay buffer collected
    under one planner mode is not interchangeable with one collected under
    another, and naming the mode in the revision is what stops them being mixed
    without a deliberate decision.
    """

    revision: str
    content_hash: str
    scenarios: tuple[ScenarioSpec, ...]
    policy_interval_s: float
    physics_step_s: float
    preference_window_s: float
    checkpoint_interval_s: float
    max_episode_steps: int
    planner_mode: str
    warmup_profile: str
    warmup_limit_s: float
    planner_deadline_s: float
    plan_validity_s: float
    replan_energy_tolerance_j: float
    reference_pace_provenance: str
    objective_id: str = "objective-v1"

    def scenario(self, scenario_id: str) -> ScenarioSpec:
        for spec in self.scenarios:
            if spec.scenario_id == scenario_id:
                return spec
        raise KeyError(f"scenario {scenario_id!r} is not part of environment revision {self.revision}")

    @property
    def environment_version(self) -> str:
        """The string written into every checkpoint and bundle."""
        return f"{ENV_REVISION_PREFIX}/{self.revision}/planner={self.planner_mode}"

    def __post_init__(self) -> None:
        if self.policy_interval_s <= 0.0 or self.physics_step_s <= 0.0:
            raise ValueError("policy and physics steps must both be positive")
        if self.physics_step_s > self.policy_interval_s:
            raise ValueError("the physics step cannot be longer than the policy cadence")
        if self.planner_mode not in ("full", "no_rollout", "disabled"):
            raise ValueError(f"unknown planner mode {self.planner_mode!r}")
        if not self.scenarios:
            raise ValueError("an environment revision must declare at least one scenario")


@dataclass(frozen=True, slots=True)
class SacConfig:
    """SAC starting settings, exactly as frozen on disk."""

    revision: str
    content_hash: str
    policy: str
    net_arch: tuple[int, ...]
    learning_rate: float
    buffer_size: int
    learning_starts: int
    batch_size: int
    gamma: float
    tau: float
    ent_coef: str | float
    target_entropy: str | float
    train_freq: int
    gradient_steps: int
    n_envs: int
    device: str
    seeds: tuple[int, ...]
    total_timesteps: int
    checkpoint_every_steps: int
    env_config_id: str

    def as_manifest(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "content_hash": self.content_hash,
            "policy": self.policy,
            "net_arch": list(self.net_arch),
            "learning_rate": self.learning_rate,
            "buffer_size": self.buffer_size,
            "learning_starts": self.learning_starts,
            "batch_size": self.batch_size,
            "gamma": self.gamma,
            "tau": self.tau,
            "ent_coef": self.ent_coef,
            "target_entropy": self.target_entropy,
            "train_freq": self.train_freq,
            "gradient_steps": self.gradient_steps,
            "n_envs": self.n_envs,
            "device": self.device,
            "seeds": list(self.seeds),
            "total_timesteps": self.total_timesteps,
            "checkpoint_every_steps": self.checkpoint_every_steps,
            "env_config_id": self.env_config_id,
        }


@dataclass(frozen=True, slots=True)
class ValueConfig:
    """Continuation-ensemble fitting settings and frozen support thresholds."""

    revision: str
    content_hash: str
    members: int
    hidden: tuple[int, ...]
    learning_rate: float
    batch_size: int
    weight_decay: float
    huber_delta: float
    max_epochs: int
    patience: int
    continuation_controller: str
    support: SupportThresholds = field(
        default_factory=lambda: SupportThresholds(
            max_ensemble_disagreement=1.0, max_clip_fraction=1.0, min_known_mask_fraction=0.0
        )
    )


def load_env_config(config_id: str = "env-v1", paths: Paths | None = None) -> EnvConfig:
    document = load_config("learning", config_id, paths)
    scenarios = tuple(
        ScenarioSpec(
            scenario_id=str(entry["id"]),
            family=str(entry["family"]),
            race_distance_m=float(entry["race_distance_m"]),
            reference_pace_mps=float(entry["reference_pace_mps"]),
            rule_pack=str(entry["rule_pack"]),
            seeds=tuple(int(s) for s in entry["seeds"]),
            warmup_to_progress_m=(
                None if entry.get("warmup_to_progress_m") is None else float(entry["warmup_to_progress_m"])
            ),
        )
        for entry in _require(document, "scenarios")
    )
    return EnvConfig(
        revision=str(_require(document, "id")),
        content_hash=sha256_json(document),
        scenarios=scenarios,
        policy_interval_s=float(_require(document, "policy_interval_s")),
        physics_step_s=float(_require(document, "physics_step_s")),
        preference_window_s=float(_require(document, "preference_window_s")),
        checkpoint_interval_s=float(_require(document, "checkpoint_interval_s")),
        max_episode_steps=int(_require(document, "max_episode_steps")),
        planner_mode=str(_require(document, "planner_mode")),
        warmup_profile=str(document.get("warmup_profile", "harvest")),
        warmup_limit_s=float(document.get("warmup_limit_s", 120.0)),
        planner_deadline_s=float(_require(document, "planner_deadline_s")),
        plan_validity_s=float(_require(document, "plan_validity_s")),
        replan_energy_tolerance_j=float(_require(document, "replan_energy_tolerance_j")),
        reference_pace_provenance=str(_require(document, "reference_pace_provenance")),
        objective_id=str(document.get("objective_id", "objective-v1")),
    )


def load_sac_config(config_id: str = "sac-v1", paths: Paths | None = None) -> SacConfig:
    document = load_config("learning", config_id, paths)
    algorithm = _require(document, "algorithm")
    if str(algorithm).upper() != "SAC":
        raise ValueError(f"configuration {config_id!r} declares algorithm {algorithm!r}, not SAC")
    return SacConfig(
        revision=str(_require(document, "id")),
        content_hash=sha256_json(document),
        policy=str(document.get("policy", "MlpPolicy")),
        net_arch=tuple(int(n) for n in _require(document, "net_arch")),
        learning_rate=float(_require(document, "learning_rate")),
        buffer_size=int(_require(document, "buffer_size")),
        learning_starts=int(_require(document, "learning_starts")),
        batch_size=int(_require(document, "batch_size")),
        gamma=float(_require(document, "gamma")),
        tau=float(_require(document, "tau")),
        ent_coef=document.get("ent_coef", "auto"),
        target_entropy=document.get("target_entropy", "auto"),
        train_freq=int(_require(document, "train_freq")),
        gradient_steps=int(_require(document, "gradient_steps")),
        n_envs=int(_require(document, "n_envs")),
        device=str(_require(document, "device")),
        seeds=tuple(int(s) for s in _require(document, "seeds")),
        total_timesteps=int(_require(document, "total_timesteps")),
        checkpoint_every_steps=int(_require(document, "checkpoint_every_steps")),
        env_config_id=str(document.get("env_config_id", "env-v1")),
    )


def load_value_config(config_id: str = "value-v1", paths: Paths | None = None) -> ValueConfig:
    document = load_config("learning", config_id, paths)
    support = _require(document, "support_thresholds")
    return ValueConfig(
        revision=str(_require(document, "id")),
        content_hash=sha256_json(document),
        members=int(_require(document, "members")),
        hidden=tuple(int(n) for n in _require(document, "hidden")),
        learning_rate=float(_require(document, "learning_rate")),
        batch_size=int(_require(document, "batch_size")),
        weight_decay=float(_require(document, "weight_decay")),
        huber_delta=float(_require(document, "huber_delta")),
        max_epochs=int(_require(document, "max_epochs")),
        patience=int(_require(document, "patience")),
        continuation_controller=str(_require(document, "continuation_controller")),
        support=SupportThresholds(
            max_ensemble_disagreement=float(support["max_ensemble_disagreement"]),
            max_clip_fraction=float(support["max_clip_fraction"]),
            min_known_mask_fraction=float(support["min_known_mask_fraction"]),
            frozen_before_final_test=bool(support.get("frozen_before_final_test", False)),
        ),
    )


def learning_config_dir(paths: Paths | None = None) -> Path:
    from ..config import config_dir

    return config_dir("learning", paths)
