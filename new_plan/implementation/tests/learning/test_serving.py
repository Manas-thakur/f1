"""Serving tests: hash validation, mismatch refusal and the named baseline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from afterlap_contracts import ApprovalStatus, SupportThresholds
from afterlap_core.feature_manifest import ENERGY_V1
from afterlap_core.learning.serving import (
    BUNDLE_SCHEMA_VERSION,
    DEFAULT_BASELINE_IDENTITY,
    BundleRejection,
    RejectionReason,
    default_model_card,
    load_bundle,
    write_bundle,
)
from afterlap_core.learning.value import (
    ContinuationEnsemble,
    TargetScaler,
    ValueMember,
)

from .conftest import constant_actor_state

RULE_FAMILY = "synthetic-pack-v1"
REWARD_REVISION = "objective-v1"
ENVIRONMENT_VERSION = "afterlap-learning-env/env-v1/planner=no_rollout"


def make_bundle(directory: Path, **overrides) -> Path:
    ensemble = ContinuationEnsemble(
        [ValueMember() for _ in range(2)],
        TargetScaler(mean=-30.0, std=4.0, fitted_on="train"),
        feature_hash=ENERGY_V1.content_hash(),
        continuation_controller="mpc-only/planner-v1/no_rollout",
        return_definition_hash="sha256:test-return-definition",
        support=SupportThresholds(
            max_ensemble_disagreement=5.0, max_clip_fraction=0.1, min_known_mask_fraction=0.6
        ),
    )
    kwargs: dict = {
        "bundle_id": "candidate-under-test",
        "actor_state": constant_actor_state(),
        "ensemble": ensemble,
        "rule_family": RULE_FAMILY,
        "reward_revision": REWARD_REVISION,
        "environment_version": ENVIRONMENT_VERSION,
        "continuation_controller": "mpc-only/planner-v1/no_rollout",
        "supported_scenario_families": ("counterattack",),
        "support": SupportThresholds(
            max_ensemble_disagreement=5.0, max_clip_fraction=0.1, min_known_mask_fraction=0.6
        ),
        "model_card": default_model_card(
            bundle_id="candidate-under-test",
            environment_version=ENVIRONMENT_VERSION,
            rule_family=RULE_FAMILY,
            reward_revision=REWARD_REVISION,
            continuation_controller="mpc-only/planner-v1/no_rollout",
            training_status="Synthetic fixture weights. NOT trained.",
            limitations=("synthetic fixture; never a measured result",),
        ),
    }
    kwargs.update(overrides)
    return write_bundle(directory, **kwargs)


class TestWriteAndLoad:
    def test_a_written_bundle_loads_and_carries_its_identity(self, bundle_dir: Path) -> None:
        make_bundle(bundle_dir)
        loaded = load_bundle(bundle_dir)
        assert loaded.manifest.feature_schema_hash == ENERGY_V1.content_hash()
        assert loaded.manifest.rule_family == RULE_FAMILY
        assert loaded.manifest.reward_revision == REWARD_REVISION
        assert loaded.feature_manifest.revision == "energy-v1"
        assert loaded.action_manifest["shape"] == [2]
        assert loaded.ensemble is not None
        assert loaded.model_card.startswith("# Model card")
        assert "torch" in loaded.library_versions
        assert loaded.baseline_identity == DEFAULT_BASELINE_IDENTITY

    def test_a_fresh_bundle_is_never_approved(self, bundle_dir: Path) -> None:
        make_bundle(bundle_dir)
        loaded = load_bundle(bundle_dir)
        assert loaded.manifest.approval_status is ApprovalStatus.UNEVALUATED
        assert loaded.approved is False
        assert loaded.learned_contribution_enabled is False
        assert loaded.promotion_policy.enabled is False

    def test_the_bundle_declares_every_artifact_with_a_hash(self, bundle_dir: Path) -> None:
        path = make_bundle(bundle_dir)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema"] == BUNDLE_SCHEMA_VERSION
        hashes = payload["artifact_hashes"]
        for name in (
            "actor.pt",
            "feature_manifest.json",
            "action_manifest.json",
            "calibrator.json",
            "model_card.md",
            "value_member_0.pt",
            "value_ensemble.json",
            "target_scaler.json",
            "support_thresholds.json",
        ):
            assert name in hashes, name
            assert hashes[name].startswith("sha256:")

    def test_an_absent_calibrator_reports_unavailable_not_a_band(self, bundle_dir: Path) -> None:
        make_bundle(bundle_dir)
        loaded = load_bundle(bundle_dir)
        assert loaded.calibrator is not None
        assert loaded.calibrator["status"] == "unavailable"

    def test_the_model_card_states_what_the_bundle_is_not(self, bundle_dir: Path) -> None:
        make_bundle(bundle_dir)
        card = load_bundle(bundle_dir).model_card
        assert "Synthetic" in card
        assert "certification" in card
        assert DEFAULT_BASELINE_IDENTITY in card


class TestRefusals:
    def test_a_bundle_never_loads_by_filename_alone(self, tmp_path: Path) -> None:
        """A directory of weights with no manifest is not a bundle."""
        directory = tmp_path / "just-weights"
        directory.mkdir()
        torch.save(constant_actor_state(), directory / "actor.pt")
        with pytest.raises(BundleRejection) as excinfo:
            load_bundle(directory)
        assert excinfo.value.reason is RejectionReason.MISSING_BUNDLE_FILE
        assert excinfo.value.baseline_identity == DEFAULT_BASELINE_IDENTITY

    def test_a_tampered_weights_file_fails_its_hash_check(self, bundle_dir: Path) -> None:
        make_bundle(bundle_dir)
        # Load once to prove the bundle was valid before tampering.
        load_bundle(bundle_dir)

        tampered = constant_actor_state()
        tampered["synthetic.linear.bias"] = torch.ones(4)
        torch.save(tampered, bundle_dir / "actor.pt")

        with pytest.raises(BundleRejection) as excinfo:
            load_bundle(bundle_dir)
        assert excinfo.value.reason is RejectionReason.HASH_MISMATCH
        assert "actor.pt" in excinfo.value.detail
        assert excinfo.value.as_dict()["learned_contribution_enabled"] == "false"

    def test_a_tampered_value_member_fails_its_hash_check(self, bundle_dir: Path) -> None:
        make_bundle(bundle_dir)
        member = ValueMember()
        torch.save(member.state_dict(), bundle_dir / "value_member_0.pt")
        with pytest.raises(BundleRejection) as excinfo:
            load_bundle(bundle_dir)
        assert excinfo.value.reason is RejectionReason.HASH_MISMATCH

    def test_a_removed_artifact_is_refused(self, bundle_dir: Path) -> None:
        make_bundle(bundle_dir)
        (bundle_dir / "target_scaler.json").unlink()
        with pytest.raises(BundleRejection) as excinfo:
            load_bundle(bundle_dir)
        assert excinfo.value.reason is RejectionReason.MISSING_ARTIFACT

    def test_a_wrong_feature_hash_disables_the_model_and_names_the_baseline(self, bundle_dir: Path) -> None:
        make_bundle(bundle_dir)
        with pytest.raises(BundleRejection) as excinfo:
            load_bundle(bundle_dir, expected_feature_hash="sha256:a-different-schema")
        rejection = excinfo.value
        assert rejection.reason is RejectionReason.FEATURE_HASH_MISMATCH
        assert "disabled" in rejection.detail
        # The fallback is named, not implied.
        assert rejection.baseline_identity == DEFAULT_BASELINE_IDENTITY
        assert DEFAULT_BASELINE_IDENTITY in str(rejection)

    def test_a_rule_family_mismatch_is_refused(self, bundle_dir: Path) -> None:
        make_bundle(bundle_dir)
        with pytest.raises(BundleRejection) as excinfo:
            load_bundle(bundle_dir, expected_rule_family="synthetic-pack-v2-strict")
        assert excinfo.value.reason is RejectionReason.RULE_FAMILY_MISMATCH

    def test_a_reward_revision_mismatch_is_refused(self, bundle_dir: Path) -> None:
        make_bundle(bundle_dir)
        with pytest.raises(BundleRejection) as excinfo:
            load_bundle(bundle_dir, expected_reward_revision="objective-v2")
        assert excinfo.value.reason is RejectionReason.REWARD_REVISION_MISMATCH

    def test_an_environment_version_mismatch_is_refused(self, bundle_dir: Path) -> None:
        make_bundle(bundle_dir)
        with pytest.raises(BundleRejection) as excinfo:
            load_bundle(bundle_dir, expected_environment_version="afterlap-learning-env/env-v9/x")
        assert excinfo.value.reason is RejectionReason.ENVIRONMENT_VERSION_MISMATCH

    def test_an_unknown_schema_is_refused(self, bundle_dir: Path) -> None:
        path = make_bundle(bundle_dir)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["schema"] = "afterlap.learning.bundle/99"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(BundleRejection) as excinfo:
            load_bundle(bundle_dir)
        assert excinfo.value.reason is RejectionReason.UNKNOWN_SCHEMA

    def test_restart_can_require_an_approved_bundle(self, bundle_dir: Path) -> None:
        """A restart resumes from approved pinned artifacts, not the newest weights."""
        make_bundle(bundle_dir)
        with pytest.raises(BundleRejection) as excinfo:
            load_bundle(bundle_dir, require_approved=True)
        assert excinfo.value.reason is RejectionReason.NOT_APPROVED
        assert "newest training checkpoint" in excinfo.value.detail


class TestRestrictedLoading:
    def test_weights_are_loaded_with_weights_only(self, bundle_dir: Path) -> None:
        """A bundle carrying a pickled object rather than tensors is refused."""
        make_bundle(bundle_dir)

        class Payload:
            def __reduce__(self):  # pragma: no cover - never executed
                return (print, ("this should never run",))

        torch.save({"evil": Payload()}, bundle_dir / "actor.pt")
        # Re-declare the hash so the load reaches the deserialisation step
        # rather than stopping at the hash check.
        from afterlap_core.paths import sha256_file

        path = bundle_dir / "bundle.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["artifact_hashes"]["actor.pt"] = sha256_file(bundle_dir / "actor.pt")
        payload["model_manifest"]["artifact_hashes"]["actor.pt"] = payload["artifact_hashes"]["actor.pt"]
        payload["model_manifest"]["weights_hash"] = payload["artifact_hashes"]["actor.pt"]
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(BundleRejection) as excinfo:
            load_bundle(bundle_dir)
        assert excinfo.value.reason is RejectionReason.UNREADABLE_WEIGHTS
