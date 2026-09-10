"""The machine-readable inventory of every model in this repository.

A model registry written by hand goes stale the first time someone changes a
hidden width, and then the document and the code disagree with no way to tell
which is right. This module *derives* the inventory from the code and the
frozen configuration documents, so the published table cannot drift from what
would actually run.

Two kinds of entry, kept apart on purpose:

**Learned models** have trainable parameters fitted from data. Their
architecture and parameter counts are read off constructed modules when the
learning extra is installed, and reported as unavailable-with-a-reason when it
is not -- never guessed from ``net_arch``.

**Deterministic and statistical models** have no fitted parameters at all: the
analytic surrogate the solver differentiates, the estimator, the independent
rules checker, the scenario quadrature, the reward, the isotonic calibrator's
*method*. They are in the inventory because a reader asking "what models does
this system contain" is owed all of them, and because three of them are the
things a learned model is being compared against.

The distinction the registry exists to keep visible is between **architecture
that exists**, **a bounded observed measurement**, and **a target gate**. A
parameter count is the first. A training loss is the second. A promotion
threshold is the third. They are separate fields and are never merged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .feature_manifest import ACTION_SIZE, ENERGY_V1, OBSERVATION_SIZE
from .paths import Paths, atomic_write_json, sha256_json

__all__ = [
    "REGISTRY_SCHEMA",
    "ModelRecord",
    "RegistryReport",
    "build_registry",
    "write_registry",
]

REGISTRY_SCHEMA = "afterlap.model_registry/1"

LEARNED = "learned"
DETERMINISTIC = "deterministic"
STATISTICAL = "statistical"


@dataclass(frozen=True, slots=True)
class ModelRecord:
    """One model, with its evidence separated by what kind of claim it is."""

    identifier: str
    kind: str
    purpose: str
    module: str
    inputs: str
    outputs: str
    algorithm: str
    trainable_parameters: int | None = None
    parameter_detail: str | None = None
    loss: str | None = None
    training_data: str | None = None
    split: str | None = None
    seeds: tuple[int, ...] = ()
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    evaluation_metrics: tuple[str, ...] = ()
    observed: dict[str, Any] = field(default_factory=dict)
    target_gates: dict[str, Any] = field(default_factory=dict)
    version: str | None = None
    content_hash: str | None = None
    serving_status: str = "not served"
    promotion_status: str = "not applicable"
    limitations: tuple[str, ...] = ()
    fallback: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "kind": self.kind,
            "purpose": self.purpose,
            "module": self.module,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "algorithm": self.algorithm,
            "trainable_parameters": self.trainable_parameters,
            "parameter_detail": self.parameter_detail,
            "loss": self.loss,
            "training_data": self.training_data,
            "split": self.split,
            "seeds": list(self.seeds),
            "hyperparameters": self.hyperparameters,
            "evaluation_metrics": list(self.evaluation_metrics),
            "observed": self.observed,
            "target_gates": self.target_gates,
            "version": self.version,
            "content_hash": self.content_hash,
            "serving_status": self.serving_status,
            "promotion_status": self.promotion_status,
            "limitations": list(self.limitations),
            "fallback": self.fallback,
        }


@dataclass(frozen=True, slots=True)
class RegistryReport:
    """The whole inventory, plus what could not be inspected and why."""

    models: tuple[ModelRecord, ...]
    generated_at: str
    feature_schema_hash: str
    observation_size: int
    action_size: int
    notes: tuple[str, ...] = field(default_factory=tuple)
    unavailable: dict[str, str] = field(default_factory=dict)

    def named(self, identifier: str) -> ModelRecord | None:
        return next((model for model in self.models if model.identifier == identifier), None)

    @property
    def learned(self) -> tuple[ModelRecord, ...]:
        return tuple(model for model in self.models if model.kind == LEARNED)

    @property
    def total_trainable_parameters(self) -> int | None:
        counts = [m.trainable_parameters for m in self.learned if m.trainable_parameters is not None]
        return sum(counts) if counts else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": REGISTRY_SCHEMA,
            "generated_at": self.generated_at,
            "feature_schema_hash": self.feature_schema_hash,
            "observation_size": self.observation_size,
            "action_size": self.action_size,
            "model_count": len(self.models),
            "learned_model_count": len(self.learned),
            "total_trainable_parameters": self.total_trainable_parameters,
            "models": [model.as_dict() for model in self.models],
            "unavailable": dict(sorted(self.unavailable.items())),
            "notes": list(self.notes),
        }

    def content_hash(self) -> str:
        payload = self.as_dict()
        payload.pop("generated_at", None)
        return sha256_json(payload)


def _sac_record(paths: Paths | None, unavailable: dict[str, str]) -> ModelRecord:
    """The SAC actor and critics. Counts come from constructed modules or not at all."""
    from .learning.config import load_sac_config

    config = load_sac_config(paths=paths)
    counts: int | None = None
    detail: str | None = None
    try:
        import numpy as np
        from gymnasium import spaces
        from stable_baselines3.common.torch_layers import FlattenExtractor
        from stable_baselines3.sac.policies import Actor

        from .learning.architecture import describe_module

        observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(OBSERVATION_SIZE,), dtype=np.float32)
        action_space = spaces.Box(low=-1.0, high=1.0, shape=(ACTION_SIZE,), dtype=np.float32)
        actor = Actor(
            observation_space=observation_space,
            action_space=action_space,
            net_arch=list(config.net_arch),
            features_extractor=FlattenExtractor(observation_space),
            features_dim=OBSERVATION_SIZE,
        )
        described = describe_module(actor, identity="sac/actor")
        counts = described.trainable_parameters
        detail = (
            f"actor only, constructed at net_arch={list(config.net_arch)}. The critic and its "
            "Polyak-tracked target are counted per bundle in that bundle's training_report.json, "
            "because the target copy is not optimiser-updated and would double the figure."
        )
    except ImportError as exc:
        unavailable["sac"] = (
            f"the learning extra is not installed, so no parameter count was read off a "
            f"constructed network: {exc}"
        )
        detail = "not counted: the learning extra is not installed and net_arch is a request, not a count"

    return ModelRecord(
        identifier="sac-energy-strategy",
        kind=LEARNED,
        purpose="Propose a bounded soft energy preference that warm-starts the constrained solve.",
        module="afterlap_core.learning.train_sac",
        inputs=f"{OBSERVATION_SIZE}-value energy-v1 observation (96 values plus a 96-value known mask)",
        outputs=f"{ACTION_SIZE} bounded preferences in [-1, 1]: deployment budget and reserve target",
        algorithm="Soft Actor-Critic (stable-baselines3, MlpPolicy), used unmodified",
        trainable_parameters=counts,
        parameter_detail=detail,
        loss="SAC actor/critic/entropy objectives as implemented by the pinned library",
        training_data=(
            "transitions generated by the simulator-backed Gymnasium environment; there is no "
            "stored dataset, so a bundle hashes the generator configuration instead"
        ),
        split="circuit-split-v1 groups; the held-out circuit group cannot be sampled today",
        seeds=tuple(config.seeds),
        hyperparameters=config.as_manifest(),
        evaluation_metrics=(
            "deterministic actor-mean episode return",
            "tracked actor/critic/entropy losses",
            "withdrawal rate",
            "paired utility difference against mpc_only (not yet measured)",
        ),
        version=config.revision,
        content_hash=config.content_hash,
        serving_status="served only from an approved and promoted bundle; none exists",
        promotion_status="no candidate has been promoted; configs/benchmarks/promotion.yaml is disabled",
        limitations=(
            (
                "The shipped configuration declares status "
                "'initial_engineering_configuration_not_trained' and calls its 200000-step budget a "
                "placeholder."
            ),
            (
                "Every observed figure in this repository comes from a bounded run far below that "
                "budget on one seed."
            ),
        ),
        fallback="mpc-only/planner-v1",
    )


def _value_record(paths: Paths | None) -> ModelRecord:
    from .learning.config import load_value_config

    config = load_value_config(paths=paths)
    hidden = list(config.hidden)
    per_member = 0
    previous = OBSERVATION_SIZE
    for width in hidden:
        per_member += previous * width + width
        previous = width
    per_member += previous * 1 + 1

    return ModelRecord(
        identifier="continuation-return-ensemble",
        kind=LEARNED,
        purpose="Predict the ordinary discounted continuation return beyond the planner's horizon.",
        module="afterlap_core.learning.value",
        inputs=f"{OBSERVATION_SIZE}-value energy-v1 observation",
        outputs="one continuation value in objective utility units, plus the ensemble disagreement",
        algorithm=f"{config.members} independently initialised MLPs, {OBSERVATION_SIZE}->"
        + "->".join(str(w) for w in hidden)
        + "->1, ReLU",
        trainable_parameters=per_member * config.members,
        parameter_detail=(
            f"{per_member:,} per member x {config.members} members, computed from the declared "
            "layer widths. A fitted ensemble reports its own counts in the bundle's "
            "training_report.json, read off the constructed modules."
        ),
        loss=f"weighted Huber (delta={config.huber_delta}) on standardised targets, Adam, early stopping",
        training_data=(
            "per-cutoff ordinary discounted returns from complete simulator episodes under one "
            "named frozen controller"
        ),
        split="by episode, never by row; adjacent cutoffs of one episode cannot straddle the split",
        seeds=(),
        hyperparameters={
            "members": config.members,
            "hidden": hidden,
            "learning_rate": config.learning_rate,
            "batch_size": config.batch_size,
            "weight_decay": config.weight_decay,
            "huber_delta": config.huber_delta,
            "max_epochs": config.max_epochs,
            "patience": config.patience,
        },
        evaluation_metrics=("MAE", "RMSE", "bias, grouped by remaining distance and energy regime"),
        version=config.revision,
        content_hash=config.content_hash,
        serving_status=(
            "refused at serving: value-v1 declares frozen_before_final_test=false, so the support "
            "gate disables the contribution regardless of fit quality"
        ),
        promotion_status="not applicable until the support thresholds are frozen",
        limitations=(
            ("The shipped support thresholds are declared placeholders, not derived from a calibration set."),
            (
                "An ensemble fitted under one controller is not a universal value function and must "
                "not be reused under another."
            ),
        ),
        fallback="the planner's analytic terminal energy term",
    )


def _calibrator_record() -> ModelRecord:
    from .learning.calibration import DEFAULT_MIN_SUPPORT

    return ModelRecord(
        identifier="probability-calibrator",
        kind=STATISTICAL,
        purpose="Map a raw rollout-ensemble event frequency to a calibrated probability.",
        module="afterlap_core.learning.calibration",
        inputs="one raw weighted scenario frequency for a named event",
        outputs="a calibrated probability, or an explicit refusal with its reason",
        algorithm="isotonic regression by pool-adjacent-violators, one monotone map per event",
        trainable_parameters=None,
        parameter_detail=(
            "non-parametric: the fitted object is a step function whose knot count depends on the "
            "calibration set, so there is no fixed parameter count to report"
        ),
        loss="least squares under a monotonicity constraint",
        training_data=(
            "forecast/realisation pairs from complete simulator episodes, the label resolved from "
            "the same episode the forecast was made in"
        ),
        split="by episode; an unreached event is dropped rather than labelled false",
        evaluation_metrics=("Brier score", "log loss", "reliability bins", "support count"),
        target_gates={"min_support": DEFAULT_MIN_SUPPORT},
        serving_status=(
            "published only when frozen_before_final_test is set by an operator; otherwise the raw "
            "frequency is published as uncalibrated"
        ),
        promotion_status="not applicable; freezing is a separate operator act",
        limitations=(
            (
                "A single-class calibration set is refused: no monotone map is identifiable and a "
                "constant fit would report a perfect score."
            ),
            "A forecast outside the fitted domain is clamped to the nearest end and flagged.",
        ),
        fallback="the uncalibrated raw ensemble frequency, labelled as such",
    )


def _deterministic_records(paths: Paths | None) -> tuple[ModelRecord, ...]:
    from .learning.reward import load_reward_manifest
    from .planning.config import load_planner_config

    planner = load_planner_config(paths=paths)
    reward = load_reward_manifest()

    return (
        ModelRecord(
            identifier="planner-surrogate",
            kind=DETERMINISTIC,
            purpose="The smooth reduced model the continuous solver differentiates.",
            module="afterlap_core.planning.surrogate",
            inputs="a plan frame, a rival scenario ensemble and an energy allocation",
            outputs="corridor time, rival deficit and a scenario loss",
            algorithm="closed-form arithmetic: cube-root corridor time, softplus deficit, logistic gap",
            trainable_parameters=0,
            parameter_detail="no fitted parameters; every coefficient is a frozen configuration value",
            evaluation_metrics=("surrogate/simulator disagreement, not yet measured",),
            version=planner.revision if hasattr(planner, "revision") else "planner-v1",
            serving_status="always active inside the planner",
            limitations=(
                (
                    "Every coefficient is labelled verification: synthetic_assumption in "
                    "configs/planning/planner-v1.yaml."
                ),
                (
                    "The harvest-opportunity coefficient is declared the largest single source of "
                    "surrogate/simulator disagreement."
                ),
            ),
            fallback="none; without it there is no continuous solve",
        ),
        ModelRecord(
            identifier="rollout-forecaster",
            kind=STATISTICAL,
            purpose="Re-simulate finalists against reacting rivals and report event frequencies.",
            module="afterlap_core.planning.rollout",
            inputs="a candidate's profile segments and a weighted rival scenario ensemble",
            outputs="scenario outcomes, per-checkpoint ranges and pass_before/ahead_at frequencies",
            algorithm="weighted Monte-Carlo over sampled rival hypotheses, rivals re-deciding",
            trainable_parameters=0,
            parameter_detail="no fitted parameters; the weights come from the estimator's belief",
            evaluation_metrics=("base rate agreement against realised episodes",),
            version="planner-rollout-ensemble-v1",
            serving_status="active when the session enables re-simulation; off by default",
            limitations=(
                (
                    "ahead_at is evaluated over the branch horizon while a realisation resolves it "
                    "over the whole episode; see artifacts/reports/finding_ahead_at_horizon.md."
                ),
                "Frequencies are published uncalibrated unless a frozen calibrator is supplied.",
            ),
            fallback="none; without it no probability or outcome range is published",
        ),
        ModelRecord(
            identifier="own-car-estimator",
            kind=STATISTICAL,
            purpose="Fuse observations into the own-car belief the controller sees.",
            module="afterlap_core.estimation.own_car",
            inputs="delivered telemetry observations with their quality and provenance",
            outputs="a StateEstimate with per-field provenance, quality and uncertainty",
            algorithm="extended Kalman filter with a hand-written, difference-checked Jacobian",
            trainable_parameters=0,
            parameter_detail="no fitted parameters; process and measurement noise are configured",
            evaluation_metrics=("interval coverage, reported per field",),
            version="own-car-ekf-v1",
            serving_status="always active in a session",
            limitations=("Every noise value is a synthetic engineering assumption.",),
            fallback="an explicit unavailable field; a missing value is never zero",
        ),
        ModelRecord(
            identifier="rival-belief",
            kind=STATISTICAL,
            purpose="Infer hidden rival state and intention weights without observing them.",
            module="afterlap_core.estimation.rivals",
            inputs="relational observations only; rival energy and temperature are never observed",
            outputs="a rival belief with an energy interval and intention weights",
            algorithm="mode-weighted filtering over declared rival behaviour modes",
            trainable_parameters=0,
            parameter_detail="no fitted parameters; mode definitions are configured",
            evaluation_metrics=("interval coverage; the shipped 0.90 label measured 0.7885",),
            version="rival-modes-v1",
            serving_status="always active in a session",
            limitations=(
                "Rival stored energy can never be labelled measured; the contract refuses it.",
                "The nominal 0.90 quantile label was measured at 0.7885 coverage.",
            ),
            fallback="an interval spanning the whole physical battery window, flagged unknown",
        ),
        ModelRecord(
            identifier="independent-rules-checker",
            kind=DETERMINISTIC,
            purpose="Adjudicate a candidate plan against the loaded rule pack, independently.",
            module="afterlap_core.rules.checker",
            inputs="a candidate plan, a checker state and a resolved rule context",
            outputs="a per-check verdict and an aggregate pass/unknown/fail",
            algorithm="seven named limit checks; the aggregate is fail > unknown > pass",
            trainable_parameters=0,
            parameter_detail="no fitted parameters; every limit is read from the versioned pack",
            evaluation_metrics=("hand-computed boundary cases in tests/rules",),
            serving_status="always active; its verdict is final and unknown is not acceptance",
            limitations=("Every shipped pack is synthetic and claims no regulatory standing.",),
            fallback="none; a plan it does not pass is withdrawn",
        ),
        ModelRecord(
            identifier="reward-objective",
            kind=DETERMINISTIC,
            purpose="Score a training transition and the planner's objective terms.",
            module="afterlap_core.learning.reward",
            inputs="a step outcome and the frozen objective document",
            outputs="a decomposed reward with a potential-based shaping term",
            algorithm="linear combination of frozen coefficients plus potential shaping",
            trainable_parameters=0,
            parameter_detail="no fitted parameters; a missing coefficient raises rather than defaulting",
            version=reward.revision,
            serving_status="active in training and in planner scoring",
            limitations=("The reference pace behind the shaping term is a fixed model, not race truth.",),
            fallback="none",
        ),
    )


def build_registry(paths: Paths | None = None) -> RegistryReport:
    """Derive the inventory from the code and the frozen configuration."""
    unavailable: dict[str, str] = {}
    models = [
        _sac_record(paths, unavailable),
        _value_record(paths),
        _calibrator_record(),
        *_deterministic_records(paths),
    ]
    notes = (
        (
            "Architecture that exists, a bounded observed measurement and a target gate are separate "
            "fields here and are never merged. A parameter count is the first, a training loss the "
            "second, a promotion threshold the third."
        ),
        (
            "Observed values are not stored in this registry. They live in each bundle's "
            "hash-covered training_report.json and in the run records under artifacts/reports, so a "
            "number can always be traced to the run that produced it."
        ),
        (
            "Every configuration behind these models is synthetic. Nothing here is a measurement of "
            "a real car, circuit or race."
        ),
    )
    return RegistryReport(
        models=tuple(models),
        generated_at=datetime.now(UTC).isoformat(),
        feature_schema_hash=ENERGY_V1.content_hash(),
        observation_size=OBSERVATION_SIZE,
        action_size=ACTION_SIZE,
        notes=notes,
        unavailable=unavailable,
    )


def write_registry(report: RegistryReport, *, paths: Paths | None = None, output: Path | None = None) -> Path:
    """Write the registry as JSON and return where it landed."""
    target = (
        Path(output)
        if output is not None
        else (paths or Paths.default()).ensure().reports / "model_registry.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, report.as_dict())
    return target


def as_markdown(report: RegistryReport) -> str:
    """A table a person can read, generated from the same data as the JSON."""
    lines = [
        "| Model | Kind | Trainable parameters | Serving | Promotion |",
        "|---|---|---:|---|---|",
    ]
    for model in report.models:
        count = "not counted" if model.trainable_parameters is None else f"{model.trainable_parameters:,}"
        lines.append(
            f"| `{model.identifier}` | {model.kind} | {count} | {model.serving_status} | "
            f"{model.promotion_status} |"
        )
    return "\n".join(lines) + "\n"


__all__ += ["as_markdown"]


def main() -> None:  # pragma: no cover - exercised through the CLI
    report = build_registry()
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True, default=str))
