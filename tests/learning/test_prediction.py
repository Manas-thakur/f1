"""The prediction serving surface, and what it refuses to serve.

A prediction service is the place a forgotten gate becomes a confident number.
So these tests are almost entirely about the gates: an unapproved bundle, a
disabled promotion policy, an unfrozen calibrator, an out-of-support
observation, a missing component. Each must produce ``None`` with a reason, and
the reason must name what would answer instead.

The one thing checked positively is that identity travels: a payload that
carries a prediction has to be able to say which weights produced it.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

torch = pytest.importorskip("torch", reason="a bundle holds torch state dicts")
pytest.importorskip("stable_baselines3", reason="the actor is rebuilt with the library's own class")

import numpy as np
from tests.learning.conftest import context, estimate_with, sb3_actor_state

from afterlap_contracts import (
    ApprovalStatus,
    CalibrationStatus,
    PromotionPolicy,
    SupportThresholds,
)
from afterlap_core.feature_manifest import ENERGY_V1, OBSERVATION_SIZE
from afterlap_core.learning.calibration import (
    CalibrationSample,
    CalibratorStatus,
    fit_calibrator,
)
from afterlap_core.learning.prediction import (
    PredictionService,
    PredictionUnavailable,
    build_prediction_service,
    service_from_directory,
    support_reason_text,
)
from afterlap_core.learning.serving import DEFAULT_BASELINE_IDENTITY, default_model_card, write_bundle
from afterlap_core.learning.value import ContinuationEnsemble, SupportReason, TargetScaler, ValueMember

RULE_FAMILY = "synthetic-pack-v1"
REWARD_REVISION = "objective-v1"
ENVIRONMENT_VERSION = "afterlap-learning-env/env-v1/planner=no_rollout"
EVENT = "pass_before(checkpoint=attack-exit)"


def _ensemble(*, frozen: bool) -> ContinuationEnsemble:
    return ContinuationEnsemble(
        [ValueMember(hidden=(16, 16)) for _ in range(2)],
        TargetScaler(mean=-60.0, std=5.0, fitted_on="train"),
        feature_hash=ENERGY_V1.content_hash(),
        continuation_controller="held-neutral/action-zero",
        return_definition_hash="sha256:test-return-definition",
        support=SupportThresholds(
            max_ensemble_disagreement=50.0,
            max_clip_fraction=1.0,
            min_known_mask_fraction=0.0,
            frozen_before_final_test=frozen,
        ),
        hidden=(16, 16),
    )


def _calibrator(*, frozen: bool):
    rng = np.random.default_rng(11)
    rows = [
        CalibrationSample(
            event_definition=EVENT,
            raw_frequency=float(rng.uniform(0.05, 0.95)),
            outcome=int(rng.uniform() < 0.4),
            episode_id=f"e{index // 3}",
            scenario_id="s",
            checkpoint_id="attack-exit",
        )
        for index in range(120)
    ]
    fitted = fit_calibrator(rows, forecaster_version="test-v1", seed=2, min_support=10).calibrator
    assert fitted is not None
    return dataclasses.replace(fitted, frozen_before_final_test=frozen)


def _write(
    directory,
    *,
    approval=ApprovalStatus.UNEVALUATED,
    promotion=None,
    ensemble_frozen=True,
    with_ensemble=True,
    with_calibrator=True,
    calibrator_frozen=True,
    actor_state=None,
):
    ensemble = _ensemble(frozen=ensemble_frozen) if with_ensemble else None
    calibrator = _calibrator(frozen=calibrator_frozen) if with_calibrator else None
    _, state = sb3_actor_state(hidden=(32, 32), seed=4)
    return write_bundle(
        directory,
        bundle_id="prediction-under-test",
        actor_state=state if actor_state is None else actor_state,
        ensemble=ensemble,
        rule_family=RULE_FAMILY,
        reward_revision=REWARD_REVISION,
        environment_version=ENVIRONMENT_VERSION,
        continuation_controller=None if ensemble is None else ensemble.continuation_controller,
        supported_scenario_families=("counterattack",),
        support=None if ensemble is None else ensemble.support,
        calibrator=None if calibrator is None else calibrator.as_dict(),
        model_card=default_model_card(
            bundle_id="prediction-under-test",
            environment_version=ENVIRONMENT_VERSION,
            rule_family=RULE_FAMILY,
            reward_revision=REWARD_REVISION,
            continuation_controller=None if ensemble is None else ensemble.continuation_controller,
            training_status="Synthetic fixture weights. NOT trained.",
            limitations=("synthetic fixture; never a measured result",),
        ),
        approval_status=approval,
        promotion_policy=promotion,
        benchmark_report_hash=None if approval is not ApprovalStatus.APPROVED else "sha256:" + "c" * 64,
    )


def _enabled_policy() -> PromotionPolicy:
    """A frozen, enabled policy. Every threshold the contract requires is present."""
    return PromotionPolicy(
        enabled=True,
        minimum_benefit=2.0,
        benefit_metric="utility_difference_vs_mpc_only",
        downside_noninferiority_limit=1.0,
        latency_limit_ms=200.0,
        frozen_at="2026-09-08T00:00:00Z",
    )


def _approved_directory(tmp_path):
    """A bundle whose gates are all open, so the enabled path can be tested."""
    directory = tmp_path / "approved"
    directory.mkdir()
    _write(directory, approval=ApprovalStatus.APPROVED, promotion=_enabled_policy())
    return directory


def _encoded(encoder, feature_context):
    return encoder.encode(estimate_with(), feature_context)


@pytest.fixture
def unapproved(tmp_path):
    directory = tmp_path / "candidate"
    directory.mkdir()
    _write(directory)
    return service_from_directory(directory)


@pytest.fixture
def approved(tmp_path):
    return service_from_directory(_approved_directory(tmp_path))


class TestTheServiceIsBuilt:
    def test_a_validated_bundle_becomes_a_service(self, unapproved) -> None:
        assert isinstance(unapproved, PredictionService)
        assert unapproved.actor is not None
        assert unapproved.ensemble is not None
        assert unapproved.calibrator is not None

    def test_a_missing_bundle_is_an_explicit_unavailable_not_an_exception(self, tmp_path) -> None:
        result = service_from_directory(tmp_path / "nothing")
        assert isinstance(result, PredictionUnavailable)
        assert result.enabled is False
        assert result.reason == "missing_bundle_file"
        assert result.baseline_identity == DEFAULT_BASELINE_IDENTITY

    def test_a_hash_mismatch_names_the_mismatch_not_merely_that_one_occurred(self, tmp_path) -> None:
        directory = tmp_path / "tampered"
        directory.mkdir()
        _write(directory)
        (directory / "actor.pt").write_bytes(b"not a state dict")
        result = service_from_directory(directory)
        assert isinstance(result, PredictionUnavailable)
        assert result.reason == "artifact_hash_mismatch"
        assert "actor.pt" in result.detail

    def test_a_rule_family_mismatch_disables_the_service(self, tmp_path) -> None:
        directory = tmp_path / "other-rules"
        directory.mkdir()
        _write(directory)
        result = service_from_directory(directory, expected_rule_family="synthetic-pack-v2-strict")
        assert isinstance(result, PredictionUnavailable)
        assert result.reason == "rule_family_mismatch"

    def test_a_bundle_without_an_ensemble_still_serves_the_actor(self, tmp_path) -> None:
        """Refusing the whole bundle would be worse than serving what exists."""
        directory = tmp_path / "actor-only"
        directory.mkdir()
        _write(directory, with_ensemble=False, with_calibrator=False)
        service = service_from_directory(directory)
        assert isinstance(service, PredictionService)
        assert service.actor is not None
        assert service.ensemble is None
        assert service.calibrator is None
        assert any("no continuation ensemble" in note for note in service.notes)

    def test_unreadable_actor_weights_are_recorded_not_raised(self, tmp_path) -> None:
        directory = tmp_path / "foreign-actor"
        directory.mkdir()
        _write(
            directory,
            actor_state={"synthetic.weight": torch.zeros(2, 192), "synthetic.bias": torch.zeros(2)},
        )
        service = service_from_directory(directory)
        assert isinstance(service, PredictionService)
        assert service.actor is None
        assert "could not be rebuilt" in service.actor_detail


class TestApprovalIsTheGate:
    def test_an_unapproved_bundle_contributes_nothing(self, unapproved, encoder, feature_context) -> None:
        assert unapproved.enabled is False
        prediction = unapproved.predict_continuation(_encoded(encoder, feature_context))
        assert prediction.value is None
        assert prediction.reason == "learned_contribution_disabled"
        assert unapproved.continuation_adapter() is None
        assert unapproved.probability_calibration() is None
        assert unapproved.propose(np.zeros(OBSERVATION_SIZE, dtype=np.float32)) is None

    def test_the_refusal_names_the_baseline_that_answers_instead(self, unapproved) -> None:
        identity = unapproved.identity()
        assert identity["learned_contribution_enabled"] is False
        assert identity["baseline_identity"] == DEFAULT_BASELINE_IDENTITY
        assert any("unevaluated" in note for note in unapproved.notes)

    def test_an_approved_bundle_with_promotion_off_cannot_even_be_written(self, tmp_path) -> None:
        """The state is refused by the contract, so it never reaches serving.

        ``ModelManifest`` requires an approved bundle to reference an enabled,
        frozen promotion policy. The service's own `promotion policy is
        disabled` note is therefore defence in depth against a manifest built
        some other way, not the first line of it.
        """
        from pydantic import ValidationError

        directory = tmp_path / "approved-policy-off"
        directory.mkdir()
        with pytest.raises(ValidationError, match="enabled, frozen promotion policy"):
            _write(
                directory,
                approval=ApprovalStatus.APPROVED,
                promotion=PromotionPolicy(enabled=False),
            )

    def test_the_service_reports_a_disabled_promotion_policy_when_it_sees_one(self, tmp_path) -> None:
        directory = tmp_path / "approved"
        directory.mkdir()
        _write(directory, approval=ApprovalStatus.APPROVED, promotion=_enabled_policy())
        service = service_from_directory(directory)
        assert isinstance(service, PredictionService)
        disabled = dataclasses.replace(
            service,
            bundle=dataclasses.replace(service.bundle, promotion_policy=PromotionPolicy(enabled=False)),
        )
        assert disabled.enabled is False
        assert build_prediction_service(disabled.bundle).enabled is False

    def test_an_approved_and_promoted_bundle_is_enabled(self, approved) -> None:
        assert isinstance(approved, PredictionService)
        assert approved.enabled is True
        assert approved.continuation_adapter() is not None
        assert approved.probability_calibration() is not None

    def test_an_enabled_service_can_produce_a_proposal(self, approved) -> None:
        action = approved.propose(np.zeros(OBSERVATION_SIZE, dtype=np.float32))
        assert action is not None
        assert action.shape == (2,)
        np.testing.assert_array_equal(action, approved.propose(np.zeros(OBSERVATION_SIZE, dtype=np.float32)))


class TestContinuationPrediction:
    def test_an_enabled_service_publishes_a_value_with_its_disagreement(
        self, approved, encoder, feature_context
    ) -> None:
        prediction = approved.predict_continuation(_encoded(encoder, feature_context))
        assert prediction.in_support is True
        assert prediction.value is not None
        assert prediction.disagreement is not None
        assert prediction.member_count == 2
        assert prediction.bundle_id is not None

    def test_a_feature_revision_mismatch_refuses_and_names_the_reason(self, approved) -> None:
        """The gate that stops an observation from another encoding being scored."""
        import dataclasses as dc

        from afterlap_core.learning.features import FeatureEncoder

        encoded = FeatureEncoder().encode(estimate_with(), context())
        mismatched = dc.replace(encoded, feature_hash="sha256:a-different-schema")
        prediction = approved.predict_continuation(mismatched)
        assert prediction.value is None
        assert prediction.in_support is False
        assert prediction.reason == SupportReason.FEATURE_HASH_MISMATCH.value
        assert "different feature revision" in support_reason_text(prediction.reason)

    def test_an_unavailable_value_is_never_zero(self, unapproved, encoder, feature_context) -> None:
        prediction = unapproved.predict_continuation(_encoded(encoder, feature_context))
        assert prediction.value is None
        assert prediction.as_dict()["value"] is None

    def test_a_service_without_an_ensemble_says_so(self, tmp_path, encoder, feature_context) -> None:
        directory = tmp_path / "no-ensemble"
        directory.mkdir()
        _write(
            directory,
            approval=ApprovalStatus.APPROVED,
            promotion=_enabled_policy(),
            with_ensemble=False,
            with_calibrator=False,
        )
        service = service_from_directory(directory)
        prediction = service.predict_continuation(_encoded(encoder, feature_context))
        assert prediction.value is None
        assert prediction.reason == "no_continuation_ensemble"


class TestCalibrationThroughTheService:
    def test_an_unfrozen_calibrator_publishes_no_calibrated_value(self, tmp_path) -> None:
        directory = tmp_path / "unfrozen-calibrator"
        directory.mkdir()
        _write(
            directory,
            approval=ApprovalStatus.APPROVED,
            promotion=_enabled_policy(),
            calibrator_frozen=False,
        )
        service = service_from_directory(directory)
        result = service.calibrate(EVENT, 0.5)
        assert result.value is None
        assert result.status == CalibratorStatus.NOT_FROZEN
        assert service.calibration_status(EVENT) is CalibrationStatus.UNCALIBRATED

    def test_a_frozen_calibrator_publishes_a_calibrated_value(self, approved) -> None:
        result = approved.calibrate(EVENT, 0.5)
        assert result.value is not None
        assert result.status == CalibratorStatus.CALIBRATED
        assert approved.calibration_status(EVENT) is CalibrationStatus.CALIBRATED

    def test_an_uncalibrated_event_reports_unavailable(self, approved) -> None:
        assert approved.calibration_status("finish_ahead(checkpoint=x)") is CalibrationStatus.UNAVAILABLE

    def test_a_disabled_service_reports_no_calibrator(self, unapproved) -> None:
        result = unapproved.calibrate(EVENT, 0.5)
        assert result.value is None
        assert result.status == CalibratorStatus.NO_CALIBRATOR
        assert unapproved.calibration_status(EVENT) is CalibrationStatus.UNAVAILABLE

    def test_a_bundle_with_no_calibration_map_carries_the_written_reason(self, tmp_path) -> None:
        """``write_bundle`` writes an explicit unavailable placeholder."""
        directory = tmp_path / "no-calibrator"
        directory.mkdir()
        _write(directory, with_calibrator=False)
        payload = json.loads((directory / "calibrator.json").read_text(encoding="utf-8"))
        assert payload["status"] == "unavailable"
        service = service_from_directory(directory)
        assert service.calibrator is None
        assert "no calibration set exists" in service.calibrator_detail


class TestIdentityTravels:
    def test_the_identity_names_what_produced_a_prediction(self, approved) -> None:
        identity = approved.identity()
        assert identity["bundle_id"] == "prediction-under-test"
        assert identity["weights_hash"].startswith("sha256:")
        assert identity["feature_schema_hash"] == ENERGY_V1.content_hash()
        assert identity["rule_family"] == RULE_FAMILY
        assert identity["reward_revision"] == REWARD_REVISION
        assert identity["calibrator_id"] is not None
        assert identity["learned_contribution_enabled"] is True

    def test_the_service_record_is_json_shaped(self, approved) -> None:
        payload = approved.as_dict()
        json.dumps(payload)
        assert payload["available"] is True
        assert payload["support_thresholds"] is not None
