"""A learned bundle contributes only when it has been approved and verified.

Regression tests for two defects A14 found, which compounded into the removal
of the whole model-compatibility gate:

- ``check_model_compatibility`` ignored ``approval_status``, so an
  ``unevaluated`` candidate was enabled on manifest agreement alone.
  ``AGENTS.md`` forbids automatic promotion.
- ``expected_feature_hash=None`` was treated as "skip this check" rather than
  "cannot verify", and the session factory never passed one — so the feature
  check was present in the code and never ran.

Together, a bundle could be loaded **unapproved, against the wrong observation
encoding**, and still report ``learned_contribution_enabled: true`` on a
published recommendation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from afterlap_api.session.degradation import check_model_compatibility
from afterlap_contracts import SCHEMA_VERSION, ApprovalStatus, ModelManifest, PromotionPolicy
from afterlap_core.feature_manifest import ENERGY_V1

RULE_FAMILY = "synthetic-pack-v1"
REWARD = "objective-v1"
BASELINE = "mpc-only/planner-v1"

_FROZEN_POLICY = PromotionPolicy(
    enabled=True,
    minimum_benefit=2.0,
    benefit_metric="utility_difference_vs_mpc_only",
    downside_noninferiority_limit=1.0,
    latency_limit_ms=200.0,
    frozen_at=datetime(2026, 9, 8, tzinfo=UTC),
)


def _bundle(**overrides) -> ModelManifest:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "id": "candidate-1",
        "algorithm": "SAC",
        "weights_hash": "sha256:" + "0" * 64,
        "feature_schema_hash": ENERGY_V1.content_hash(),
        "rule_family": RULE_FAMILY,
        "reward_revision": REWARD,
        "created_at": datetime.now(UTC),
    }
    payload.update(overrides)
    return ModelManifest(**payload)


def _approved(**overrides) -> ModelManifest:
    return _bundle(
        approval_status=ApprovalStatus.APPROVED,
        benchmark_report_hash="sha256:" + "1" * 64,
        promotion_policy=_FROZEN_POLICY,
        **overrides,
    )


ENERGY_FEATURE_HASH = ENERGY_V1.content_hash()


def _check(bundle, *, feature_hash=ENERGY_FEATURE_HASH, rule_family=RULE_FAMILY):
    return check_model_compatibility(
        requested_model_hash="sha256:requested",
        bundle=bundle,
        expected_feature_hash=feature_hash,
        expected_rule_family=rule_family,
        expected_reward_revision=REWARD,
        baseline_identity=BASELINE,
    )


@pytest.mark.parametrize(
    "status",
    [ApprovalStatus.UNEVALUATED, ApprovalStatus.CANDIDATE, ApprovalStatus.REJECTED],
)
def test_an_unapproved_bundle_never_contributes(status):
    """Manifest agreement is not approval."""
    decision = _check(_bundle(approval_status=status))
    assert decision.enabled is False
    assert status.value in decision.detail
    assert BASELINE in decision.detail


def test_an_approved_and_matching_bundle_is_enabled():
    """The gate must still let a legitimately promoted bundle through."""
    assert _check(_approved()).enabled is True


def test_an_undeclared_feature_hash_fails_closed():
    """'Cannot verify' is not 'no objection'.

    This is the defect that made the check unreachable: the session factory
    passed no hash, so the comparison was skipped entirely.
    """
    decision = _check(_approved(), feature_hash=None)
    assert decision.enabled is False
    assert "cannot be verified" in decision.detail


def test_an_undeclared_rule_family_fails_closed():
    decision = _check(_approved(), rule_family=None)
    assert decision.enabled is False
    assert "cannot be verified" in decision.detail


def test_a_wrong_feature_encoding_is_refused_even_when_approved():
    decision = _check(_approved(feature_schema_hash="sha256:" + "9" * 64))
    assert decision.enabled is False
    assert "feature manifest" in decision.detail


def test_the_two_defects_no_longer_compound():
    """The exact combination A14 reported: unapproved AND unverifiable.

    Previously this produced ``enabled=True``.
    """
    decision = check_model_compatibility(
        requested_model_hash="sha256:requested",
        bundle=_bundle(feature_schema_hash="sha256:" + "9" * 64),
        expected_feature_hash=None,
        expected_rule_family=None,
        expected_reward_revision=None,
        baseline_identity=BASELINE,
    )
    assert decision.enabled is False, (
        "an unapproved bundle trained on a different observation encoding was enabled"
    )


def test_no_bundle_is_the_baseline_path_not_a_mismatch():
    decision = check_model_compatibility(
        requested_model_hash=None,
        bundle=None,
        expected_feature_hash=ENERGY_V1.content_hash(),
        expected_rule_family=RULE_FAMILY,
        expected_reward_revision=REWARD,
        baseline_identity=BASELINE,
    )
    assert decision.enabled is False
    assert BASELINE in decision.detail
    assert "no learned bundle" in decision.detail


def test_a_requested_but_unloaded_bundle_is_a_mismatch():
    decision = check_model_compatibility(
        requested_model_hash="sha256:missing",
        bundle=None,
        expected_feature_hash=ENERGY_V1.content_hash(),
        expected_rule_family=RULE_FAMILY,
        expected_reward_revision=REWARD,
        baseline_identity=BASELINE,
    )
    assert decision.enabled is False
    assert "not loaded" in decision.detail
