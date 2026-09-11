"""The adapter that connects the real planner, and the learned model, to a session.

On the audited revision the runtime hardwired ``BaselinePlanner`` at four sites
and ``default_planner`` -- the function whose whole job was to prefer the MPC
planner -- had zero callers. The one adapter that existed passed ``None`` for
``model_bundle`` and supplied neither ``proposal``, ``world`` nor
``current_plan``, so the learned seams on ``plan()`` were reachable only from
the training environment.

This adapter closes that. It supplies, per decision:

``world``
    the session's own scenario bundle, so re-simulation happens against the
    circuit the session is actually running. The planner's fallback is the
    fixture ``two-straight-counterattack``, which would have re-simulated every
    session's candidates in the wrong scenario.
``current_plan``
    the instruction now in force, so hysteresis, minimum dwell and incumbent
    preference apply instead of the planner re-deciding from scratch each tick.
``model_bundle`` and ``calibrator``
    the learned continuation ensemble and probability calibrator, but only when
    an approved and promoted bundle is pinned for this session.
``proposal``
    the frozen actor's warm start, decoded under this tick's reachable bounds.

Three boundaries this does not cross
------------------------------------

**The learning extra is optional.** ``torch`` is not a runtime dependency, so
every learned component is loaded through a duck-typed handle and its absence
is an ordinary unavailable result naming the baseline. A session on a default
install behaves exactly as it did before.

**The actor cannot buy an illegal plan.** Its output is a warm start for the
solve. The feasible set, the independent checker and the baseline candidates are
untouched, and the checker's verdict on the resulting plan is still final.

**The encoding is the training encoding.** The observation the actor sees is
built by ``learning.bridge.ObservationBridge`` -- the same component training
used -- rather than re-derived here from the session's estimate. Feeding a model
an observation assembled by a different estimator would be an input-distribution
mismatch that nothing downstream could detect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.util import find_spec
from typing import TYPE_CHECKING, Any

from afterlap_contracts import PlanningResult
from afterlap_core.planning import (
    DEFAULT_DEADLINE_S,
    ActivePlan,
    BudgetProposal,
    PlanningWorld,
    active_plan_from,
)

if TYPE_CHECKING:
    from afterlap_core.rules import RulePack
    from afterlap_core.simulation import Observation, ScenarioBundle

    from .baseline_planner import PlanRequest

__all__ = [
    "LEARNED_PLANNER_IDENTITY",
    "LearnedPlannerAdapter",
    "LearnedPlannerNotes",
    "build_learned_planner",
]

LEARNED_PLANNER_IDENTITY = "afterlap-core-planning"
_PROPOSAL_SOURCE = "learned-actor/energy-v1"


@dataclass(frozen=True, slots=True)
class LearnedPlannerNotes:
    """What contributed to the last decision, and what did not and why.

    Published rather than logged: an engineer reading a recommendation needs to
    know whether a learned model touched it, and a boolean cannot say *why not*.
    """

    encoded_available: bool = False
    proposal_supplied: bool = False
    continuation_supplied: bool = False
    calibrator_supplied: bool = False
    continuation_value: float | None = None
    continuation_disagreement: float | None = None
    continuation_in_support: bool = False
    support_reason: str | None = None
    bundle_id: str | None = None
    weights_hash: str | None = None
    calibrator_id: str | None = None
    member_count: int | None = None
    unavailable_reasons: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "encoded_available": self.encoded_available,
            "proposal_supplied": self.proposal_supplied,
            "continuation_supplied": self.continuation_supplied,
            "calibrator_supplied": self.calibrator_supplied,
            "continuation_value": self.continuation_value,
            "continuation_disagreement": self.continuation_disagreement,
            "continuation_in_support": self.continuation_in_support,
            "support_reason": self.support_reason,
            "bundle_id": self.bundle_id,
            "weights_hash": self.weights_hash,
            "calibrator_id": self.calibrator_id,
            "member_count": self.member_count,
            "unavailable_reasons": list(self.unavailable_reasons),
        }


class LearnedPlannerAdapter:
    """Adapts ``afterlap_core.planning.plan`` to the session runtime's protocol."""

    identity = LEARNED_PLANNER_IDENTITY

    def __init__(
        self,
        plan_fn: Any,
        *,
        bundle: ScenarioBundle,
        pack: RulePack,
        session_id: str,
        prediction: Any | None = None,
        seed: int = 0,
        plan_validity_s: float = 4.0,
        rollout_enabled: bool = True,
    ) -> None:
        self._plan = plan_fn
        self._bundle = bundle
        self._pack = pack
        self._session_id = session_id
        self._prediction = prediction
        self._seed = seed
        self._plan_validity_s = float(plan_validity_s)
        self._rollout_enabled = rollout_enabled
        self._world = PlanningWorld(
            bundle=bundle,
            ego_car_id=bundle.scenario.ego_car_id,
            rival_car_id=(bundle.scenario.rival_ids[0] if bundle.scenario.rival_ids else None),
            seed=seed,
        )
        self._active_plan: ActivePlan | None = None
        self._bridge: Any | None = None
        self._encoder: Any | None = None
        self._encoded: Any | None = None
        self._notes = LearnedPlannerNotes()
        self._bridge_detail = ""
        self._build_bridge()

    def _build_bridge(self) -> None:
        """Attach the training-side encoder, or record why there is none.

        ``learning.bridge`` and ``learning.features`` are torch-free, so this
        succeeds on a default install; only the models themselves need the
        optional extra.
        """
        try:
            from afterlap_core.learning.bridge import ObservationBridge
            from afterlap_core.learning.features import FeatureEncoder
        except ImportError as exc:
            self._bridge_detail = (
                f"the learning package is not importable, so no learned observation can be encoded: {exc}"
            )
            return
        try:
            self._bridge = ObservationBridge(
                bundle=self._bundle,
                pack=self._pack,
                session_id=self._session_id,
                seed=self._seed,
            )
            self._encoder = FeatureEncoder()
        except Exception as exc:
            self._bridge = None
            self._bridge_detail = f"the learned observation encoder could not be built: {exc}"

    @property
    def notes(self) -> LearnedPlannerNotes:
        """What contributed to the most recent decision."""
        return self._notes

    @property
    def prediction(self) -> Any | None:
        return self._prediction

    def observe(self, observation: Observation) -> None:
        """Feed one delivered observation to the learned encoder.

        Failures are recorded, never raised: a learned encoding that cannot be
        built is a reason to fall back to the baseline, not a reason to stop a
        session from planning.
        """
        if self._bridge is None or self._encoder is None:
            return
        try:
            tick = self._bridge.observe(observation)
            self._encoded = self._encoder.encode(tick.estimate, tick.feature_context)
        except Exception as exc:
            self._encoded = None
            self._bridge_detail = f"the learned observation encoder refused a tick: {exc}"
            return
        self._bridge_detail = ""

    def record_instruction_change(self, at_s: float) -> None:
        if self._bridge is not None:
            self._bridge.record_instruction_change(at_s)

    def reset(self) -> None:
        """Clear per-episode learned state. The world and models are unchanged."""
        if self._bridge is not None:
            self._bridge.reset()
        self._encoded = None
        self._active_plan = None
        self._notes = LearnedPlannerNotes()

    def _proposal(self, request: PlanRequest) -> tuple[BudgetProposal | None, str | None]:
        """The actor's warm start, or the reason there is none."""
        service = self._prediction
        if service is None or not getattr(service, "enabled", False):
            return None, None
        if self._encoded is None:
            return None, "no learned observation was encoded for this tick"
        try:
            from afterlap_core.learning.actions import compute_bounds, decode_action
        except ImportError as exc:
            return None, f"the learning extra is not installed: {exc}"

        action = service.propose(self._encoded.observation)
        if action is None:
            return None, "the frozen actor produced no action"
        bounds = compute_bounds(
            request.estimate,
            request.rule_context.applicable_limits,
            checkpoint_interval_s=request.horizon_s,
        )
        decoded = decode_action(action, bounds)
        if not decoded.learned_enabled or decoded.budget_j is None:
            return None, f"the actor preference was not usable: {decoded.reason}"
        window = max(1, len(request.admissible) or 1)
        deploy = tuple([float(decoded.budget_j) / window] * window)
        harvest = tuple([0.0] * window)
        return BudgetProposal(deploy_j=deploy, harvest_j=harvest, source=_PROPOSAL_SOURCE), None

    def _continuation(self) -> tuple[Any | None, str | None]:
        """The continuation adapter pinned to this tick's encoding."""
        service = self._prediction
        if service is None or not getattr(service, "enabled", False):
            return None, None
        adapter = service.continuation_adapter()
        if adapter is None:
            return None, service.ensemble_detail or "no continuation ensemble is bundled"
        if self._encoded is None:
            return None, "no learned observation was encoded, so no terminal state can be built"
        adapter.set_reference(self._encoded)
        return adapter, None

    def _published_continuation(
        self, continuation: Any | None
    ) -> tuple[float | None, float | None, bool, str | None]:
        """``(value, disagreement, in_support, reason)`` for publication.

        Evaluated at the decision-time encoding, which is what the planner's own
        support gate saw. The value is dropped unless the model was in support,
        so a published number never comes from outside the validated regime; the
        disagreement is kept either way, because a refusal caused by ensemble
        spread is more informative with the number attached.
        """
        service = self._prediction
        if service is None or continuation is None or self._encoded is None:
            return None, None, False, None
        score = service.predict_continuation(self._encoded)
        return (
            score.value if score.in_support else None,
            score.disagreement,
            bool(score.in_support),
            score.reason,
        )

    @staticmethod
    def _restamp(result: PlanningResult, request: PlanRequest) -> PlanningResult:
        """Translate the planner's revision numbering into the session's.

        ``afterlap_core.planning.plan`` stamps ``state_revision`` from the
        *estimate* it planned against; the session runtime's revision guard
        compares it against the *plan request* revision it issued. Those are two
        different counters, so an otherwise valid result was discarded at
        ``accept_plan_result`` on every tick and the session withdrew advice
        forever.

        Re-stamping is a coordinate change, not a claim: the result really was
        computed for this request, and the estimate's own revision remains on
        the estimate. ``BaselinePlanner`` already stamps the request revision,
        which is why the defect only appeared once the real planner was wired
        in.
        """
        if result.state_revision == request.revision:
            return result
        accepted = tuple(plan.revise(state_revision=request.revision) for plan in result.accepted)
        rejected = tuple(plan.revise(state_revision=request.revision) for plan in result.rejected)
        return result.revise(state_revision=request.revision, accepted=accepted, rejected=rejected)

    def plan(self, request: PlanRequest) -> PlanningResult:
        """Plan one decision with everything the session actually has."""
        reasons: list[str] = []
        if not self._rollout_enabled:
            reasons.append(
                "scenario re-simulation is disabled for this session, so no event probability "
                "and no outcome range is published; enabling it needs a planner deadline above "
                "the declared operational budget"
            )
        if self._bridge_detail:
            reasons.append(self._bridge_detail)

        service = self._prediction
        if service is None:
            reasons.append(
                f"no learned bundle is pinned for this session; {request.baseline_identity} answers"
            )
        elif not getattr(service, "enabled", False):
            reasons.extend(getattr(service, "notes", ()) or ())

        proposal, proposal_reason = self._proposal(request)
        if proposal_reason:
            reasons.append(proposal_reason)
        continuation, continuation_reason = self._continuation()
        if continuation_reason:
            reasons.append(continuation_reason)
        calibrator = service.probability_calibration() if service is not None else None
        if service is not None and calibrator is None and getattr(service, "calibrator_detail", ""):
            reasons.append(service.calibrator_detail)

        result = self._plan(
            request.estimate,
            request.rule_context,
            continuation,
            request.deadline_s or DEFAULT_DEADLINE_S,
            manifest=request.manifest,
            world=self._world,
            current_plan=self._active_plan,
            proposal=proposal,
            admissible=request.admissible or None,
            now_s=request.now_s,
            seed=self._seed,
            rollout_enabled=self._rollout_enabled,
            calibrator=calibrator,
        )

        result = self._restamp(result, request)
        prediction = self._published_continuation(continuation)
        self._notes = LearnedPlannerNotes(
            encoded_available=self._encoded is not None,
            proposal_supplied=proposal is not None,
            continuation_supplied=continuation is not None,
            calibrator_supplied=calibrator is not None,
            continuation_value=prediction[0],
            continuation_disagreement=prediction[1],
            continuation_in_support=prediction[2],
            support_reason=prediction[3],
            bundle_id=None if service is None else getattr(service, "bundle_id", None),
            weights_hash=None if service is None else getattr(service, "model_hash", None),
            calibrator_id=None if calibrator is None else calibrator.calibrator_id,
            member_count=(
                None
                if service is None or getattr(service, "ensemble", None) is None
                else service.ensemble.member_count
            ),
            unavailable_reasons=tuple(dict.fromkeys(reason for reason in reasons if reason)),
        )

        self._active_plan = (
            active_plan_from(
                result,
                request.rule_context,
                selected_at_s=request.now_s,
                validity_s=self._plan_validity_s,
            )
            or self._active_plan
        )
        return result


