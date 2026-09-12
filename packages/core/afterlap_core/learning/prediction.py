"""The serving surface for prediction: one object, or an explicit unavailable.

Three separately fitted things predict something in this system -- the
continuation-return ensemble, the probability calibrator, and the actor whose
proposal shapes what gets predicted about -- and each has its own support gate.
Wiring them into a runtime one at a time means three places to forget a gate,
and a forgotten gate is a confident number from a model outside its regime.

:class:`PredictionService` is the single object a runtime holds. It is built
from a validated bundle, it reports its own identity, and every method either
returns a value with its support verdict or returns an explicit unavailable
result naming the reason. It has no constructor that produces a partly enabled
service: :meth:`from_bundle` returns a :class:`PredictionUnavailable` instead.

What it deliberately does not do
--------------------------------

* It does not enable itself. A bundle contributes only when it is approved
  *and* its promotion policy is on, which is ``LoadedBundle``'s existing rule;
  a service built from an unapproved bundle reports ``enabled=False`` and every
  prediction carries that.
* It does not average away a disagreement. The ensemble spread is published, and
  the frozen support threshold decides whether the value may be used at all.
* It does not fill an absent prediction with zero. Every unavailable path
  returns ``None`` with a reason string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from afterlap_contracts import ApprovalStatus, CalibrationStatus, SupportThresholds

from ..feature_manifest import ENERGY_V1
from .calibration import CalibratedProbability, CalibratorStatus, ProbabilityCalibrator
from .features import EncodedObservation
from .policy import ActorPolicy, PolicyLoadError, load_actor
from .serving import BundleRejection, LoadedBundle, load_bundle
from .value import ContinuationEnsemble, PlannerContinuationAdapter, SupportReason

__all__ = [
    "ContinuationPrediction",
    "PredictionService",
    "PredictionUnavailable",
    "build_prediction_service",
]


@dataclass(frozen=True, slots=True)
class PredictionUnavailable:
    """No prediction service could be built. The named baseline takes over."""

    reason: str
    detail: str
    baseline_identity: str
    bundle_directory: str | None = None

    @property
    def enabled(self) -> bool:
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": False,
            "enabled": False,
            "reason": self.reason,
            "detail": self.detail,
            "baseline_identity": self.baseline_identity,
            "bundle_directory": self.bundle_directory,
        }


@dataclass(frozen=True, slots=True)
class ContinuationPrediction:
    """One continuation-return prediction with its support verdict.

    ``value`` is ``None`` when the prediction may not be used. The disagreement
    is published either way, because a refusal caused by disagreement is more
    informative with the number attached.
    """

    value: float | None
    disagreement: float | None
    in_support: bool
    reason: str
    member_values: tuple[float, ...] = ()
    bundle_id: str | None = None
    member_count: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "disagreement": self.disagreement,
            "in_support": self.in_support,
            "reason": self.reason,
            "member_values": list(self.member_values),
            "bundle_id": self.bundle_id,
            "member_count": self.member_count,
        }


_DISABLED_REASON = "learned_contribution_disabled"


@dataclass(frozen=True, slots=True)
class PredictionService:
    """Every learned prediction from one bundle, behind its own support gates."""

    bundle: LoadedBundle
    actor: ActorPolicy | None
    ensemble: ContinuationEnsemble | None
    calibrator: ProbabilityCalibrator | None
    support: SupportThresholds | None
    actor_detail: str = ""
    calibrator_detail: str = ""
    ensemble_detail: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def bundle_id(self) -> str:
        return self.bundle.manifest.id

    @property
    def enabled(self) -> bool:
        """A bundle contributes only when approved *and* promotion is on."""
        return self.bundle.learned_contribution_enabled

    @property
    def baseline_identity(self) -> str:
        return self.bundle.baseline_identity

    @property
    def model_hash(self) -> str:
        return self.bundle.manifest.weights_hash

    def identity(self) -> dict[str, Any]:
        """What produced a prediction, in one place, for a published payload."""
        manifest = self.bundle.manifest
        return {
            "bundle_id": manifest.id,
            "weights_hash": manifest.weights_hash,
            "feature_schema_hash": manifest.feature_schema_hash,
            "rule_family": manifest.rule_family,
            "reward_revision": manifest.reward_revision,
            "approval_status": manifest.approval_status.value,
            "promotion_enabled": bool(manifest.promotion_policy.enabled),
            "learned_contribution_enabled": self.enabled,
            "baseline_identity": self.baseline_identity,
            "continuation_controller": manifest.continuation_controller,
            "calibrator_id": None if self.calibrator is None else self.calibrator.calibrator_id,
            "actor_available": self.actor is not None,
            "ensemble_available": self.ensemble is not None,
            "calibrator_available": self.calibrator is not None,
            "supported_track_ids": list(manifest.supported_track_ids),
            "supported_scenario_families": list(manifest.supported_scenario_families),
        }

    def continuation_adapter(self) -> PlannerContinuationAdapter | None:
        """The planner-protocol view of the ensemble, or ``None`` when disabled."""
        if not self.enabled or self.ensemble is None:
            return None
        return PlannerContinuationAdapter(self.ensemble)

    def probability_calibration(self) -> ProbabilityCalibrator | None:
        """The planner-protocol view of the calibrator, or ``None`` when disabled."""
        if not self.enabled:
            return None
        return self.calibrator

    def predict_continuation(self, encoded: EncodedObservation) -> ContinuationPrediction:
        """The continuation return for one encoded observation."""
        if not self.enabled:
            return ContinuationPrediction(
                value=None,
                disagreement=None,
                in_support=False,
                reason=_DISABLED_REASON,
                bundle_id=self.bundle_id,
            )
        if self.ensemble is None:
            return ContinuationPrediction(
                value=None,
                disagreement=None,
                in_support=False,
                reason="no_continuation_ensemble",
                bundle_id=self.bundle_id,
            )
        score = self.ensemble.score(encoded)
        return ContinuationPrediction(
            value=score.value if score.in_support else None,
            disagreement=score.disagreement,
            in_support=score.in_support,
            reason=score.reason.value,
            member_values=score.member_values,
            bundle_id=self.ensemble.bundle_id,
            member_count=self.ensemble.member_count,
        )

    def propose(self, observation: np.ndarray) -> np.ndarray | None:
        """The actor's raw preference vector, or ``None`` when unavailable."""
        if not self.enabled or self.actor is None:
            return None
        try:
            return self.actor.act(observation)
        except PolicyLoadError:
            return None

    def calibrate(self, event_definition: str, raw_frequency: float) -> CalibratedProbability:
        """One calibrated probability, or the refusal that explains its absence."""
        if not self.enabled:
            return CalibratedProbability(
                value=None,
                raw_frequency=float(raw_frequency),
                status=CalibratorStatus.NO_CALIBRATOR,
                detail=(
                    "the learned contribution is disabled for this bundle, so no calibrated "
                    "probability is published"
                ),
            )
        if self.calibrator is None:
            return CalibratedProbability(
                value=None,
                raw_frequency=float(raw_frequency),
                status=CalibratorStatus.NO_CALIBRATOR,
                detail=self.calibrator_detail or "this bundle carries no calibration map",
            )
        return self.calibrator.apply(event_definition, raw_frequency)

    def calibration_status(self, event_definition: str) -> CalibrationStatus:
        """What a payload may claim about this event before one is computed."""
        if not self.enabled or self.calibrator is None:
            return CalibrationStatus.UNAVAILABLE
        if event_definition not in self.calibrator.event_definitions:
            return CalibrationStatus.UNAVAILABLE
        if not self.calibrator.frozen_before_final_test:
            return CalibrationStatus.UNCALIBRATED
        return CalibrationStatus.CALIBRATED

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": True,
            **self.identity(),
            "actor_detail": self.actor_detail,
            "ensemble_detail": self.ensemble_detail,
            "calibrator_detail": self.calibrator_detail,
            "support_thresholds": (None if self.support is None else self.support.model_dump(mode="json")),
            "notes": list(self.notes),
        }


