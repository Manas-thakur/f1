"""Promotion tests. Refusal is the default and it is tested as such."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from afterlap_contracts import (
    SCHEMA_VERSION,
    ApprovalStatus,
    BenchmarkComparison,
    BenchmarkReport,
    ModelManifest,
    PromotionPolicy,
)
from afterlap_core.feature_manifest import ENERGY_V1
from afterlap_core.learning.promotion import (
    FrozenPromotionPolicy,
    RefusalCode,
    load_promotion_policy,
    promote_bundle,
)
from afterlap_core.learning.serving import DEFAULT_BASELINE_IDENTITY

RULE_FAMILY = "synthetic-pack-v1"


@pytest.fixture(scope="module")
def policy() -> FrozenPromotionPolicy:
    return load_promotion_policy()


def manifest(**overrides) -> ModelManifest:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "id": "candidate-under-test",
        "algorithm": "SAC",
        "weights_hash": "sha256:" + "0" * 64,
        "feature_schema_hash": ENERGY_V1.content_hash(),
        "rule_family": RULE_FAMILY,
        "reward_revision": "objective-v1",
        "approval_status": ApprovalStatus.CANDIDATE,
        "created_at": datetime(2026, 9, 8, tzinfo=UTC),
    }
    payload.update(overrides)
    return ModelManifest(**payload)


def comparison(metric: str, mean: float, low: float, high: float) -> BenchmarkComparison:
    return BenchmarkComparison(
        controller="full_system",
        reference="mpc_only",
        metric=metric,
        unit="1",
        difference_mean=mean,
        ci_low=low,
        ci_high=high,
        coverage=0.95,
        scenario_count=120,
        seed_count=5,
        favours_controller=mean > 0.0,
    )


def report(**overrides) -> BenchmarkReport:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "id": "held-out-test-v1",
        "created_at": datetime(2026, 9, 8, tzinfo=UTC),
        "evaluator_version": "a13-harness-1",
        "metrics_version": "metrics-1",
        "scenario_family": "mixed",
        "scenario_count": 120,
        "seed_count": 5,
        "comparisons": (
            comparison("utility_difference_vs_mpc_only", 3.5, 1.2, 5.8),
            comparison("cvar_0.9_utility_loss", 0.2, -0.1, 0.5),
        ),
        "latency_p95_ms": 150.0,
        "latency_p99_ms": 190.0,
        "withdrawn_decisions": 3,
        "modelled_violations": 0,
    }
    payload.update(overrides)
    return BenchmarkReport(**payload)


ALL_EVIDENCE = (
    "held_out_test_manifest_frozen_before_training",
    "at_least_100_independent_test_scenarios",
    "at_least_5_training_seeds",
    "hierarchical_paired_bootstrap_over_scenarios_and_seeds",
    "ablation_disabling_only_the_learned_terminal_value",
    "ablation_disabling_only_the_policy_warm_start",
    "equal_observation_access_and_equal_solver_compute_allowance",
    "failed_and_withdrawn_decisions_retained_in_denominators",
)


class TestTheFrozenPolicyIsReadOnly:
    def test_the_shipped_policy_carries_frozen_thresholds(self, policy: FrozenPromotionPolicy) -> None:
        assert policy.thresholds_frozen is True
        assert policy.minimum_benefit == pytest.approx(2.0)
        assert policy.downside_noninferiority_limit == pytest.approx(1.0)
        assert policy.latency_limit_ms == pytest.approx(200.0)
        assert policy.frozen_at is not None
        assert policy.benefit_metric == "utility_difference_vs_mpc_only"
        assert policy.enabled is False
        assert policy.minimum_scenarios == 100
        assert policy.minimum_seeds == 5

    def test_the_contract_refuses_enabled_without_thresholds(self) -> None:
        with pytest.raises(ValueError, match="without frozen thresholds"):
            PromotionPolicy(enabled=True)

    def test_the_contract_refuses_approval_without_evidence(self) -> None:
        with pytest.raises(ValueError, match="benchmark report"):
            manifest(approval_status=ApprovalStatus.APPROVED)


class TestRefusals:
    def test_promotion_is_refused_without_a_benchmark_report(self, policy: FrozenPromotionPolicy) -> None:
        decision = promote_bundle(manifest(), None, policy=policy, evidence_supplied=ALL_EVIDENCE)
        assert decision.promoted is False
        assert RefusalCode.REPORT_ABSENT in decision.refusals
        assert decision.baseline_enabled is True
        assert decision.baseline_identity == DEFAULT_BASELINE_IDENTITY

    def test_promotion_is_refused_without_frozen_thresholds(self) -> None:
        unfrozen = FrozenPromotionPolicy(
            policy_id="unfrozen",
            content_hash="sha256:test",
            enabled=False,
            frozen_at=None,
            benefit_metric=None,
            minimum_benefit=None,
            require_interval_excludes_zero=True,
            interval_coverage=0.95,
            downside_noninferiority_limit=None,
            downside_metric=None,
            latency_limit_ms=None,
            latency_percentile=95,
            max_withdrawn_decision_rate=None,
            max_modelled_violations=None,
            evidence_required=(),
            refusal_conditions=(),
            rationale=None,
        )
        assert unfrozen.thresholds_frozen is False
        decision = promote_bundle(manifest(), report(), policy=unfrozen)
        assert decision.promoted is False
        assert RefusalCode.THRESHOLDS_MISSING in decision.refusals
        assert decision.baseline_enabled is True

    def test_promotion_is_refused_on_a_feature_hash_mismatch(self, policy: FrozenPromotionPolicy) -> None:
        decision = promote_bundle(
            manifest(feature_schema_hash="sha256:a-different-schema"),
            report(),
            policy=policy,
            evidence_supplied=ALL_EVIDENCE,
            expected_rule_family=RULE_FAMILY,
        )
        assert decision.promoted is False
        assert RefusalCode.FEATURE_HASH_MISMATCH in decision.refusals
        assert decision.baseline_enabled is True

    def test_promotion_is_refused_on_a_rule_family_mismatch(self, policy: FrozenPromotionPolicy) -> None:
        decision = promote_bundle(
            manifest(rule_family="synthetic-pack-v2-strict"),
            report(),
            policy=policy,
            evidence_supplied=ALL_EVIDENCE,
            expected_rule_family=RULE_FAMILY,
        )
        assert decision.promoted is False
        assert RefusalCode.RULE_FAMILY_MISMATCH in decision.refusals

    def test_promotion_is_refused_when_evidence_is_missing(self, policy: FrozenPromotionPolicy) -> None:
        decision = promote_bundle(manifest(), report(), policy=policy, evidence_supplied=ALL_EVIDENCE[:3])
        assert decision.promoted is False
        assert RefusalCode.EVIDENCE_MISSING in decision.refusals
        assert "ablation_disabling_only_the_learned_terminal_value" in " ".join(decision.detail)

    def test_promotion_is_refused_below_the_frozen_benefit_margin(
        self, policy: FrozenPromotionPolicy
    ) -> None:
        thin = report(
            comparisons=(
                comparison("utility_difference_vs_mpc_only", 0.5, 0.1, 0.9),
                comparison("cvar_0.9_utility_loss", 0.2, -0.1, 0.5),
            )
        )
        decision = promote_bundle(manifest(), thin, policy=policy, evidence_supplied=ALL_EVIDENCE)
        assert decision.promoted is False
        assert RefusalCode.BENEFIT_BELOW_MARGIN in decision.refusals

    def test_promotion_is_refused_when_the_interval_includes_zero(
        self, policy: FrozenPromotionPolicy
    ) -> None:
        wide = report(
            comparisons=(
                comparison("utility_difference_vs_mpc_only", 3.0, -1.0, 7.0),
                comparison("cvar_0.9_utility_loss", 0.2, -0.1, 0.5),
            )
        )
        decision = promote_bundle(manifest(), wide, policy=policy, evidence_supplied=ALL_EVIDENCE)
        assert decision.promoted is False
        assert RefusalCode.INTERVAL_INCLUDES_ZERO in decision.refusals

    def test_promotion_is_refused_when_the_primary_comparison_is_absent(
        self, policy: FrozenPromotionPolicy
    ) -> None:
        decision = promote_bundle(
            manifest(),
            report(comparisons=(comparison("some_other_metric", 9.0, 8.0, 10.0),)),
            policy=policy,
            evidence_supplied=ALL_EVIDENCE,
        )
        assert decision.promoted is False
        assert RefusalCode.COMPARISON_ABSENT in decision.refusals

    def test_promotion_is_refused_on_a_downside_breach(self, policy: FrozenPromotionPolicy) -> None:
        worse = report(
            comparisons=(
                comparison("utility_difference_vs_mpc_only", 3.5, 1.2, 5.8),
                comparison("cvar_0.9_utility_loss", 4.0, 3.0, 5.0),
            )
        )
        decision = promote_bundle(manifest(), worse, policy=policy, evidence_supplied=ALL_EVIDENCE)
        assert decision.promoted is False
        assert RefusalCode.DOWNSIDE_LIMIT in decision.refusals

    def test_promotion_is_refused_on_a_latency_breach(self, policy: FrozenPromotionPolicy) -> None:
        slow = report(latency_p95_ms=830.0)
        decision = promote_bundle(manifest(), slow, policy=policy, evidence_supplied=ALL_EVIDENCE)
        assert decision.promoted is False
        assert RefusalCode.LATENCY_LIMIT in decision.refusals

    def test_promotion_is_refused_without_a_recorded_latency(self, policy: FrozenPromotionPolicy) -> None:
        decision = promote_bundle(
            manifest(), report(latency_p95_ms=None), policy=policy, evidence_supplied=ALL_EVIDENCE
        )
        assert decision.promoted is False
        assert RefusalCode.LATENCY_LIMIT in decision.refusals

    def test_promotion_is_refused_on_a_modelled_violation(self, policy: FrozenPromotionPolicy) -> None:
        decision = promote_bundle(
            manifest(), report(modelled_violations=1), policy=policy, evidence_supplied=ALL_EVIDENCE
        )
        assert decision.promoted is False
        assert RefusalCode.MODELLED_VIOLATIONS in decision.refusals

    def test_promotion_is_refused_on_too_few_scenarios_or_seeds(self, policy: FrozenPromotionPolicy) -> None:
        small = report(scenario_count=8, seed_count=1)
        decision = promote_bundle(manifest(), small, policy=policy, evidence_supplied=ALL_EVIDENCE)
        assert decision.promoted is False
        assert RefusalCode.SCENARIO_COUNT in decision.refusals
        assert RefusalCode.SEED_COUNT in decision.refusals

    def test_promotion_is_refused_when_withdrawals_are_excessive(self, policy: FrozenPromotionPolicy) -> None:
        noisy = report(withdrawn_decisions=500)
        decision = promote_bundle(manifest(), noisy, policy=policy, evidence_supplied=ALL_EVIDENCE)
        assert decision.promoted is False
        assert RefusalCode.WITHDRAWAL_RATE in decision.refusals

    def test_a_previously_rejected_candidate_is_refused(self, policy: FrozenPromotionPolicy) -> None:
        decision = promote_bundle(
            manifest(approval_status=ApprovalStatus.REJECTED),
            report(),
            policy=policy,
            evidence_supplied=ALL_EVIDENCE,
            expected_rule_family=RULE_FAMILY,
        )
        assert decision.promoted is False
        assert "candidate_previously_rejected" in decision.refusals


class TestAFailedPromotionIsAValidResult:
    def test_the_baseline_stays_enabled_and_the_candidate_stays_inspectable(
        self, policy: FrozenPromotionPolicy, tmp_path
    ) -> None:
        candidate = tmp_path / "candidate-bundle"
        candidate.mkdir()
        decision = promote_bundle(
            manifest(),
            report(comparisons=(comparison("utility_difference_vs_mpc_only", 0.1, -0.4, 0.6),)),
            policy=policy,
            evidence_supplied=ALL_EVIDENCE,
            candidate_path=candidate,
        )
        assert decision.promoted is False
        assert decision.baseline_enabled is True
        assert decision.baseline_identity == DEFAULT_BASELINE_IDENTITY
        assert str(candidate) in " ".join(decision.detail)
        assert candidate.is_dir(), "a failed promotion must not delete the candidate"
        payload = decision.as_dict()
        assert payload["baseline_enabled"] is True
        assert payload["report_hash"] is not None

    def test_every_refusal_is_reported_not_just_the_first(self, policy: FrozenPromotionPolicy) -> None:
        broken = report(
            scenario_count=4,
            seed_count=1,
            modelled_violations=2,
            latency_p95_ms=900.0,
            comparisons=(comparison("utility_difference_vs_mpc_only", 0.0, -1.0, 1.0),),
        )
        decision = promote_bundle(
            manifest(feature_schema_hash="sha256:wrong"),
            broken,
            policy=policy,
            evidence_supplied=(),
        )
        assert decision.promoted is False
        assert len(decision.refusals) >= 6
        assert len(decision.detail) >= 6


class TestAPassingCandidate:
    def test_a_candidate_meeting_every_frozen_gate_is_promoted(self, policy: FrozenPromotionPolicy) -> None:
        """The positive control, so the refusals above are not vacuous."""
        decision = promote_bundle(
            manifest(),
            report(),
            policy=policy,
            evidence_supplied=ALL_EVIDENCE,
            expected_rule_family=RULE_FAMILY,
        )
        assert decision.promoted is True, decision.refusals
        assert decision.refusals == ()
        assert decision.baseline_enabled is False
        assert "benefit_meets_frozen_margin" in decision.satisfied_gates
        assert "latency_within_frozen_limit" in decision.satisfied_gates

    def test_removing_one_gate_flips_the_decision(self, policy: FrozenPromotionPolicy) -> None:
        """A single failing gate is enough to refuse. The gates have teeth."""
        for mutation in (
            {"latency_p95_ms": 900.0},
            {"modelled_violations": 1},
            {"scenario_count": 10},
        ):
            decision = promote_bundle(
                manifest(),
                report(**mutation),
                policy=policy,
                evidence_supplied=ALL_EVIDENCE,
                expected_rule_family=RULE_FAMILY,
            )
            assert decision.promoted is False, mutation

    def test_a_promoted_decision_still_needs_the_contract_to_agree(
        self, policy: FrozenPromotionPolicy
    ) -> None:
        """Promotion is a decision; the manifest still refuses approval without evidence."""
        decision = promote_bundle(
            manifest(),
            report(),
            policy=policy,
            evidence_supplied=ALL_EVIDENCE,
            expected_rule_family=RULE_FAMILY,
        )
        assert decision.promoted is True
        contract_policy = dataclasses.replace(policy, enabled=True).as_contract()
        assert contract_policy.enabled is True
        approved = manifest(
            approval_status=ApprovalStatus.APPROVED,
            benchmark_report_hash=decision.report_hash,
            promotion_policy=contract_policy,
        )
        assert approved.approval_status is ApprovalStatus.APPROVED
        with pytest.raises(ValueError, match="benchmark report"):
            manifest(approval_status=ApprovalStatus.APPROVED, promotion_policy=contract_policy)
