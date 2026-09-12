"""The frozen model bundle and its loader.

A bundle is a directory holding the actor weights, the five continuation
members, the feature and action manifests, the normaliser, the target scaler,
the probability calibrator, the frozen support thresholds, the model card, and a
top-level ``bundle.json`` carrying the schema version, a SHA-256 map of every
artifact, the library versions and the promotion status.

Loading refuses more often than it succeeds, deliberately:

* **every hash is validated before initialisation.** A filename is not evidence
  of what a set of weights contains;
* **deserialisation is restricted.** ``torch.load(..., weights_only=True)`` is
  used for every tensor file, so a bundle cannot execute code while loading;
* **a feature-hash, rule-family or reward-revision mismatch disables the model
  and names the baseline that takes over.** The rejection is a value, not an
  exception swallowed somewhere: :class:`BundleRejection` carries the reason
  code and ``baseline_identity``.

Nothing here promotes anything. ``approval_status`` on a freshly written bundle
is ``unevaluated`` and the contract refuses ``approved`` without a benchmark
report.
"""

from __future__ import annotations

import contextlib
import json
import platform
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
import torch

from afterlap_contracts import (
    SCHEMA_VERSION,
    ApprovalStatus,
    FeatureManifest,
    ModelManifest,
    NormalizerManifest,
    PromotionPolicy,
    SupportThresholds,
)

from ..feature_manifest import ACTION_SIZE, ENERGY_V1, OBSERVATION_SIZE, PREFERENCE_WINDOW_S
from ..paths import atomic_write_bytes, atomic_write_json, sha256_file
from .value import ContinuationEnsemble

__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "DEFAULT_BASELINE_IDENTITY",
    "BundleRejection",
    "LoadedBundle",
    "RejectionReason",
    "load_bundle",
    "write_bundle",
]

BUNDLE_SCHEMA_VERSION = "afterlap.learning.bundle/1"
DEFAULT_BASELINE_IDENTITY = "mpc-only/planner-v1"
"""The validated path that takes over whenever the learned contribution is off."""

_BUNDLE_FILE = "bundle.json"
_ACTOR_FILE = "actor.pt"
_CARD_FILE = "model_card.md"
_REPORT_FILE = "training_report.json"


class RejectionReason(StrEnum):
    """Why a bundle was refused. Every one leaves the baseline enabled."""

    MISSING_BUNDLE_FILE = "missing_bundle_file"
    UNKNOWN_SCHEMA = "unknown_bundle_schema"
    MISSING_ARTIFACT = "missing_artifact"
    HASH_MISMATCH = "artifact_hash_mismatch"
    FEATURE_HASH_MISMATCH = "feature_schema_hash_mismatch"
    RULE_FAMILY_MISMATCH = "rule_family_mismatch"
    REWARD_REVISION_MISMATCH = "reward_revision_mismatch"
    ENVIRONMENT_VERSION_MISMATCH = "environment_version_mismatch"
    UNREADABLE_WEIGHTS = "unreadable_weights"
    NOT_APPROVED = "not_approved"


class BundleRejection(RuntimeError):
    """A bundle could not be loaded. The baseline named here takes over."""

    def __init__(self, reason: RejectionReason, detail: str, *, baseline_identity: str) -> None:
        super().__init__(f"{reason.value}: {detail} (falling back to {baseline_identity})")
        self.reason = reason
        self.detail = detail
        self.baseline_identity = baseline_identity

    def as_dict(self) -> dict[str, str]:
        return {
            "reason": self.reason.value,
            "detail": self.detail,
            "baseline_identity": self.baseline_identity,
            "learned_contribution_enabled": "false",
        }


