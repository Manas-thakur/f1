"""From a training run to a frozen bundle, without inventing anything.

``train_sac`` produces checkpoints; ``serving.write_bundle`` consumes weights,
manifests and a model card. Nothing joined the two, so a run could not become a
loadable artifact. This module is that join, and its whole design constraint is
that the card it generates must be *readable by someone who then trusts it less
than they did before*.

Concretely:

* the architecture and the parameter counts are read off the reconstructed
  networks (:mod:`afterlap_core.learning.architecture`), never off
  ``net_arch`` in the configuration document;
* the observed metrics are whatever the run recorded, including a failed status
  and a non-finite loss. There is no path that writes a metric the run did not
  produce, and no default that fills an absent metric with a plausible one;
* a smoke run is labelled a smoke run in the bundle id, in the training status,
  in the limitations and in the machine-readable report;
* ``approval_status`` is left at ``unevaluated``. Packaging is not promotion,
  and a bundle written here contributes nothing until the frozen protocol says
  otherwise.

The ``training_data_hash`` deserves a note. On-policy reinforcement learning
has no dataset file to hash: the transitions are generated. Hashing the
generator is the honest substitute, so the value here covers the environment
configuration, the scenario selection, the seeds, the reward revision and the
step budget. It identifies *what would be regenerated*, and the report says so
in those words rather than implying a fixed corpus.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from afterlap_contracts import ApprovalStatus, ModelManifest, NormalizerManifest, SupportThresholds

from ..feature_manifest import ENERGY_V1
from ..paths import Paths, sha256_json
from .architecture import ArchitectureReport, describe_ensemble, describe_sac
from .checkpoints import CheckpointManifest, verify_checkpoint
from .config import EnvConfig, load_env_config
from .serving import DEFAULT_BASELINE_IDENTITY, default_model_card, library_versions, write_bundle
from .value import ContinuationEnsemble

__all__ = [
    "PackagedBundle",
    "PackagingError",
    "TrainingEvidence",
    "code_revision",
    "package_checkpoint",
    "training_data_hash",
]

_SMOKE_STATUS = (
    "**Smoke run, not a trained model.** This bundle was packaged from a short job whose only "
    "purpose was to prove that gradient steps run, losses stay finite, checkpoints round-trip and "
    "episodes complete. It has no held-out evaluation, it has not been compared against the "
    "baseline on the promotion benchmark, and quoting it as a trained or competitive model would "
    "be a fabricated result."
)

_UNEVALUATED_STATUS = (
    "**Trained, not evaluated for promotion.** Gradient steps ran to the recorded step count with "
    "finite losses. No held-out benchmark report is attached to this bundle, so no benefit over the "
    "baseline has been measured and no promotion gate has been assessed."
)

_FAILED_STATUS = (
    "**Training did not complete.** The recorded status is not `completed`. The weights in this "
    "bundle are whatever the last checkpoint held; they are packaged so the failure is inspectable, "
    "not because they are usable."
)


class PackagingError(RuntimeError):
    """A checkpoint could not be packaged into a bundle."""


@dataclass(frozen=True, slots=True)
class TrainingEvidence:
    """The observed record of one training run. Absent means absent."""

    run_id: str
    status: str
    requested_timesteps: int
    completed_timesteps: int
    wall_clock_s: float | None = None
    transitions_per_second: float | None = None
    seeds: tuple[int, ...] = ()
    scenario_id: str | None = None
    is_smoke_run: bool = False
    failure_detail: str | None = None
    hardware: str | None = None
    losses: dict[str, Any] = field(default_factory=dict)
    training_episode_returns: dict[str, Any] = field(default_factory=dict)
    deterministic_evaluation_returns: tuple[float, ...] = ()
    deterministic_evaluation_detail: str | None = None
    benchmark_report_hash: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "requested_timesteps": self.requested_timesteps,
            "completed_timesteps": self.completed_timesteps,
            "wall_clock_s": self.wall_clock_s,
            "transitions_per_second": self.transitions_per_second,
            "seeds": list(self.seeds),
            "scenario_id": self.scenario_id,
            "is_smoke_run": self.is_smoke_run,
            "failure_detail": self.failure_detail,
            "hardware": self.hardware,
            "losses": self.losses,
            "training_episode_returns": self.training_episode_returns,
            "deterministic_evaluation_returns": list(self.deterministic_evaluation_returns),
            "deterministic_evaluation_detail": self.deterministic_evaluation_detail,
            "benchmark_report_hash": self.benchmark_report_hash,
        }

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    def training_status_text(self) -> str:
        if self.is_smoke_run:
            return _SMOKE_STATUS
        if not self.completed:
            return _FAILED_STATUS
        if self.benchmark_report_hash is None:
            return _UNEVALUATED_STATUS
        return (
            "**Trained and evaluated.** Gradient steps ran to the recorded step count and a "
            f"held-out benchmark report (`{self.benchmark_report_hash}`) is attached. Promotion "
            "remains a separate frozen decision."
        )


@dataclass(frozen=True, slots=True)
class PackagedBundle:
    """Where the bundle landed and what it declares."""

    directory: Path
    bundle_id: str
    manifest: ModelManifest
    architecture: ArchitectureReport
    evidence: TrainingEvidence
    training_report: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "directory": str(self.directory),
            "bundle_id": self.bundle_id,
            "weights_hash": self.manifest.weights_hash,
            "approval_status": self.manifest.approval_status.value,
            "optimiser_updated_parameters": self.architecture.optimiser_updated_parameters,
            "trainable_parameters": self.architecture.trainable_parameters,
            "total_parameters": self.architecture.total_parameters,
            "training_report": self.training_report,
        }


def code_revision(root: Path | None = None) -> str:
    """The training code revision, or an explicit statement that it is unknown.

    A dirty tree is reported as dirty. A bundle whose weights came from edited,
    uncommitted code is reproducible only against that working tree, and hiding
    that behind a clean commit id would make the manifest wrong.
    """
    workspace = Path(root) if root is not None else Path(__file__).resolve().parents[4]
    try:
        head = subprocess.run(  # noqa: S603
            ["git", "-C", str(workspace), "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=15.0,
            check=False,
        )
        if head.returncode != 0:
            return "unknown:not-a-git-checkout"
        revision = head.stdout.strip()
        status = subprocess.run(  # noqa: S603
            ["git", "-C", str(workspace), "status", "--porcelain"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=15.0,
            check=False,
        )
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else True
        return f"{revision}-dirty" if dirty else revision
    except (OSError, subprocess.SubprocessError):
        return "unknown:git-unavailable"


def training_data_hash(
    *,
    env_config: EnvConfig,
    scenario_id: str | None,
    seeds: tuple[int, ...],
    total_timesteps: int,
    reward_revision: str,
) -> str:
    """Hash the transition *generator*, because there is no dataset file.

    Two runs sharing this hash would regenerate the same distribution of
    transitions given the same library versions; it is not a hash of stored
    data and must not be described as one.
    """
    return sha256_json(
        {
            "kind": "generated-transitions",
            "environment_version": env_config.environment_version,
            "env_config_hash": env_config.content_hash,
            "feature_schema_hash": ENERGY_V1.content_hash(),
            "scenario_id": scenario_id or "mixed",
            "seeds": sorted(int(s) for s in seeds),
            "total_timesteps": int(total_timesteps),
            "reward_revision": reward_revision,
        }
    )


def _load_run_manifest(run_directory: Path) -> dict[str, Any]:
    path = run_directory / "run_manifest.json"
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def evidence_from_run(
    run_directory: Path,
    checkpoint: CheckpointManifest,
    *,
    deterministic_returns: tuple[float, ...] = (),
    deterministic_detail: str | None = None,
    benchmark_report_hash: str | None = None,
) -> TrainingEvidence:
    """Read the run's own record. Nothing is inferred when a field is absent."""
    manifest = _load_run_manifest(run_directory)
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else checkpoint.metrics
    metrics = metrics if isinstance(metrics, dict) else {}
    losses = metrics.get("optimiser") if isinstance(metrics.get("optimiser"), dict) else {}
    returns = metrics.get("episode_return") if isinstance(metrics.get("episode_return"), dict) else {}
    seeds = checkpoint.seeds or tuple(int(s) for s in manifest.get("seeds", ()) or ())
    if not seeds and manifest.get("seed") is not None:
        seeds = (int(manifest["seed"]),)
    return TrainingEvidence(
        run_id=checkpoint.run_id,
        status=str(result.get("status") or manifest.get("status") or "unknown"),
        requested_timesteps=int(
            result.get("requested_timesteps") or manifest.get("requested_timesteps") or 0
        ),
        completed_timesteps=int(result.get("completed_timesteps") or checkpoint.step_count),
        wall_clock_s=result.get("wall_clock_s"),
        transitions_per_second=result.get("transitions_per_second"),
        seeds=tuple(seeds),
        scenario_id=manifest.get("scenario_id"),
        is_smoke_run=bool(result.get("is_smoke_run") or manifest.get("is_smoke_run") or False),
        failure_detail=result.get("failure_detail"),
        hardware=result.get("hardware") or manifest.get("hardware"),
        losses=dict(losses),
        training_episode_returns=dict(returns),
        deterministic_evaluation_returns=deterministic_returns,
        deterministic_evaluation_detail=deterministic_detail,
        benchmark_report_hash=benchmark_report_hash,
    )