def build_prediction_service(
    bundle: LoadedBundle,
) -> PredictionService:
    """Assemble a service from an already validated bundle.

    Component absence is recorded rather than raised: a bundle with an actor and
    no ensemble is a real, useful artifact, and refusing to serve it at all would
    be worse than serving it with the continuation prediction reported
    unavailable.
    """
    notes: list[str] = []

    actor: ActorPolicy | None = None
    actor_detail = ""
    try:
        actor = load_actor(bundle.actor_state, bundle_id=bundle.manifest.id)
    except PolicyLoadError as exc:
        actor_detail = f"the actor could not be rebuilt: {exc}"
        notes.append(actor_detail)

    ensemble_detail = ""
    if bundle.ensemble is None:
        ensemble_detail = "no continuation ensemble is bundled; the planner uses its analytic terminal term"
        notes.append(ensemble_detail)
    elif not bundle.ensemble.support.frozen_before_final_test:
        ensemble_detail = "the bundled continuation support thresholds are not frozen before a final test"
        notes.append(ensemble_detail)

    calibrator = ProbabilityCalibrator.from_dict(bundle.calibrator or {})
    calibrator_detail = ""
    if calibrator is None:
        detail = (bundle.calibrator or {}).get("detail")
        calibrator_detail = str(
            detail or "this bundle carries no calibration map; event probabilities stay uncalibrated"
        )
        notes.append(calibrator_detail)
    elif not calibrator.frozen_before_final_test:
        calibrator_detail = (
            "the bundled calibrator is not frozen before a final test, so its output is not "
            "published as calibrated"
        )
        notes.append(calibrator_detail)

    if bundle.manifest.approval_status is not ApprovalStatus.APPROVED:
        notes.append(
            f"bundle approval status is {bundle.manifest.approval_status.value!r}; every learned "
            f"prediction is reported unavailable and {bundle.baseline_identity} answers instead"
        )
    elif not bundle.promotion_policy.enabled:
        notes.append(
            "the frozen promotion policy is disabled, so an approved bundle still contributes nothing"
        )

    return PredictionService(
        bundle=bundle,
        actor=actor,
        ensemble=bundle.ensemble,
        calibrator=calibrator,
        support=bundle.support,
        actor_detail=actor_detail,
        ensemble_detail=ensemble_detail,
        calibrator_detail=calibrator_detail,
        notes=tuple(notes),
    )


