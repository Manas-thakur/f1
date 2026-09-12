"""Planner-backed controllers for the comparison matrix.

Four of the six matrix rows in ``evaluation.controllers.COMPARISON_MATRIX`` were
declared unmeasurable, three of them because no controller existed that ran the
MPC planner. One did exist -- in ``tests/acceptance/conftest.py`` -- which meant
the acceptance suite proved a row the benchmark harness could not run.

These live in ``planning`` rather than in ``evaluation`` on purpose.
``tests/evaluation/test_independent_ledger.py`` asserts that no module under
``afterlap_core/evaluation`` imports ``afterlap_core.planning``, so the harness
stays independent of the planner it scores. Putting the adapter on the planner's
side of that line keeps the invariant intact: evaluation still knows only the
``Controller`` protocol.

The rows
--------

``mpc_only``
    the planner with no learned input at all. The reference the promotion
    protocol compares against.
``mpc_plus_actor``
    the planner warm-started by a frozen actor's budget preference.
``mpc_plus_value``
    the planner with the learned continuation ensemble reranking finalists.
``full_system``
    both.

Every row runs the *same* planner through the *same* independent checker. A
candidate the checker refuses withdraws advice rather than reaching the car, and
a result that is not ``ok`` withdraws, so a learned row cannot win a comparison
by proposing something illegal.

``without_contribution`` is implemented, so each learned row is genuinely
ablatable and an ablation is a measurement rather than an unmeasured stub.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from afterlap_contracts import (
    CheckStatus,
    DeploymentProfile,
    PlanningStatus,
    ReasonCode,
    StateEstimate,
)

from ..evaluation.controllers import AblationUnsupported, ControlDecision, ControlRequest
from ..simulation import DriverAction
from .planner import plan as run_planner
from .publication import selected_candidate
from .rollout import PlanningWorld

if TYPE_CHECKING:
    from ..rules import RulePack
    from ..simulation import ScenarioBundle

__all__ = [
    "MATRIX_ROW_NAMES",
    "PlannerController",
    "matrix_controllers",
]

MATRIX_ROW_NAMES = ("mpc_only", "mpc_plus_actor", "mpc_plus_value", "full_system")
_MIN_BUDGET_S = 0.05


@dataclass(frozen=True, slots=True)
class _LearnedHandles:
    """What a learned row was given, after its own gates were applied."""

    continuation: Any | None = None
    proposal: Any | None = None
    calibrator: Any | None = None
    bundle_id: str | None = None
    detail: str = ""


class PlannerController:
    """One comparison-matrix row backed by the real MPC planner.

    ``estimate_adapter`` converts a controller observation into the planner's
    ``StateEstimate``. It is injected rather than built here because the harness
    hands controllers an ``Observation`` and the planner needs a belief, and the
    conversion is a property of the evaluation setup rather than of the planner.
    """

    def __init__(
        self,
        pack: RulePack,
        bundle: ScenarioBundle,
        *,
        name: str = "mpc_only",
        estimate_adapter: Any,
        prediction: Any | None = None,
        uses_actor: bool = False,
        uses_learned_return: bool = False,
        seed: int = 42,
        rollout_enabled: bool = True,
    ) -> None:
        if name not in MATRIX_ROW_NAMES:
            raise ValueError(f"unknown matrix row {name!r}; expected one of {list(MATRIX_ROW_NAMES)}")
        if (uses_actor or uses_learned_return) and prediction is None:
            raise ValueError(
                f"row {name!r} declares a learned contribution but no prediction service was "
                "supplied; a row that cannot use a model must not claim to"
            )
        self._pack = pack
        self._bundle = bundle
        self._name = name
        self._adapter = estimate_adapter
        self._prediction = prediction
        self._uses_actor = uses_actor
        self._uses_learned_return = uses_learned_return
        self._seed = seed
        self._rollout_enabled = rollout_enabled
        self._world = PlanningWorld(
            bundle=bundle,
            ego_car_id=bundle.scenario.ego_car_id,
            rival_car_id=(bundle.scenario.rival_ids[0] if bundle.scenario.rival_ids else None),
            seed=seed,
        )
        self._revision = 0
        self.results: list[Any] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def uses_actor(self) -> bool:
        return self._uses_actor

    @property
    def uses_learned_return(self) -> bool:
        return self._uses_learned_return

    def without_contribution(self, target: str) -> PlannerController:
        """The same row with one learned contribution removed.

        Returns a controller, not a flag: the ablated run must go through the
        same planner with the input genuinely absent, because a flag the planner
        never reads would leave the contribution in place.
        """
        if target == "none":
            return self
        if target == "policy":
            actor, value = False, self._uses_learned_return
        elif target == "terminal":
            actor, value = self._uses_actor, False
        else:
            raise AblationUnsupported(f"cannot drop {target!r}; expected 'policy' or 'terminal'")
        if not (actor or value):
            row = "mpc_only"
        elif actor and not value:
            row = "mpc_plus_actor"
        elif value and not actor:
            row = "mpc_plus_value"
        else:  # pragma: no cover - unreachable, one contribution was dropped
            row = "full_system"
        return PlannerController(
            self._pack,
            self._bundle,
            name=row,
            estimate_adapter=self._adapter,
            prediction=self._prediction if (actor or value) else None,
            uses_actor=actor,
            uses_learned_return=value,
            seed=self._seed,
            rollout_enabled=self._rollout_enabled,
        )

    def _handles(self, request: ControlRequest, estimate: StateEstimate) -> _LearnedHandles:
        """The learned inputs this row is entitled to, after their own gates."""
        service = self._prediction
        if service is None or not (self._uses_actor or self._uses_learned_return):
            return _LearnedHandles()
        if not getattr(service, "enabled", False):
            return _LearnedHandles(
                detail="the pinned bundle is not approved and promoted, so nothing learned applied"
            )

        continuation = None
        proposal = None
        detail = ""
        if self._uses_learned_return:
            continuation = service.continuation_adapter()
            if continuation is None:
                detail = getattr(service, "ensemble_detail", "") or "no continuation ensemble"
        if self._uses_actor:
            proposal, reason = self._proposal(request, estimate)
            if reason:
                detail = f"{detail}; {reason}" if detail else reason
        return _LearnedHandles(
            continuation=continuation,
            proposal=proposal,
            calibrator=service.probability_calibration(),
            bundle_id=getattr(service, "bundle_id", None),
            detail=detail,
        )

    def _proposal(self, request: ControlRequest, estimate: StateEstimate) -> tuple[Any | None, str]:
        encoded = getattr(request, "encoded_observation", None)
        if encoded is None:
            return None, "no learned observation was encoded for this decision"
        try:
            from ..learning.actions import compute_bounds, decode_action
        except ImportError as exc:
            return None, f"the learning extra is not installed: {exc}"
        prediction = self._prediction
        if prediction is None:
            return None, "no frozen actor is loaded for this session"
        action = prediction.propose(encoded.observation)
        if action is None:
            return None, "the frozen actor produced no action"
        rule_context = request.rule_context
        if rule_context is None:
            return None, "no rule context was resolved for this decision"
        bounds = compute_bounds(estimate, rule_context.applicable_limits, checkpoint_interval_s=20.0)
        decoded = decode_action(action, bounds)
        if not decoded.learned_enabled or decoded.budget_j is None:
            return None, f"the actor preference was not usable: {decoded.reason}"
        from .planner import BudgetProposal

        return (
            BudgetProposal(
                deploy_j=(float(decoded.budget_j),),
                harvest_j=(0.0,),
                source=f"learned-actor/{self._name}",
            ),
            "",
        )

    def decide(self, request: ControlRequest) -> ControlDecision:
        """One decision, through the planner and its independent checker."""
        if request.rule_context is None or not request.observation.channels:
            return ControlDecision(
                controller=self._name,
                status=PlanningStatus.INPUT_UNAVAILABLE,
                action=None,
                reasons=(ReasonCode.STALE_OBSERVATIONS,),
                provenance="withdrawn",
                detail="no observation old enough to plan from",
            )
        self._revision += 1
        estimate = self._adapter(
            request.observation,
            now_s=request.session_time_s,
            revision=self._revision,
            track_length_m=self._bundle.track.length,
        )
        handles = self._handles(request, estimate)

        started = time.perf_counter()
        result = run_planner(
            estimate,
            request.rule_context,
            handles.continuation,
            max(_MIN_BUDGET_S, request.compute_budget_ms / 1000.0),
            manifest=self._pack.manifest,
            world=self._world,
            proposal=handles.proposal,
            now_s=request.session_time_s,
            seed=self._seed,
            rollout_enabled=self._rollout_enabled,
            calibrator=handles.calibrator,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        self.results.append(result)

        if result.status is not PlanningStatus.OK or result.selected_plan_id is None:
            return ControlDecision(
                controller=self._name,
                status=result.status,
                action=None,
                reasons=result.reason_codes,
                latency_ms=latency_ms,
                provenance="withdrawn",
                detail=result.detail or handles.detail,
            )
        selected = selected_candidate(result)
        if selected is None or selected.constraint_result.status is not CheckStatus.PASS:
            verdict = "absent" if selected is None else selected.constraint_result.status.value
            return ControlDecision(
                controller=self._name,
                status=PlanningStatus.NO_FEASIBLE_CANDIDATE,
                action=None,
                reasons=(*result.reason_codes, ReasonCode.ELIGIBILITY_UNKNOWN),
                latency_ms=latency_ms,
                provenance="withdrawn",
                detail=f"the selected plan carried a {verdict} checker verdict",
            )
        profile: DeploymentProfile = selected.profile_segments[0].profile_id
        return ControlDecision(
            controller=self._name,
            status=PlanningStatus.OK,
            action=DriverAction(profile=profile, issued_at_s=request.session_time_s, label=selected.id),
            reasons=result.reason_codes,
            latency_ms=latency_ms,
            provenance=(
                f"{result.baseline_identity}"
                if handles.bundle_id is None
                else f"{result.baseline_identity}+{handles.bundle_id}"
            ),
            detail=handles.detail,
        )


def matrix_controllers(
    pack: RulePack,
    bundle: ScenarioBundle,
    *,
    estimate_adapter: Any,
    prediction: Any | None = None,
    seed: int = 42,
    rollout_enabled: bool = True,
) -> tuple[PlannerController, ...]:
    """Every matrix row this setup can actually run.

    ``mpc_only`` always. The three learned rows only when a prediction service
    was supplied, because a row built without one would be the MPC-only row
    wearing a learned row's name -- which is exactly the misreporting the
    unavailable stubs existed to prevent.
    """
    rows: list[PlannerController] = [
        PlannerController(
            pack,
            bundle,
            name="mpc_only",
            estimate_adapter=estimate_adapter,
            seed=seed,
            rollout_enabled=rollout_enabled,
        )
    ]
    if prediction is None:
        return tuple(rows)
    for name, actor, value in (
        ("mpc_plus_actor", True, False),
        ("mpc_plus_value", False, True),
        ("full_system", True, True),
    ):
        rows.append(
            PlannerController(
                pack,
                bundle,
                name=name,
                estimate_adapter=estimate_adapter,
                prediction=prediction,
                uses_actor=actor,
                uses_learned_return=value,
                seed=seed,
                rollout_enabled=rollout_enabled,
            )
        )
    return tuple(rows)