@dataclass(frozen=True, slots=True)
class LoadedBundle:
    """A validated bundle, ready to be pinned for one session."""

    directory: Path
    manifest: ModelManifest
    feature_manifest: FeatureManifest
    action_manifest: dict[str, Any]
    actor_state: dict[str, torch.Tensor]
    ensemble: ContinuationEnsemble | None
    normalizer: NormalizerManifest | None
    support: SupportThresholds | None
    calibrator: dict[str, Any] | None
    model_card: str
    training_report: dict[str, Any] | None
    library_versions: dict[str, str]
    promotion_policy: PromotionPolicy
    baseline_identity: str

    @property
    def approved(self) -> bool:
        return self.manifest.approval_status is ApprovalStatus.APPROVED

    @property
    def learned_contribution_enabled(self) -> bool:
        """A bundle only contributes when it is approved *and* promotion is on."""
        return self.approved and self.promotion_policy.enabled


def library_versions() -> dict[str, str]:
    """Versions recorded in every bundle, so a load can detect a changed stack."""
    versions = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "torch": torch.__version__,
        "platform": platform.platform(),
    }
    with contextlib.suppress(ImportError):  # pragma: no cover - optional at fit time
        import gymnasium

        versions["gymnasium"] = gymnasium.__version__
    with contextlib.suppress(ImportError):  # pragma: no cover - optional at fit time
        import stable_baselines3

        versions["stable_baselines3"] = stable_baselines3.__version__
    return versions


def action_manifest() -> dict[str, Any]:
    """The frozen action contract, written beside the feature manifest."""
    return {
        "revision": ENERGY_V1.revision,
        "space": "Box",
        "low": -1.0,
        "high": 1.0,
        "shape": [ACTION_SIZE],
        "dtype": "float32",
        "components": [
            {
                "index": 0,
                "name": "deployment_budget",
                "unit": "J",
                "meaning": "energy leaving the battery over the fixed preference window",
                "window_s": PREFERENCE_WINDOW_S,
                "decode": "lower + (a + 1) / 2 * (upper - lower)",
            },
            {
                "index": 1,
                "name": "reserve_target",
                "unit": "J",
                "meaning": "battery energy target at the next declared tactical checkpoint",
                "decode": "lower + (a + 1) / 2 * (upper - lower)",
            },
        ],
        "semantics": "soft preferences; the planner penalises deviation and still returns a legal plan",
    }


def _state_dict_bytes(state: dict[str, torch.Tensor]) -> bytes:
    import io

    buffer = io.BytesIO()
    torch.save({key: value.detach().cpu() for key, value in state.items()}, buffer)
    return buffer.getvalue()


