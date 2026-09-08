"""Promotion, and the refusals that are its default.

``configs/benchmarks/promotion.yaml`` is coordinator-owned and **read only**.
This module never writes it and never supplies a missing threshold: a value
chosen after seeing a result is not a deployment gate, so an absent threshold is
a refusal rather than a default.

:func:`promote_bundle` refuses when

* the thresholds are missing or not frozen,
* no benchmark report is supplied,
* the report does not carry the declared primary comparison,
* the benefit is below the frozen margin, or its interval includes zero,
* a downside, latency, withdrawal-rate or violation gate is breached,
* the required evidence is not present,
* the feature schema hash or the rule family disagrees.

A refusal is a first-class result: :class:`PromotionDecision` carries every
reason, leaves the baseline enabled and leaves the candidate inspectable.
Failing promotion after a real experiment is a valid research outcome; it is not
a build failure and it is not an error to be worked around.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from afterlap_contracts import ApprovalStatus, BenchmarkReport, ModelManifest, PromotionPolicy

from ..config import load_config
from ..paths import Paths, sha256_json
from .serving import DEFAULT_BASELINE_IDENTITY

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "FrozenPromotionPolicy",
    "PromotionDecision",
    "RefusalCode",
    "load_promotion_policy",
    "promote_bundle",
]


class RefusalCode:
    """String constants, kept plain so a report can quote them verbatim."""

    THRESHOLDS_MISSING = "thresholds_missing_or_not_frozen"
    REPORT_ABSENT = "benchmark_report_absent"
    COMPARISON_ABSENT = "declared_primary_comparison_absent"
    BENEFIT_BELOW_MARGIN = "benefit_below_frozen_margin"
    INTERVAL_INCLUDES_ZERO = "benefit_interval_includes_zero"
    DOWNSIDE_LIMIT = "downside_noninferiority_limit_breached"
    LATENCY_LIMIT = "latency_limit_breached"
    WITHDRAWAL_RATE = "withdrawn_decision_rate_exceeded"
    MODELLED_VIOLATIONS = "modelled_violations_present"
    FEATURE_HASH_MISMATCH = "feature_schema_hash_mismatch"
    RULE_FAMILY_MISMATCH = "rule_family_mismatch"
    EVIDENCE_MISSING = "required_evidence_missing"
    SCENARIO_COUNT = "insufficient_independent_test_scenarios"
    SEED_COUNT = "insufficient_training_seeds"


@dataclass(frozen=True, slots=True)
class FrozenPromotionPolicy:
    """The frozen document, exactly as read. Nothing here is defaulted."""

    policy_id: str
    content_hash: str
    enabled: bool
    frozen_at: datetime | None
    benefit_metric: str | None
    minimum_benefit: float | None
    require_interval_excludes_zero: bool
    interval_coverage: float | None
    downside_noninferiority_limit: float | None
    downside_metric: str | None
    latency_limit_ms: float | None
    latency_percentile: int | None
    max_withdrawn_decision_rate: float | None
    max_modelled_violations: int | None
    evidence_required: tuple[str, ...]
    refusal_conditions: tuple[str, ...]
    rationale: str | None
    minimum_scenarios: int | None = None
    minimum_seeds: int | None = None

    @property
    def thresholds_frozen(self) -> bool:
        """True only when every gate the policy declares actually has a value."""
        return (
            self.frozen_at is not None
            and self.benefit_metric is not None
            and self.minimum_benefit is not None
            and self.downside_noninferiority_limit is not None
            and self.latency_limit_ms is not None
        )

    def as_contract(self) -> PromotionPolicy:
        """The contract form. It refuses ``enabled`` without frozen thresholds."""
        return PromotionPolicy(
            enabled=self.enabled and self.thresholds_frozen,
            minimum_benefit=self.minimum_benefit,
            benefit_metric=self.benefit_metric,
            downside_noninferiority_limit=self.downside_noninferiority_limit,
            latency_limit_ms=self.latency_limit_ms,
            frozen_at=self.frozen_at,
            rationale=self.rationale,
        )


def _parse_int_from_evidence(evidence: tuple[str, ...], prefix: str, suffix: str) -> int | None:
    """Read ``at_least_100_independent_test_scenarios`` style requirements."""
    for entry in evidence:
        if entry.startswith(prefix) and entry.endswith(suffix):
            middle = entry[len(prefix) : len(entry) - len(suffix)]
            digits = "".join(ch for ch in middle if ch.isdigit())
            if digits:
                return int(digits)
    return None


def load_promotion_policy(policy_id: str = "promotion", paths: Paths | None = None) -> FrozenPromotionPolicy:
    """Read the frozen policy. This function never writes and never defaults."""
    document = load_config("benchmarks", policy_id, paths)
    benefit: dict[str, Any] = dict(document.get("benefit") or {})
    non_inferiority: dict[str, Any] = dict(document.get("non_inferiority") or {})
    frozen_at_raw = document.get("frozen_at")
    frozen_at = None
    if frozen_at_raw is not None:
        frozen_at = (
            frozen_at_raw
            if isinstance(frozen_at_raw, datetime)
            else datetime.fromisoformat(str(frozen_at_raw))
        )
    evidence = tuple(str(e) for e in (document.get("evidence_required") or ()))
    return FrozenPromotionPolicy(
        policy_id=str(document.get("id", policy_id)),
        content_hash=sha256_json(document),
        enabled=bool(document.get("enabled", False)),
        frozen_at=frozen_at,
        benefit_metric=None if benefit.get("metric") is None else str(benefit["metric"]),
        minimum_benefit=(
            None if benefit.get("minimum_benefit") is None else float(benefit["minimum_benefit"])
        ),
        require_interval_excludes_zero=bool(benefit.get("require_interval_excludes_zero", False)),
        interval_coverage=(
            None if benefit.get("interval_coverage") is None else float(benefit["interval_coverage"])
        ),
        downside_noninferiority_limit=(
            None
            if non_inferiority.get("downside_noninferiority_limit") is None
            else float(non_inferiority["downside_noninferiority_limit"])
        ),
        downside_metric=(
            None
            if non_inferiority.get("downside_metric") is None
            else str(non_inferiority["downside_metric"])
        ),
        latency_limit_ms=(
            None
            if non_inferiority.get("latency_limit_ms") is None
            else float(non_inferiority["latency_limit_ms"])
        ),
        latency_percentile=(
            None
            if non_inferiority.get("latency_percentile") is None
            else int(non_inferiority["latency_percentile"])
        ),
        max_withdrawn_decision_rate=(
            None
            if non_inferiority.get("max_withdrawn_decision_rate") is None
            else float(non_inferiority["max_withdrawn_decision_rate"])
        ),
        max_modelled_violations=(
            None
            if non_inferiority.get("max_modelled_violations") is None
            else int(non_inferiority["max_modelled_violations"])
        ),
        evidence_required=evidence,
        refusal_conditions=tuple(str(r) for r in (document.get("refusal_conditions") or ())),
        rationale=None if document.get("rationale") is None else str(document["rationale"]),
        minimum_scenarios=_parse_int_from_evidence(evidence, "at_least_", "_independent_test_scenarios"),
        minimum_seeds=_parse_int_from_evidence(evidence, "at_least_", "_training_seeds"),
    )


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """The decision and every reason behind it. A refusal is a valid result."""

    promoted: bool
    bundle_id: str
    policy_id: str
    policy_hash: str
    baseline_identity: str
    refusals: tuple[str, ...] = ()
    detail: tuple[str, ...] = ()
    report_hash: str | None = None
    evaluated_at: datetime | None = None
    satisfied_gates: tuple[str, ...] = field(default=())

    @property
    def baseline_enabled(self) -> bool:
        """The validated baseline stays enabled whenever promotion is refused."""
        return not self.promoted

    def as_dict(self) -> dict[str, Any]:
        return {
            "promoted": self.promoted,
            "bundle_id": self.bundle_id,
            "policy_id": self.policy_id,
            "policy_hash": self.policy_hash,
            "baseline_identity": self.baseline_identity,
            "baseline_enabled": self.baseline_enabled,
            "refusals": list(self.refusals),
            "detail": list(self.detail),
            "report_hash": self.report_hash,
            "evaluated_at": None if self.evaluated_at is None else self.evaluated_at.isoformat(),
            "satisfied_gates": list(self.satisfied_gates),
        }


def promote_bundle(
    manifest: ModelManifest,
    report: BenchmarkReport | None,
    *,
    policy: FrozenPromotionPolicy | None = None,
    paths: Paths | None = None,
    expected_feature_hash: str | None = None,
    expected_rule_family: str | None = None,
    evidence_supplied: tuple[str, ...] = (),
    baseline_identity: str = DEFAULT_BASELINE_IDENTITY,
    candidate_path: Path | None = None,
) -> PromotionDecision:
    """Decide whether a candidate may be promoted.

    Refusal is the default. A candidate is promoted only when every frozen gate
    is present *and* satisfied by supplied evidence.
    """
    frozen = policy or load_promotion_policy(paths=paths)
    refusals: list[str] = []
    detail: list[str] = []
    satisfied: list[str] = []

    if not frozen.thresholds_frozen:
        refusals.append(RefusalCode.THRESHOLDS_MISSING)
        detail.append(
            "the promotion policy does not carry a frozen benefit margin, downside limit, "
            "latency limit and freeze timestamp; a threshold chosen now would not be a gate"
        )

    if report is None:
        refusals.append(RefusalCode.REPORT_ABSENT)
        detail.append("no benchmark report was supplied; there is no evidence to evaluate")
        return PromotionDecision(
            promoted=False,
            bundle_id=manifest.id,
            policy_id=frozen.policy_id,
            policy_hash=frozen.content_hash,
            baseline_identity=baseline_identity,
            refusals=tuple(refusals),
            detail=tuple(detail),
            report_hash=None,
            satisfied_gates=tuple(satisfied),
        )

    report_hash = sha256_json(report.model_dump(mode="json"))

    wanted_feature = expected_feature_hash
    if wanted_feature is None:
        from ..feature_manifest import ENERGY_V1

        wanted_feature = ENERGY_V1.content_hash()
    if manifest.feature_schema_hash != wanted_feature:
        refusals.append(RefusalCode.FEATURE_HASH_MISMATCH)
        detail.append(
            f"candidate feature schema {manifest.feature_schema_hash} does not match the "
            f"evaluated schema {wanted_feature}"
        )
    else:
        satisfied.append("feature_schema_hash_matches")

    if expected_rule_family is not None:
        if manifest.rule_family != expected_rule_family:
            refusals.append(RefusalCode.RULE_FAMILY_MISMATCH)
            detail.append(
                f"candidate rule family {manifest.rule_family!r} does not match the evaluated "
                f"family {expected_rule_family!r}"
            )
        else:
            satisfied.append("rule_family_matches")

    missing_evidence = tuple(e for e in frozen.evidence_required if e not in evidence_supplied)
    if missing_evidence:
        refusals.append(RefusalCode.EVIDENCE_MISSING)
        detail.append(f"required evidence not supplied: {list(missing_evidence)}")
    else:
        satisfied.append("all_declared_evidence_supplied")

    if frozen.minimum_scenarios is not None and report.scenario_count < frozen.minimum_scenarios:
        refusals.append(RefusalCode.SCENARIO_COUNT)
        detail.append(
            f"the report covers {report.scenario_count} independent scenarios, below the "
            f"{frozen.minimum_scenarios} the policy requires"
        )
    if frozen.minimum_seeds is not None and report.seed_count < frozen.minimum_seeds:
        refusals.append(RefusalCode.SEED_COUNT)
        detail.append(
            f"the report covers {report.seed_count} training seeds, below the "
            f"{frozen.minimum_seeds} the policy requires"
        )

    comparison = None
    if frozen.benefit_metric is not None:
        comparison = next(
            (c for c in report.comparisons if c.metric == frozen.benefit_metric),
            None,
        )
    if comparison is None:
        refusals.append(RefusalCode.COMPARISON_ABSENT)
        detail.append(
            f"the report carries no comparison for the declared primary metric {frozen.benefit_metric!r}"
        )
    else:
        if frozen.minimum_benefit is not None and comparison.difference_mean < frozen.minimum_benefit:
            refusals.append(RefusalCode.BENEFIT_BELOW_MARGIN)
            detail.append(
                f"measured benefit {comparison.difference_mean:.4f} is below the frozen margin "
                f"{frozen.minimum_benefit:.4f}"
            )
        else:
            satisfied.append("benefit_meets_frozen_margin")
        if frozen.require_interval_excludes_zero and comparison.ci_low <= 0.0:
            refusals.append(RefusalCode.INTERVAL_INCLUDES_ZERO)
            detail.append(
                f"the {comparison.coverage:.0%} interval [{comparison.ci_low:.4f}, "
                f"{comparison.ci_high:.4f}] does not exclude zero"
            )
        elif frozen.require_interval_excludes_zero:
            satisfied.append("benefit_interval_excludes_zero")

    if frozen.downside_noninferiority_limit is not None and frozen.downside_metric is not None:
        downside = next((c for c in report.comparisons if c.metric == frozen.downside_metric), None)
        if downside is None:
            refusals.append(RefusalCode.DOWNSIDE_LIMIT)
            detail.append(
                f"the report carries no downside comparison for {frozen.downside_metric!r}, so "
                "non-inferiority cannot be established"
            )
        elif downside.difference_mean > frozen.downside_noninferiority_limit:
            refusals.append(RefusalCode.DOWNSIDE_LIMIT)
            detail.append(
                f"downside {downside.difference_mean:.4f} exceeds the frozen limit "
                f"{frozen.downside_noninferiority_limit:.4f}"
            )
        else:
            satisfied.append("downside_within_noninferiority_limit")

    if frozen.latency_limit_ms is not None:
        observed = report.latency_p95_ms if frozen.latency_percentile == 95 else report.latency_p99_ms
        if observed is None:
            refusals.append(RefusalCode.LATENCY_LIMIT)
            detail.append(
                f"the report records no p{frozen.latency_percentile} latency, so the latency gate "
                "cannot be evaluated"
            )
        elif observed > frozen.latency_limit_ms:
            refusals.append(RefusalCode.LATENCY_LIMIT)
            detail.append(
                f"p{frozen.latency_percentile} latency {observed:.1f} ms exceeds the frozen limit "
                f"{frozen.latency_limit_ms:.1f} ms"
            )
        else:
            satisfied.append("latency_within_frozen_limit")

    if frozen.max_modelled_violations is not None:
        if report.modelled_violations > frozen.max_modelled_violations:
            refusals.append(RefusalCode.MODELLED_VIOLATIONS)
            detail.append(
                f"{report.modelled_violations} modelled violation(s) observed; the policy allows "
                f"at most {frozen.max_modelled_violations}"
            )
        else:
            satisfied.append("no_modelled_violations_above_limit")

    if frozen.max_withdrawn_decision_rate is not None and comparison is not None:
        denominator = max(1, report.scenario_count * max(1, report.seed_count))
        rate = report.withdrawn_decisions / denominator
        if rate > frozen.max_withdrawn_decision_rate:
            refusals.append(RefusalCode.WITHDRAWAL_RATE)
            detail.append(
                f"withdrawn-decision rate {rate:.4f} exceeds the frozen limit "
                f"{frozen.max_withdrawn_decision_rate:.4f}"
            )
        else:
            satisfied.append("withdrawal_rate_within_limit")

    promoted = not refusals and frozen.thresholds_frozen
    if promoted and manifest.approval_status is ApprovalStatus.REJECTED:
        refusals.append("candidate_previously_rejected")
        detail.append("the candidate manifest is already marked rejected; promotion is refused")
        promoted = False

    if candidate_path is not None:
        detail.append(f"candidate remains inspectable at {candidate_path}")

    return PromotionDecision(
        promoted=promoted,
        bundle_id=manifest.id,
        policy_id=frozen.policy_id,
        policy_hash=frozen.content_hash,
        baseline_identity=baseline_identity,
        refusals=tuple(refusals),
        detail=tuple(detail),
        report_hash=report_hash,
        evaluated_at=report.created_at,
        satisfied_gates=tuple(satisfied),
    )