def _metric_lines(evidence: TrainingEvidence) -> list[str]:
    lines = [
        f"- Status: `{evidence.status}`",
        (
            f"- Transitions: {evidence.completed_timesteps:,} completed of "
            f"{evidence.requested_timesteps:,} requested"
        ),
        f"- Seeds: {list(evidence.seeds) or 'not recorded'}",
        f"- Scenario selection: `{evidence.scenario_id or 'not recorded'}`",
    ]
    if evidence.wall_clock_s is not None:
        rate = (
            f" ({evidence.transitions_per_second:.1f} transitions/s)"
            if evidence.transitions_per_second is not None
            else ""
        )
        lines.append(f"- Wall clock: {evidence.wall_clock_s:.1f} s{rate}")
    if evidence.losses:
        for name in sorted(evidence.losses):
            lines.append(f"- Observed `{name}`: {evidence.losses[name]}")
    else:
        lines.append(
            "- Observed losses: none recorded. A run that logged no loss did not take a"
            " gradient step this reader can verify."
        )
    if evidence.training_episode_returns:
        lines.append(f"- Training episode returns: {evidence.training_episode_returns}")
    if evidence.deterministic_evaluation_returns:
        values = list(evidence.deterministic_evaluation_returns)
        mean = sum(values) / len(values)
        lines.append(
            f"- Deterministic evaluation returns ({len(values)} episode(s)): "
            f"mean {mean:.4f}, values {[round(v, 4) for v in values]}"
        )
    else:
        lines.append(
            "- Deterministic evaluation: not run for this bundle. "
            + (evidence.deterministic_evaluation_detail or "No reason was recorded.")
        )
    if evidence.failure_detail:
        lines.append(f"- Failure detail: {evidence.failure_detail}")
    if evidence.hardware:
        lines.append(f"- Hardware: {evidence.hardware}")
    return lines