def write_bundle(
    directory: Path,
    *,
    bundle_id: str,
    actor_state: dict[str, torch.Tensor],
    ensemble: ContinuationEnsemble | None,
    rule_family: str,
    reward_revision: str,
    environment_version: str,
    continuation_controller: str | None,
    training_code_revision: str | None = None,
    training_data_hash: str | None = None,
    supported_scenario_families: tuple[str, ...] = (),
    support: SupportThresholds | None = None,
    normalizer: NormalizerManifest | None = None,
    calibrator: dict[str, Any] | None = None,
    model_card: str,
    training_report: dict[str, Any] | None = None,
    promotion_policy: PromotionPolicy | None = None,
    approval_status: ApprovalStatus = ApprovalStatus.UNEVALUATED,
    benchmark_report_hash: str | None = None,
    baseline_identity: str = DEFAULT_BASELINE_IDENTITY,
) -> Path:
    """Write a frozen bundle. ``approval_status`` never defaults to approved."""
    directory.mkdir(parents=True, exist_ok=True)

    artifacts: dict[str, Path] = {}
    actor_path = directory / _ACTOR_FILE
    atomic_write_bytes(actor_path, _state_dict_bytes(actor_state))
    artifacts[_ACTOR_FILE] = actor_path

    feature_path = directory / "feature_manifest.json"
    atomic_write_json(feature_path, ENERGY_V1.model_dump(mode="json"))
    artifacts["feature_manifest.json"] = feature_path

    action_path = directory / "action_manifest.json"
    atomic_write_json(action_path, action_manifest())
    artifacts["action_manifest.json"] = action_path

    if ensemble is not None:
        for path in ensemble.save(directory).values():
            artifacts[path.name] = path
        scaler_path = directory / "target_scaler.json"
        atomic_write_json(scaler_path, ensemble.target_scaler.as_dict())
        artifacts["target_scaler.json"] = scaler_path

    if normalizer is not None:
        normalizer_path = directory / "normalizer.json"
        atomic_write_json(normalizer_path, normalizer.model_dump(mode="json"))
        artifacts["normalizer.json"] = normalizer_path

    calibrator_path = directory / "calibrator.json"
    atomic_write_json(
        calibrator_path,
        calibrator
        if calibrator is not None
        else {
            "status": "unavailable",
            "detail": (
                "no calibration set exists for this bundle; a probability is reported as "
                "unavailable rather than as a precise band"
            ),
        },
    )
    artifacts["calibrator.json"] = calibrator_path

    if support is not None:
        support_path = directory / "support_thresholds.json"
        atomic_write_json(support_path, support.model_dump(mode="json"))
        artifacts["support_thresholds.json"] = support_path

    card_path = directory / _CARD_FILE
    atomic_write_bytes(card_path, model_card.encode("utf-8"))
    artifacts[_CARD_FILE] = card_path

    if training_report is not None:
        report_path = directory / _REPORT_FILE
        atomic_write_json(report_path, training_report)
        artifacts[_REPORT_FILE] = report_path

    hashes = {name: sha256_file(path) for name, path in sorted(artifacts.items())}

    manifest = ModelManifest(
        schema_version=SCHEMA_VERSION,
        id=bundle_id,
        algorithm="SAC",
        weights_hash=hashes[_ACTOR_FILE],
        artifact_hashes=hashes,
        feature_schema_hash=ENERGY_V1.content_hash(),
        normalizer_hash=None if normalizer is None else hashes.get("normalizer.json"),
        rule_family=rule_family,
        reward_revision=reward_revision,
        continuation_controller=continuation_controller,
        training_data_hash=training_data_hash,
        training_code_revision=training_code_revision,
        library_versions=library_versions(),
        supported_scenario_families=supported_scenario_families,
        support_thresholds=support,
        approval_status=approval_status,
        benchmark_report_hash=benchmark_report_hash,
        promotion_policy=promotion_policy or PromotionPolicy(),
        created_at=datetime.now(UTC),
        model_card=_CARD_FILE,
    )

    payload = {
        "schema": BUNDLE_SCHEMA_VERSION,
        "bundle_id": bundle_id,
        "created_at": manifest.created_at.isoformat(),
        "artifact_hashes": hashes,
        "feature_schema_hash": manifest.feature_schema_hash,
        "observation_size": OBSERVATION_SIZE,
        "action_size": ACTION_SIZE,
        "rule_family": rule_family,
        "reward_revision": reward_revision,
        "environment_version": environment_version,
        "continuation_controller": continuation_controller,
        "library_versions": manifest.library_versions,
        "promotion_status": manifest.approval_status.value,
        "promotion_policy": manifest.promotion_policy.model_dump(mode="json"),
        "baseline_identity": baseline_identity,
        "model_manifest": manifest.model_dump(mode="json"),
        "synthetic": True,
        "notice": (
            "Every artifact in this bundle was produced inside a synthetic simulator. "
            "Nothing here is a measured result, a validated model of any real car or "
            "circuit, or a certification of anything."
        ),
    }
    bundle_path = directory / _BUNDLE_FILE
    atomic_write_json(bundle_path, payload)
    return bundle_path