def build_learned_planner(
    *,
    bundle: ScenarioBundle,
    pack: RulePack,
    session_id: str,
    prediction: Any | None = None,
    seed: int = 0,
    plan_validity_s: float = 4.0,
    rollout_enabled: bool = True,
) -> tuple[Any, str]:
    """The real planner when it is importable, otherwise the baseline.

    Returns the planner and a note recording which path was taken, so a decision
    record names the planner that produced it rather than the one that was hoped
    for. This is what ``default_planner`` was written to do and never called to
    do; the difference is that this one is wired in.
    """
    if find_spec("casadi") is None:
        from .baseline_planner import BaselinePlanner

        return BaselinePlanner(), "the solver extra is unavailable; using the baseline"
    try:
        from afterlap_core.planning import plan as external_plan
    except ImportError as exc:
        from .baseline_planner import BaselinePlanner

        return BaselinePlanner(), f"afterlap_core.planning is unavailable ({exc}); using the baseline"
    return (
        LearnedPlannerAdapter(
            external_plan,
            bundle=bundle,
            pack=pack,
            session_id=session_id,
            prediction=prediction,
            seed=seed,
            plan_validity_s=plan_validity_s,
            rollout_enabled=rollout_enabled,
        ),
        f"{LEARNED_PLANNER_IDENTITY} (afterlap_core.planning.plan)",
    )