def service_from_directory(
    directory: Path,
    *,
    expected_rule_family: str | None = None,
    expected_reward_revision: str | None = None,
    expected_environment_version: str | None = None,
    require_approved: bool = False,
    baseline_identity: str | None = None,
) -> PredictionService | PredictionUnavailable:
    """Load a bundle and build a service, or explain why neither happened.

    Every rejection reason from the loader is preserved: the caller needs to
    publish *which* mismatch disabled the learned contribution, not merely that
    one did.
    """
    from .serving import DEFAULT_BASELINE_IDENTITY

    fallback = baseline_identity or DEFAULT_BASELINE_IDENTITY
    try:
        bundle = load_bundle(
            Path(directory),
            expected_feature_hash=ENERGY_V1.content_hash(),
            expected_rule_family=expected_rule_family,
            expected_reward_revision=expected_reward_revision,
            expected_environment_version=expected_environment_version,
            require_approved=require_approved,
            baseline_identity=fallback,
        )
    except BundleRejection as exc:
        return PredictionUnavailable(
            reason=exc.reason.value,
            detail=exc.detail,
            baseline_identity=exc.baseline_identity,
            bundle_directory=str(directory).replace("\\", "/"),
        )
    return build_prediction_service(bundle)


def support_reason_text(reason: SupportReason | str) -> str:
    """A one-line explanation for a support refusal, for a published payload."""
    value = reason.value if isinstance(reason, SupportReason) else str(reason)
    return {
        SupportReason.IN_SUPPORT.value: "the observation is inside the validated regime",
        SupportReason.FEATURE_HASH_MISMATCH.value: (
            "the observation was encoded under a different feature revision"
        ),
        SupportReason.CLIP_FRACTION_EXCEEDED.value: (
            "too many features were clipped, so the observation is outside the fitted range"
        ),
        SupportReason.KNOWN_MASK_TOO_LOW.value: (
            "too much of the observation is unknown to evaluate the model on it"
        ),
        SupportReason.DISAGREEMENT_EXCEEDED.value: (
            "the ensemble members disagree beyond the frozen threshold"
        ),
        SupportReason.NON_FINITE_OUTPUT.value: "a member produced a non-finite value",
        SupportReason.THRESHOLDS_NOT_FROZEN.value: (
            "the support thresholds are not frozen before a final test"
        ),
    }.get(value, value)


__all__ += ["service_from_directory", "support_reason_text"]