def _limitations(evidence: TrainingEvidence, ensemble: ContinuationEnsemble | None) -> tuple[str, ...]:
    notes: list[str] = [
        (
            "Every configuration behind these weights is a synthetic engineering assumption. "
            "No quantity here was measured on a real car, circuit or race."
        ),
        (
            "The actor emits two bounded soft preferences that warm-start a solve. It cannot "
            "relax a modelled constraint, and the independent checker's verdict on the "
            "resulting plan is final."
        ),
    ]
    if evidence.is_smoke_run:
        notes.append(
            "This is a smoke run. Its step count is orders of magnitude below the declared "
            "training budget and its behaviour should be treated as an untrained initialisation."
        )
    if not evidence.completed:
        notes.append(f"Training status is {evidence.status!r}, not 'completed'.")
    if evidence.benchmark_report_hash is None:
        notes.append(
            "No held-out benchmark report is attached, so no benefit over the baseline has been "
            "measured and the promotion gates have not been assessed."
        )
    if len(evidence.seeds) < 2:
        notes.append(
            f"Only {len(evidence.seeds)} training seed(s) were recorded. The promotion protocol "
            "requires multiple seeds before a difference can be attributed to the method."
        )
    if ensemble is None:
        notes.append(
            "No continuation ensemble is bundled, so learned reranking is unavailable and the "
            "planner uses its analytic terminal term."
        )
    elif not ensemble.support.frozen_before_final_test:
        notes.append(
            "The bundled continuation support thresholds are not frozen before a final test, so "
            "the learned contribution stays disabled under the serving gate."
        )
    return tuple(notes)


