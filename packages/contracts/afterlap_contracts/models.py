"""Model bundles, feature manifests and experiment/evaluation records.

A bundle is loadable only when every hash validates. A filename is never
sufficient evidence of what a set of weights contains.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from .base import Contract, VersionedContract
from .enums import ApprovalStatus, CalibrationStatus, FailureCategory, JobStatus


class FeatureField(Contract):
    """One entry of the frozen observation encoding."""

    index: int = Field(ge=0)
    name: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    offset: float = Field(description="Applied before scale: (raw - offset) / scale.")
    scale: float = Field(description="Non-zero physical scale in the field's own unit.")
    clip_low: float = -5.0
    clip_high: float = 5.0
    maskable: bool = True
    provenance_note: str | None = None

    @model_validator(mode="after")
    def _usable_scale(self) -> FeatureField:
        if self.scale == 0.0:
            raise ValueError(f"feature {self.name} has zero scale")
        if self.clip_high <= self.clip_low:
            raise ValueError(f"feature {self.name} has an empty clip range")
        return self


class FeatureManifest(VersionedContract):
    """Frozen feature contract. Any change here requires retraining."""

    revision: str = Field(min_length=1, description="e.g. 'energy-v1'.")
    value_count: int = Field(gt=0)
    observation_size: int = Field(gt=0, description="values + masks.")
    fields: tuple[FeatureField, ...] = Field(min_length=1)
    action_size: int = Field(gt=0)
    policy_interval_s: float = Field(gt=0.0)
    preference_window_s: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _indices_are_dense(self) -> FeatureManifest:
        if len(self.fields) != self.value_count:
            raise ValueError(f"expected {self.value_count} fields, got {len(self.fields)}")
        if self.observation_size != 2 * self.value_count:
            raise ValueError("observation size must be values plus an equal-length mask block")
        indices = [f.index for f in self.fields]
        if indices != list(range(self.value_count)):
            raise ValueError("feature indices must be dense and ordered from zero")
        names = [f.name for f in self.fields]
        if len(set(names)) != len(names):
            raise ValueError("duplicate feature names")
        return self

    @property
    def feature_hash(self) -> str:
        return self.content_hash()


class RewardManifest(Contract):
    """Frozen reward revision (objective-v1)."""

    revision: str = Field(min_length=1)
    elapsed_second_penalty: float = Field(ge=0.0)
    instruction_change_penalty: float = Field(ge=0.0)
    finish_position_penalty: float = Field(ge=0.0)
    terminal_failure_penalty: float = Field(ge=0.0)
    potential_reference_time_scale_s: float = Field(gt=0.0)
    gamma: float = Field(gt=0.0, lt=1.0)
    maximum_supported_field_size: int = Field(gt=0)
    maximum_charged_instruction_changes_per_s: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _failure_penalty_dominates(self) -> RewardManifest:
        """Reproduce the bound argued in ENVIRONMENT_AND_FEATURES.md.

        The failure penalty must exceed the discounted running cost plus the
        worst finish-position cost, or deliberate DNF becomes profitable.
        """
        running_bound = (
            self.elapsed_second_penalty
            + self.instruction_change_penalty * self.maximum_charged_instruction_changes_per_s
        ) / (1.0 - self.gamma)
        position_bound = self.finish_position_penalty * (self.maximum_supported_field_size - 1)
        if self.terminal_failure_penalty <= running_bound + position_bound:
            raise ValueError(
                "terminal_failure_penalty must exceed the discounted running-cost bound "
                f"({running_bound:.1f}) plus maximum finish-position cost ({position_bound:.1f})"
            )
        return self


class NormalizerManifest(Contract):
    """Target scaler for the continuation-return ensemble."""

    mean: float
    std: float = Field(gt=0.0)
    fitted_on: str = Field(min_length=1, description="Training split identifier.")


class SupportThresholds(Contract):
    """Frozen gates that disable learned scoring outside its validated regime."""

    max_ensemble_disagreement: float = Field(gt=0.0)
    max_clip_fraction: float = Field(ge=0.0, le=1.0)
    min_known_mask_fraction: float = Field(ge=0.0, le=1.0)
    frozen_before_final_test: bool = False


class BenchmarkComparison(Contract):
    """One paired controller comparison with its uncertainty."""

    controller: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    difference_mean: float
    ci_low: float
    ci_high: float
    coverage: float = Field(gt=0.0, lt=1.0)
    scenario_count: int = Field(ge=0)
    seed_count: int = Field(ge=0)
    favours_controller: bool

    @model_validator(mode="after")
    def _interval_contains_mean(self) -> BenchmarkComparison:
        if not (self.ci_low <= self.difference_mean <= self.ci_high):
            raise ValueError("confidence interval does not contain its own point estimate")
        return self


class CalibrationReport(Contract):
    """Reliability evidence for one event definition."""

    event_definition: str = Field(min_length=1)
    status: CalibrationStatus
    brier_score: float | None = Field(default=None, ge=0.0)
    log_loss: float | None = Field(default=None, ge=0.0)
    bin_counts: tuple[int, ...] = ()
    bin_predicted: tuple[float, ...] = ()
    bin_observed: tuple[float, ...] = ()
    support_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _bins_align(self) -> CalibrationReport:
        sizes = {len(self.bin_counts), len(self.bin_predicted), len(self.bin_observed)}
        if len(sizes) > 1:
            raise ValueError("calibration bin arrays have inconsistent lengths")
        if self.status is CalibrationStatus.CALIBRATED and self.support_count == 0:
            raise ValueError("a calibrated report requires supporting samples")
        return self


class PromotionPolicy(Contract):
    """Thresholds frozen *before* the final test is opened."""

    enabled: bool = False
    minimum_benefit: float | None = None
    benefit_metric: str | None = None
    downside_noninferiority_limit: float | None = None
    latency_limit_ms: float | None = None
    frozen_at: datetime | None = None
    rationale: str | None = None

    @model_validator(mode="after")
    def _enabled_requires_thresholds(self) -> PromotionPolicy:
        if self.enabled:
            missing = [
                name
                for name, value in (
                    ("minimum_benefit", self.minimum_benefit),
                    ("benefit_metric", self.benefit_metric),
                    ("downside_noninferiority_limit", self.downside_noninferiority_limit),
                    ("latency_limit_ms", self.latency_limit_ms),
                    ("frozen_at", self.frozen_at),
                )
                if value is None
            ]
            if missing:
                raise ValueError(f"promotion enabled without frozen thresholds: {missing}")
        return self


class BenchmarkReport(VersionedContract):
    """Machine-readable held-out result. Absent evidence stays absent."""

    id: str = Field(min_length=1)
    created_at: datetime
    evaluator_version: str = Field(min_length=1)
    metrics_version: str = Field(min_length=1)
    scenario_family: str = Field(min_length=1)
    scenario_count: int = Field(ge=0)
    seed_count: int = Field(ge=0)
    comparisons: tuple[BenchmarkComparison, ...] = ()
    calibration: tuple[CalibrationReport, ...] = ()
    latency_p50_ms: float | None = Field(default=None, ge=0.0)
    latency_p95_ms: float | None = Field(default=None, ge=0.0)
    latency_p99_ms: float | None = Field(default=None, ge=0.0)
    withdrawn_decisions: int = Field(default=0, ge=0)
    modelled_violations: int = Field(default=0, ge=0)
    failures_by_category: dict[FailureCategory, int] = Field(default_factory=dict)
    hardware: str | None = None
    rerun_command: str | None = None
    notes: tuple[str, ...] = ()


class ModelManifest(VersionedContract):
    """Frozen bundle descriptor. ``approval_status`` never defaults to approved."""

    id: str = Field(min_length=1)
    algorithm: str = Field(min_length=1)
    weights_hash: str = Field(min_length=1)
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    feature_schema_hash: str = Field(min_length=1)
    normalizer_hash: str | None = None
    rule_family: str = Field(min_length=1)
    reward_revision: str = Field(min_length=1)
    continuation_controller: str | None = None
    training_data_hash: str | None = None
    training_code_revision: str | None = None
    library_versions: dict[str, str] = Field(default_factory=dict)
    supported_scenario_families: tuple[str, ...] = ()
    support_thresholds: SupportThresholds | None = None
    approval_status: ApprovalStatus = ApprovalStatus.UNEVALUATED
    benchmark_report_hash: str | None = None
    promotion_policy: PromotionPolicy = PromotionPolicy()
    created_at: datetime
    model_card: str | None = None

    @model_validator(mode="after")
    def _approval_needs_evidence(self) -> ModelManifest:
        if self.approval_status is ApprovalStatus.APPROVED:
            if self.benchmark_report_hash is None:
                raise ValueError("an approved bundle must reference its benchmark report")
            if not self.promotion_policy.enabled:
                raise ValueError("an approved bundle requires an enabled, frozen promotion policy")
        return self


class ExperimentManifest(VersionedContract):
    """Immutable definition of a branch or benchmark experiment."""

    id: str = Field(min_length=1)
    snapshot_hash: str = Field(min_length=1)
    treatment_ids: tuple[str, ...] = Field(min_length=1)
    opponent_policy_hashes: dict[str, str] = Field(default_factory=dict)
    disturbance_seed_ids: tuple[int, ...] = Field(min_length=1)
    evaluator_version: str = Field(min_length=1)
    metrics_version: str = Field(min_length=1)
    evaluation_horizon_s: float = Field(gt=0.0)
    checkpoint_ids: tuple[str, ...] = ()
    created_at: datetime


class ExperimentJob(VersionedContract):
    """Trackable batch job. Partial results are labelled, never aggregated silently."""

    id: str = Field(min_length=1)
    manifest_hash: str = Field(min_length=1)
    status: JobStatus
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    report_hash: str | None = None
    failure: str | None = None
    partial_results: bool = False

    @model_validator(mode="after")
    def _terminal_states_are_consistent(self) -> ExperimentJob:
        if self.status is JobStatus.COMPLETED and self.report_hash is None:
            raise ValueError("a completed job must reference its report")
        if self.status is JobStatus.FAILED and not self.failure:
            raise ValueError("a failed job must record why")
        if self.status is JobStatus.CANCELLED and self.progress > 0.0 and not self.partial_results:
            raise ValueError("a cancelled job with progress must label its partial results")
        return self


__all__ = [
    "BenchmarkComparison",
    "BenchmarkReport",
    "CalibrationReport",
    "ExperimentJob",
    "ExperimentManifest",
    "FeatureField",
    "FeatureManifest",
    "ModelManifest",
    "NormalizerManifest",
    "PromotionPolicy",
    "RewardManifest",
    "SupportThresholds",
]