def load_bundle(
    directory: Path,
    *,
    expected_feature_hash: str | None = None,
    expected_rule_family: str | None = None,
    expected_reward_revision: str | None = None,
    expected_environment_version: str | None = None,
    require_approved: bool = False,
    baseline_identity: str = DEFAULT_BASELINE_IDENTITY,
) -> LoadedBundle:
    """Validate and load a bundle, or raise :class:`BundleRejection`.

    A bundle is never loaded by filename alone: the top-level document names
    every artifact with its SHA-256, and each file is re-hashed before anything
    is deserialised.
    """
    directory = Path(directory)
    bundle_path = directory / _BUNDLE_FILE

    def reject(reason: RejectionReason, detail: str) -> BundleRejection:
        return BundleRejection(reason, detail, baseline_identity=baseline_identity)

    if not bundle_path.is_file():
        raise reject(
            RejectionReason.MISSING_BUNDLE_FILE,
            f"{directory} has no {_BUNDLE_FILE}; a directory of weights is not a bundle",
        )
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    if payload.get("schema") != BUNDLE_SCHEMA_VERSION:
        raise reject(
            RejectionReason.UNKNOWN_SCHEMA,
            f"bundle schema {payload.get('schema')!r} is not {BUNDLE_SCHEMA_VERSION!r}",
        )

    hashes: dict[str, str] = dict(payload.get("artifact_hashes") or {})
    if not hashes:
        raise reject(RejectionReason.MISSING_ARTIFACT, "the bundle declares no artifact hashes")

    for name, expected in sorted(hashes.items()):
        path = directory / name
        if not path.is_file():
            raise reject(RejectionReason.MISSING_ARTIFACT, f"declared artifact {name!r} is absent")
        actual = sha256_file(path)
        if actual != expected:
            raise reject(
                RejectionReason.HASH_MISMATCH,
                f"artifact {name!r} hashes to {actual} but the bundle declares {expected}",
            )

    manifest = ModelManifest.model_validate(payload["model_manifest"])

    wanted_feature = expected_feature_hash or ENERGY_V1.content_hash()
    if manifest.feature_schema_hash != wanted_feature:
        raise reject(
            RejectionReason.FEATURE_HASH_MISMATCH,
            (
                f"bundle was trained against feature schema {manifest.feature_schema_hash} but this "
                f"runtime uses {wanted_feature}; the learned contribution is disabled"
            ),
        )
    if expected_rule_family is not None and manifest.rule_family != expected_rule_family:
        raise reject(
            RejectionReason.RULE_FAMILY_MISMATCH,
            f"bundle rule family {manifest.rule_family!r} does not match {expected_rule_family!r}",
        )
    if expected_reward_revision is not None and manifest.reward_revision != expected_reward_revision:
        raise reject(
            RejectionReason.REWARD_REVISION_MISMATCH,
            f"bundle reward revision {manifest.reward_revision!r} does not match "
            f"{expected_reward_revision!r}",
        )
    if (
        expected_environment_version is not None
        and payload.get("environment_version") != expected_environment_version
    ):
        raise reject(
            RejectionReason.ENVIRONMENT_VERSION_MISMATCH,
            f"bundle environment {payload.get('environment_version')!r} does not match "
            f"{expected_environment_version!r}",
        )
    if require_approved and manifest.approval_status is not ApprovalStatus.APPROVED:
        raise reject(
            RejectionReason.NOT_APPROVED,
            f"bundle approval status is {manifest.approval_status.value!r}; a restart resumes from "
            "approved pinned artifacts, never the newest training checkpoint",
        )

    try:
        actor_state = torch.load(directory / _ACTOR_FILE, map_location="cpu", weights_only=True)
    except Exception as exc:
        raise reject(RejectionReason.UNREADABLE_WEIGHTS, f"actor weights would not load: {exc}") from exc

    ensemble = None
    if (directory / "value_ensemble.json").is_file():
        try:
            ensemble = ContinuationEnsemble.load(directory)
        except Exception as exc:
            raise reject(
                RejectionReason.UNREADABLE_WEIGHTS, f"continuation members would not load: {exc}"
            ) from exc

    normalizer = None
    if (directory / "normalizer.json").is_file():
        normalizer = NormalizerManifest.model_validate(
            json.loads((directory / "normalizer.json").read_text(encoding="utf-8"))
        )
    support = manifest.support_thresholds
    calibrator = None
    if (directory / "calibrator.json").is_file():
        calibrator = json.loads((directory / "calibrator.json").read_text(encoding="utf-8"))

    return LoadedBundle(
        directory=directory,
        manifest=manifest,
        feature_manifest=FeatureManifest.model_validate(
            json.loads((directory / "feature_manifest.json").read_text(encoding="utf-8"))
        ),
        action_manifest=json.loads((directory / "action_manifest.json").read_text(encoding="utf-8")),
        actor_state=actor_state,
        ensemble=ensemble,
        normalizer=normalizer,
        support=support,
        calibrator=calibrator,
        model_card=(directory / _CARD_FILE).read_text(encoding="utf-8"),
        training_report=(
            json.loads((directory / _REPORT_FILE).read_text(encoding="utf-8"))
            if (directory / _REPORT_FILE).is_file()
            else None
        ),
        library_versions=dict(payload.get("library_versions") or {}),
        promotion_policy=manifest.promotion_policy,
        baseline_identity=str(payload.get("baseline_identity") or baseline_identity),
    )