def package_checkpoint(
    checkpoint_directory: Path,
    *,
    bundle_directory: Path | None = None,
    bundle_id: str | None = None,
    rule_family: str,
    env_config: EnvConfig | None = None,
    ensemble: ContinuationEnsemble | None = None,
    calibrator: dict[str, Any] | None = None,
    normalizer: NormalizerManifest | None = None,
    support: SupportThresholds | None = None,
    supported_scenario_families: tuple[str, ...] = (),
    deterministic_returns: tuple[float, ...] = (),
    deterministic_detail: str | None = None,
    benchmark_report_hash: str | None = None,
    paths: Paths | None = None,
    baseline_identity: str = DEFAULT_BASELINE_IDENTITY,
) -> PackagedBundle:
    """Package a verified checkpoint into a frozen, loadable bundle.

    The checkpoint is re-hashed before anything is read from it. The bundle is
    written with ``approval_status=unevaluated``; this function has no argument
    that would let a caller declare it approved.
    """
    checkpoint_directory = Path(checkpoint_directory)
    manifest = verify_checkpoint(checkpoint_directory)
    settings = env_config or load_env_config()

    if manifest.feature_hash != ENERGY_V1.content_hash():
        raise PackagingError(
            f"checkpoint feature schema {manifest.feature_hash} does not match the current "
            f"{ENERGY_V1.content_hash()}; packaging it would mislabel the bundle"
        )

    try:
        from stable_baselines3 import SAC
    except ImportError as exc:
        raise PackagingError(
            f"the learning extra is not installed, so a checkpoint cannot be packaged: {exc}"
        ) from exc

    model_path = checkpoint_directory / "model.zip"
    if not model_path.is_file():
        raise PackagingError(f"{checkpoint_directory} has no model.zip to package")
    try:
        model = SAC.load(str(model_path), env=None, device="cpu")
    except Exception as exc:
        raise PackagingError(f"the checkpointed model would not load: {exc}") from exc

    architecture = describe_sac(model)
    actor_state = {
        key: value.detach().cpu().clone() for key, value in model.policy.actor.state_dict().items()
    }

    evidence = evidence_from_run(
        checkpoint_directory.parent.parent,
        manifest,
        deterministic_returns=deterministic_returns,
        deterministic_detail=deterministic_detail,
        benchmark_report_hash=benchmark_report_hash,
    )

    ensemble_architecture = describe_ensemble(ensemble) if ensemble is not None else None
    identifier = bundle_id or (
        f"{'smoke' if evidence.is_smoke_run else 'sac'}/{settings.environment_version}/"
        f"{manifest.run_id}/{manifest.step_count}"
    )
    revision = code_revision()
    data_hash = training_data_hash(
        env_config=settings,
        scenario_id=evidence.scenario_id,
        seeds=evidence.seeds,
        total_timesteps=evidence.completed_timesteps,
        reward_revision=manifest.reward_revision,
    )

    training_report: dict[str, Any] = {
        "schema": "afterlap.learning.training_report/1",
        "generated_at": datetime.now(UTC).isoformat(),
        "bundle_id": identifier,
        "checkpoint": {
            "directory": checkpoint_directory.name,
            "run_id": manifest.run_id,
            "step_count": manifest.step_count,
            "artifact_hashes": manifest.artifact_hashes,
            "env_config_hash": manifest.env_config_hash,
            "algorithm_config": manifest.algorithm_config,
        },
        "identity": {
            "environment_version": settings.environment_version,
            "feature_schema_hash": ENERGY_V1.content_hash(),
            "reward_revision": manifest.reward_revision,
            "rule_family": rule_family,
            "training_code_revision": revision,
            "training_data_hash": data_hash,
            "training_data_kind": (
                "transitions generated by the simulator-backed environment; this hash identifies "
                "the generator configuration, not a stored dataset"
            ),
        },
        "architecture": {
            "actor_critic": architecture.as_dict(),
            "continuation_ensemble": (
                None if ensemble_architecture is None else ensemble_architecture.as_dict()
            ),
        },
        "observed": evidence.as_dict(),
        "library_versions": library_versions(),
        "approval_status": ApprovalStatus.UNEVALUATED.value,
        "promotion": "not assessed by packaging; promotion is a separate frozen decision",
    }

    card = default_model_card(
        bundle_id=identifier,
        environment_version=settings.environment_version,
        rule_family=rule_family,
        reward_revision=manifest.reward_revision,
        continuation_controller=None if ensemble is None else ensemble.continuation_controller,
        training_status=evidence.training_status_text(),
        limitations=_limitations(evidence, ensemble),
        architecture_markdown=(
            architecture.as_markdown()
            + ("" if ensemble_architecture is None else "\n" + ensemble_architecture.as_markdown())
        ),
        observed_metrics=tuple(_metric_lines(evidence)),
        training_code_revision=revision,
        training_data_hash=data_hash,
    )

    resolved = (
        Path(bundle_directory)
        if bundle_directory is not None
        else (paths or Paths.default()).ensure().models / "bundles" / manifest.run_id
    )
    manifest_path = write_bundle(
        resolved,
        bundle_id=identifier,
        actor_state=actor_state,
        ensemble=ensemble,
        rule_family=rule_family,
        reward_revision=manifest.reward_revision,
        environment_version=settings.environment_version,
        continuation_controller=None if ensemble is None else ensemble.continuation_controller,
        training_code_revision=revision,
        training_data_hash=data_hash,
        supported_scenario_families=supported_scenario_families,
        support=support if support is not None else (None if ensemble is None else ensemble.support),
        normalizer=normalizer,
        calibrator=calibrator,
        model_card=card,
        training_report=training_report,
        approval_status=ApprovalStatus.UNEVALUATED,
        benchmark_report_hash=benchmark_report_hash,
        baseline_identity=baseline_identity,
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return PackagedBundle(
        directory=manifest_path.parent,
        bundle_id=identifier,
        manifest=ModelManifest.model_validate(payload["model_manifest"]),
        architecture=architecture,
        evidence=evidence,
        training_report=training_report,
    )
