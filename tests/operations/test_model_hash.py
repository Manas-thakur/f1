"""A bundle whose weights do not hash to what it declares.

**Genuinely causes the condition.** A real frozen bundle is written to disk by
`afterlap_core.learning.serving.write_bundle` — real `actor.pt` bytes, a real
`bundle.json` with a real SHA-256 map — and is then loaded once to prove the
fixture is a *valid* bundle. Only then are the weights genuinely replaced with
different tensors, so `actor.pt` really hashes to something the bundle really
does not declare. Nothing is mocked and no hash is hand-edited to disagree.

Two guarantees are separable and both are tested:

* the bundle is **refused**, with a reason code, and the validated baseline
  that takes over is **named** in the refusal;
* the refusal happens **before any deserialisation**. A filename is not
  evidence of what a set of weights contains, so `torch.load` must never see
  the file. That is asserted by making `torch.load` fail: the rejection still
  has to be the hash mismatch.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch", reason="the bundle format is torch state dicts")

from typing import TYPE_CHECKING

from afterlap_api.session.degradation import (
    DegradationRow,
    check_model_compatibility,
)
from afterlap_contracts import (
    SCHEMA_VERSION,
    ApprovalStatus,
    ModelManifest,
    PromotionPolicy,
    ReasonCode,
)
from afterlap_core.feature_manifest import ENERGY_V1
from afterlap_core.learning.serving import (
    DEFAULT_BASELINE_IDENTITY,
    BundleRejection,
    RejectionReason,
    load_bundle,
    write_bundle,
)
from afterlap_core.paths import sha256_file

from .conftest import RULE_PACK_ID, actionable

if TYPE_CHECKING:
    from pathlib import Path

RULE_FAMILY = RULE_PACK_ID
REWARD_REVISION = "objective-v1"


def _actor_state() -> dict[str, torch.Tensor]:
    """A small, deterministic state dict. Not a trained model and not claimed to be."""
    generator = torch.Generator().manual_seed(11)
    return {
        "net.0.weight": torch.randn(4, 8, generator=generator),
        "net.0.bias": torch.zeros(4),
    }


@pytest.fixture
def bundle_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "bundle-ops-drill"
    write_bundle(
        directory,
        bundle_id="ops-drill-bundle",
        actor_state=_actor_state(),
        ensemble=None,
        rule_family=RULE_FAMILY,
        reward_revision=REWARD_REVISION,
        environment_version="env-ops-drill",
        continuation_controller=None,
        supported_scenario_families=("two-straight-counterattack",),
        model_card=(
            "# Synthetic operations drill bundle\n\n"
            "Random weights written by tests/operations/test_model_hash.py. Not trained, "
            "not evaluated, not approved, and not a model of any real car.\n"
        ),
    )
    loaded = load_bundle(
        directory,
        expected_rule_family=RULE_FAMILY,
        expected_reward_revision=REWARD_REVISION,
        expected_environment_version="env-ops-drill",
    )
    assert loaded.manifest.id == "ops-drill-bundle"
    assert loaded.approved is False, "a freshly written bundle must not be approved"
    assert loaded.learned_contribution_enabled is False
    return directory


def test_a_bundle_whose_weights_hash_does_not_match_is_rejected(bundle_dir: Path):
    actor = bundle_dir / "actor.pt"
    declared = sha256_file(actor)

    replacement = {key: value + 1.0 for key, value in _actor_state().items()}
    torch.save(replacement, actor)
    actual = sha256_file(actor)
    assert actual != declared, "the replacement weights happened to hash identically"
    print(f"\ndeclared {declared}\nactual   {actual}")

    with pytest.raises(BundleRejection) as rejection:
        load_bundle(bundle_dir)

    error = rejection.value
    assert error.reason is RejectionReason.HASH_MISMATCH, error.reason
    assert "actor.pt" in error.detail
    assert actual in error.detail and declared in error.detail, (
        "the refusal does not show both the hash found and the hash declared"
    )

    assert error.baseline_identity == DEFAULT_BASELINE_IDENTITY
    assert DEFAULT_BASELINE_IDENTITY in str(error)
    assert error.as_dict() == {
        "reason": "artifact_hash_mismatch",
        "detail": error.detail,
        "baseline_identity": DEFAULT_BASELINE_IDENTITY,
        "learned_contribution_enabled": "false",
    }
    print(f"refused: {error}")


def test_the_hashes_are_validated_before_anything_is_deserialised(
    bundle_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """A filename is not evidence. `torch.load` must never see a bad bundle."""
    torch.save({key: value * 2.0 for key, value in _actor_state().items()}, bundle_dir / "actor.pt")

    def _explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("torch.load was reached with an unvalidated bundle on disk")

    monkeypatch.setattr(torch, "load", _explode)

    with pytest.raises(BundleRejection) as rejection:
        load_bundle(bundle_dir)
    assert rejection.value.reason is RejectionReason.HASH_MISMATCH


def test_a_declared_artifact_that_is_simply_gone_is_also_refused(bundle_dir: Path):
    (bundle_dir / "calibrator.json").unlink()
    with pytest.raises(BundleRejection) as rejection:
        load_bundle(bundle_dir)
    assert rejection.value.reason is RejectionReason.MISSING_ARTIFACT
    assert "calibrator.json" in rejection.value.detail
    assert rejection.value.baseline_identity == DEFAULT_BASELINE_IDENTITY


def _manifest(**overrides: object) -> ModelManifest:
    fields: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "id": "ops-drill-bundle",
        "algorithm": "SAC",
        "weights_hash": "sha256:" + "a" * 64,
        "artifact_hashes": {"actor.pt": "sha256:" + "a" * 64},
        "feature_schema_hash": ENERGY_V1.content_hash(),
        "rule_family": RULE_FAMILY,
        "reward_revision": REWARD_REVISION,
        "continuation_controller": None,
        "library_versions": {"torch": torch.__version__},
        "supported_scenario_families": ("two-straight-counterattack",),
        "approval_status": ApprovalStatus.UNEVALUATED,
        "promotion_policy": PromotionPolicy(),
        "model_card": "model_card.md",
    }
    fields.update(overrides)
    from datetime import UTC, datetime

    fields.setdefault("created_at", datetime.now(UTC))
    return ModelManifest(**fields)  # type: ignore[arg-type]


def _live_session(bundle: ModelManifest):  # type: ignore[no-untyped-def]
    from afterlap_api.session import BaselinePlanner, SessionFactory
    from afterlap_contracts import SessionMode
    from afterlap_contracts.requests import CreateSessionRequest

    factory = SessionFactory(planner=BaselinePlanner(), model_bundles={"ops-drill-bundle": bundle})
    return factory.create(
        CreateSessionRequest(
            mode=SessionMode.SIMULATION,
            scenario_id="two-straight-counterattack",
            ruleset_id=RULE_PACK_ID,
            seed=42,
            model_bundle_id="ops-drill-bundle",
            label="model hash drill",
        )
    )


def test_a_rule_family_mismatch_disables_the_learned_contribution(db_factory):
    """The runtime consequence, on a real published recommendation.

    The rule family is chosen because it is a disagreement the *runtime*
    actually passes to the check (`expected_rule_family=pack.manifest.
    ruleset_id`). The feature-manifest hash is a separate matter — see
    `test_a_live_session_checks_the_feature_manifest_hash` below.
    """
    mismatched = _manifest(rule_family="some-other-rule-family")
    manifest, runtime = _live_session(mismatched)

    assert manifest.model_hash == mismatched.content_hash()

    decision = runtime.model_decision
    print(f"\nmodel decision: {decision.detail}")
    assert decision.enabled is False
    assert decision.baseline_identity, "no validated baseline was named"
    assert any("rule family" in reason for reason in decision.mismatches), decision.mismatches
    assert decision.baseline_identity in decision.detail

    tick = None
    for _ in range(45):
        tick = runtime.advance(1.0)
        if actionable(tick):
            break
    assert tick is not None and tick.recommendation is not None, "no advice was published"
    recommendation = tick.recommendation
    assert recommendation.learned_contribution_enabled is False
    assert recommendation.baseline_identity == decision.baseline_identity
    assert ReasonCode.BASELINE_FALLBACK in recommendation.reason_codes
    assert ReasonCode.LEARNED_MODEL_DISABLED in recommendation.reason_codes
    print(
        f"published with learned contribution off, baseline {recommendation.baseline_identity!r}, "
        f"reasons {[c.value for c in recommendation.reason_codes]}"
    )

    finding = runtime.degradation.find(DegradationRow.MODEL_MISMATCH)
    assert finding is not None
    assert finding.effect == "learned_contribution_disabled_baseline_named"
    del db_factory


def test_a_live_session_checks_the_feature_manifest_hash():
    """Was A14-8, now fixed.

    ``SessionFactory`` never supplied ``expected_feature_hash``, so the runtime
    called the check with ``None`` and the feature-manifest comparison was
    skipped entirely -- a bundle trained against a different observation
    encoding was accepted. The factory now declares the hash, and an
    undeclared expectation fails closed rather than being treated as no
    objection.
    """
    _, runtime = _live_session(_manifest(feature_schema_hash="sha256:" + "b" * 64))
    decision = runtime.model_decision
    assert decision.enabled is False, (
        "a bundle declaring a different feature-manifest hash was enabled by a live session"
    )
    assert any("feature manifest" in reason for reason in decision.mismatches), decision.mismatches


@pytest.mark.parametrize(
    ("field", "value", "expected_text"),
    [
        ("rule_family", "some-other-pack", "rule family"),
        ("reward_revision", "objective-v99", "reward revision"),
        ("supported_scenario_families", ("oval-defend-hold",), "scenario family"),
    ],
)
def test_every_pinned_manifest_disagreement_disables_the_model(field: str, value: object, expected_text: str):
    decision = check_model_compatibility(
        requested_model_hash="sha256:" + "a" * 64,
        bundle=_manifest(**{field: value}),
        expected_feature_hash=ENERGY_V1.content_hash(),
        expected_rule_family=RULE_FAMILY,
        expected_reward_revision=REWARD_REVISION,
        baseline_identity=DEFAULT_BASELINE_IDENTITY,
        scenario_family="two-straight-counterattack",
    )
    assert decision.enabled is False
    assert any(expected_text in reason for reason in decision.mismatches), decision.mismatches
    assert decision.baseline_identity == DEFAULT_BASELINE_IDENTITY
    assert decision.finding is not None


def test_a_requested_bundle_that_is_not_loaded_is_a_mismatch_not_a_silent_baseline():
    decision = check_model_compatibility(
        requested_model_hash="sha256:" + "c" * 64,
        bundle=None,
        expected_feature_hash=ENERGY_V1.content_hash(),
        expected_rule_family=RULE_FAMILY,
        expected_reward_revision=REWARD_REVISION,
        baseline_identity=DEFAULT_BASELINE_IDENTITY,
    )
    assert decision.enabled is False
    assert decision.finding is not None, "a requested-but-absent bundle degraded silently"
    assert "is not loaded" in decision.detail


def test_an_unapproved_bundle_is_never_enabled():
    """Was A14-7, now fixed.

    The check ignored ``approval_status`` entirely, so manifest agreement was
    treated as approval. AGENTS.md forbids automatic promotion.
    """
    decision = check_model_compatibility(
        requested_model_hash="sha256:" + "a" * 64,
        bundle=_manifest(approval_status=ApprovalStatus.UNEVALUATED),
        expected_feature_hash=ENERGY_V1.content_hash(),
        expected_rule_family=RULE_FAMILY,
        expected_reward_revision=REWARD_REVISION,
        baseline_identity=DEFAULT_BASELINE_IDENTITY,
        scenario_family="two-straight-counterattack",
    )
    assert decision.enabled is False, (
        "an unevaluated bundle was enabled as a learned contribution on manifest agreement alone"
    )