def default_model_card(
    *,
    bundle_id: str,
    environment_version: str,
    rule_family: str,
    reward_revision: str,
    continuation_controller: str | None,
    training_status: str,
    limitations: tuple[str, ...] = (),
    architecture_markdown: str | None = None,
    observed_metrics: tuple[str, ...] = (),
    training_code_revision: str | None = None,
    training_data_hash: str | None = None,
) -> str:
    """A model card that states what the bundle is and is not.

    ``architecture_markdown`` and ``observed_metrics`` are rendered verbatim.
    Both sections state their own absence when nothing was supplied, because a
    card missing its parameter count or its measured losses is a card a reader
    would otherwise fill in optimistically.
    """
    lines = [
        f"# Model card — {bundle_id}",
        "",
        "**Synthetic.** Every artifact in this bundle was produced inside a synthetic",
        "simulator whose parameters are invented engineering assumptions. Nothing here",
        "describes a real car, a real circuit or a real race, and nothing here is a",
        "certification, a safety argument or a measured performance claim.",
        "",
        "## Identity",
        "",
        f"- Environment revision: `{environment_version}`",
        f"- Feature schema: `energy-v1` / `{ENERGY_V1.content_hash()}`",
        f"- Rule family: `{rule_family}`",
        f"- Reward revision: `{reward_revision}`",
        f"- Continuation controller: `{continuation_controller or 'none'}`",
        f"- Training code revision: `{training_code_revision or 'not recorded'}`",
        f"- Training data hash: `{training_data_hash or 'not recorded'}`",
        "",
        "## Training status",
        "",
        training_status,
        "",
        "## Architecture and trainable parameters",
        "",
        architecture_markdown
        or (
            "No architecture was described and no parameter count was recorded for this "
            "bundle, which is itself a defect."
        ),
        "",
        "## Observed metrics",
        "",
        "Every value below was recorded by the run that produced these weights. A metric that",
        "is absent is stated as absent and is never replaced by a target or a typical value.",
        "",
    ]
    lines.extend(observed_metrics or ("- No metric was recorded, which is itself a defect.",))
    lines += [
        "",
        "## Intended use",
        "",
        "The actor emits two bounded soft preferences. It does not actuate anything, it",
        "does not override a constraint, and the independent checker's verdict on the",
        "resulting plan is final. With this bundle disabled the system falls back to the",
        f"validated `{DEFAULT_BASELINE_IDENTITY}` path.",
        "",
        "## Limitations",
        "",
    ]
    for note in limitations or ("No limitation was recorded, which is itself a defect.",):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)
