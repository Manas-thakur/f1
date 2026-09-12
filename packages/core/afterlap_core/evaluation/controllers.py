"""Benchmark controllers and the protocol the comparison matrix is built on.

``learning/SERVING_AND_EVALUATION.md`` names six rows:

======================  =====  ==============  =====================================
Controller              Actor  Learned return  Status in this package
======================  =====  ==============  =====================================
Legal fixed schedule    no     no              implemented here
Legal greedy attacker   no     no              implemented here
MPC-only                no     no              not merged (A06) - explicit stub
MPC + actor             yes    no              not merged (A06/A07) - explicit stub
MPC + value             no     yes             not merged (A06/A07) - explicit stub
Full system             yes    yes             not merged (A06/A07) - explicit stub
======================  =====  ==============  =====================================

The four unmerged rows are represented by :class:`UnavailableController`, which
returns an explicit *unavailable* decision. It never invents a number, and the
report renders those rows as unmeasured rather than as a result.

**Equal observation access is structural.** A controller is handed a
:class:`ControlRequest` and nothing else. That record carries an
``Observation`` (the simulator's only sanctioned controller input path), the
resolved rule context, the compute allowance and the identifiers of the
exogenous disturbance streams. It carries no simulator, no ``WorldState`` and no
rival truth, so no controller can reach further than any other by construction.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from afterlap_contracts import (
    DeploymentProfile,
    PlanningStatus,
    Quality,
    ReasonCode,
    RuleContext,
)
from afterlap_core.simulation.policies import DriverAction

if TYPE_CHECKING:
    from collections.abc import Sequence

    from afterlap_core.simulation.observation import Observation

__all__ = [
    "ACTIVE_PROFILES",
    "AGGRESSION_ORDER",
    "ControlDecision",
    "ControlRequest",
    "Controller",
    "HashCheckedController",
    "LegalFixedSchedule",
    "LegalGreedyAttacker",
    "UnavailableController",
    "assert_no_truth_access",
    "build_request",
]

AGGRESSION_ORDER: tuple[DeploymentProfile, ...] = (
    DeploymentProfile.HARVEST,
    DeploymentProfile.CONSERVE,
    DeploymentProfile.NEUTRAL,
    DeploymentProfile.PUSH,
    DeploymentProfile.OVERTAKE,
)
"""Least to most electrically aggressive. Used only to *downgrade*, never to upgrade."""

ACTIVE_PROFILES: frozenset[DeploymentProfile] = frozenset(
    {DeploymentProfile.PUSH, DeploymentProfile.OVERTAKE}
)
"""Profiles that instruct the driver to spend energy now. These are the
directives that must never be issued confidently under an unknown condition."""

_DEGRADED_REASONS: frozenset[ReasonCode] = frozenset(
    {
        ReasonCode.ELIGIBILITY_UNKNOWN,
        ReasonCode.OWN_ENERGY_UNAVAILABLE,
        ReasonCode.RIVAL_ENERGY_UNKNOWN,
        ReasonCode.STALE_OBSERVATIONS,
        ReasonCode.LEARNED_MODEL_DISABLED,
        ReasonCode.LEARNED_MODEL_OUT_OF_SUPPORT,
        ReasonCode.BASELINE_FALLBACK,
        ReasonCode.SOLVER_TIMEOUT,
    }
)
"""Reasons that mark a decision as qualified rather than confident."""


@dataclass(frozen=True, slots=True)
class ControlRequest:
    """Everything a controller is allowed to see at one decision tick.

    This record is the equal-access boundary. Adding a field that carries
    simulator truth would break :func:`assert_no_truth_access`, which the test
    suite runs over the dataclass definition itself.
    """

    car_id: str
    session_time_s: float
    observation: Observation
    rule_context: RuleContext | None
    compute_budget_ms: float
    disturbance_keys: tuple[str, ...] = ()
    max_observation_age_s: float = 1.0
    expected_model_bundle_hash: str | None = None
    offered_model_bundle_hash: str | None = None

    @property
    def admissible_profiles(self) -> tuple[DeploymentProfile, ...]:
        """Legal profiles right now. Empty when the rules could not be resolved."""
        if self.rule_context is None:
            return ()
        return tuple(self.rule_context.admissible_profiles)

    @property
    def unknown_conditions(self) -> tuple[str, ...]:
        if self.rule_context is None:
            return ("rule_context_unavailable",)
        return tuple(self.rule_context.unknown_conditions)

    @property
    def observation_age_s(self) -> float:
        return self.observation.delivered_at_s - self.observation.observed_at_s


@dataclass(frozen=True, slots=True)
class ControlDecision:
    """One controller's answer, with its provenance and its qualifications."""

    controller: str
    status: PlanningStatus
    action: DriverAction | None
    reasons: tuple[ReasonCode, ...] = ()
    latency_ms: float = 0.0
    provenance: str = "baseline"
    detail: str | None = None

    @property
    def withdrawn(self) -> bool:
        """True when no directive was issued at all."""
        return self.action is None

    @property
    def is_active_directive(self) -> bool:
        """True when the directive tells the driver to spend energy now."""
        return self.action is not None and self.action.profile in ACTIVE_PROFILES

    @property
    def is_confident(self) -> bool:
        """True only when the plan succeeded and nothing qualified it."""
        return self.status is PlanningStatus.OK and not (set(self.reasons) & _DEGRADED_REASONS)

    @property
    def is_confident_active_directive(self) -> bool:
        """The state ``validation/TECHNICAL_SPEC.md`` forbids under an unknown."""
        return self.is_active_directive and self.is_confident


@runtime_checkable
class Controller(Protocol):
    """What a benchmark row must provide.

    A06's MPC and A07's learned system satisfy this by implementing ``decide``;
    nothing here depends on either module, and this package never imports them.
    """

    @property
    def name(self) -> str: ...

    @property
    def uses_actor(self) -> bool: ...

    @property
    def uses_learned_return(self) -> bool: ...

    def decide(self, request: ControlRequest) -> ControlDecision: ...


def build_request(
    *,
    car_id: str,
    session_time_s: float,
    observation: Observation,
    rule_context: RuleContext | None,
    compute_budget_ms: float,
    disturbance_keys: Sequence[str] = (),
    max_observation_age_s: float = 1.0,
    expected_model_bundle_hash: str | None = None,
    offered_model_bundle_hash: str | None = None,
) -> ControlRequest:
    """Single constructor for a decision tick, shared by every controller."""
    return ControlRequest(
        car_id=car_id,
        session_time_s=session_time_s,
        observation=observation,
        rule_context=rule_context,
        compute_budget_ms=compute_budget_ms,
        disturbance_keys=tuple(disturbance_keys),
        max_observation_age_s=max_observation_age_s,
        expected_model_bundle_hash=expected_model_bundle_hash,
        offered_model_bundle_hash=offered_model_bundle_hash,
    )


def assert_no_truth_access() -> None:
    """Fail if :class:`ControlRequest` ever gains a channel into simulator truth.

    Structural rather than behavioural: it inspects the dataclass definition, so
    a future field named ``world``, ``simulator`` or ``truth`` fails the suite
    before anyone can read from it.
    """
    forbidden = {"world", "simulator", "truth", "world_state", "rival_truth", "ledger"}
    names = {f.name for f in fields(ControlRequest)}
    leaked = names & forbidden
    if leaked:
        raise AssertionError(f"ControlRequest exposes simulator truth through {sorted(leaked)}")


def _downgrade_to_admissible(
    wanted: DeploymentProfile, admissible: Sequence[DeploymentProfile]
) -> DeploymentProfile | None:
    """Most aggressive admissible profile no more aggressive than ``wanted``."""
    if not admissible:
        return None
    allowed = set(admissible)
    ranked = AGGRESSION_ORDER[: AGGRESSION_ORDER.index(wanted) + 1]
    for profile in reversed(ranked):
        if profile in allowed:
            return profile
    return None


def _withdraw(
    controller: str,
    status: PlanningStatus,
    reasons: tuple[ReasonCode, ...],
    detail: str,
    latency_ms: float,
) -> ControlDecision:
    return ControlDecision(
        controller=controller,
        status=status,
        action=None,
        reasons=reasons,
        latency_ms=latency_ms,
        provenance="withdrawn",
        detail=detail,
    )


class _LegalBaseline:
    """Shared gating every legal baseline applies before it proposes anything."""

    uses_actor = False
    uses_learned_return = False

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def _gate(self, request: ControlRequest, latency_ms: float) -> ControlDecision | None:
        """Return a withdrawal when the situation is not safely resolvable."""
        observation = request.observation
        if observation.quality in (Quality.MISSING, Quality.INVALID):
            return _withdraw(
                self._name,
                PlanningStatus.INPUT_UNAVAILABLE,
                (ReasonCode.STALE_OBSERVATIONS,),
                f"observation quality is {observation.quality.value}",
                latency_ms,
            )
        if observation.quality is Quality.STALE or (
            request.observation_age_s > request.max_observation_age_s
        ):
            return _withdraw(
                self._name,
                PlanningStatus.INPUT_UNAVAILABLE,
                (ReasonCode.STALE_OBSERVATIONS,),
                (
                    f"observation age {request.observation_age_s:.3f} s exceeds the declared limit "
                    f"{request.max_observation_age_s:.3f} s; both engineer and driver advice are withdrawn"
                ),
                latency_ms,
            )
        if request.unknown_conditions:
            return _withdraw(
                self._name,
                PlanningStatus.RULES_UNKNOWN,
                (ReasonCode.ELIGIBILITY_UNKNOWN,),
                f"unresolved rule conditions {list(request.unknown_conditions)}",
                latency_ms,
            )
        if not request.admissible_profiles:
            return _withdraw(
                self._name,
                PlanningStatus.NO_FEASIBLE_CANDIDATE,
                (ReasonCode.ELIGIBILITY_UNKNOWN,),
                "no admissible deployment profile",
                latency_ms,
            )
        return None

    def _emit(
        self,
        request: ControlRequest,
        wanted: DeploymentProfile,
        *,
        latency_ms: float,
        reasons: tuple[ReasonCode, ...] = (),
        label: str = "",
    ) -> ControlDecision:
        """Downgrade ``wanted`` to something legal and package the decision."""
        extra = list(reasons)
        if not request.observation.has("battery_energy_j") and wanted in ACTIVE_PROFILES:
            wanted = DeploymentProfile.NEUTRAL
            extra.append(ReasonCode.OWN_ENERGY_UNAVAILABLE)
        profile = _downgrade_to_admissible(wanted, request.admissible_profiles)
        if profile is None:
            return _withdraw(
                self._name,
                PlanningStatus.NO_FEASIBLE_CANDIDATE,
                (*extra, ReasonCode.ENERGY_FLOOR),
                f"no admissible profile at or below {wanted.value}",
                latency_ms,
            )
        if profile is not wanted:
            extra.append(ReasonCode.POWER_CEILING_EXCEEDED)
        return ControlDecision(
            controller=self._name,
            status=PlanningStatus.OK,
            action=DriverAction(profile=profile, issued_at_s=request.session_time_s, label=label),
            reasons=tuple(extra),
            latency_ms=latency_ms,
            provenance="baseline",
        )


@dataclass(frozen=True, slots=True)
class ScheduleEntry:
    """One entry of a fixed schedule: apply ``profile`` from ``from_s`` onwards."""

    from_s: float
    profile: DeploymentProfile


class LegalFixedSchedule(_LegalBaseline):
    """A reproducible reference: a deterministic profile schedule, made legal.

    The schedule is a function of elapsed session time alone, so this row is
    reproducible from the manifest without any state. It is still filtered
    through the rule context, so it is a *legal* fixed schedule and not a way to
    make a comparison look good by ignoring the rules.
    """

    def __init__(
        self,
        entries: Sequence[ScheduleEntry] | None = None,
        *,
        name: str = "legal_fixed_schedule",
    ) -> None:
        super().__init__(name)
        chosen = tuple(entries or (ScheduleEntry(0.0, DeploymentProfile.NEUTRAL),))
        if chosen[0].from_s > 0.0:
            raise ValueError("a fixed schedule must define a profile from time zero")
        times = [entry.from_s for entry in chosen]
        if times != sorted(times):
            raise ValueError("schedule entries must be ordered by time")
        self._entries = chosen

    @property
    def entries(self) -> tuple[ScheduleEntry, ...]:
        return self._entries

    def scheduled_profile(self, session_time_s: float) -> DeploymentProfile:
        chosen = self._entries[0].profile
        for entry in self._entries:
            if session_time_s + 1e-12 >= entry.from_s:
                chosen = entry.profile
        return chosen

    def decide(self, request: ControlRequest) -> ControlDecision:
        started = time.perf_counter()

        def latency() -> float:
            return (time.perf_counter() - started) * 1000.0

        gated = self._gate(request, latency())
        if gated is not None:
            return gated
        wanted = self.scheduled_profile(request.session_time_s)
        return self._emit(request, wanted, latency_ms=latency(), label="fixed_schedule")


class LegalGreedyAttacker(_LegalBaseline):
    """Spends early: the cost of a short-term strategy, made legal.

    While the battery is above ``reserve_energy_j`` it always asks for the most
    aggressive admissible profile. Below the reserve it asks to harvest. This is
    a deliberately myopic reference, not a proposal.
    """

    def __init__(
        self,
        *,
        reserve_energy_j: float = 4.0e5,
        name: str = "legal_greedy_attacker",
    ) -> None:
        super().__init__(name)
        if reserve_energy_j < 0.0:
            raise ValueError("the reserve must be non-negative")
        self.reserve_energy_j = reserve_energy_j

    def decide(self, request: ControlRequest) -> ControlDecision:
        started = time.perf_counter()

        def latency() -> float:
            return (time.perf_counter() - started) * 1000.0

        gated = self._gate(request, latency())
        if gated is not None:
            return gated
        observation = request.observation
        if not observation.has("battery_energy_j"):
            return self._emit(
                request,
                DeploymentProfile.NEUTRAL,
                latency_ms=latency(),
                reasons=(ReasonCode.OWN_ENERGY_UNAVAILABLE,),
                label="greedy_no_energy_channel",
            )
        energy_j = observation.get("battery_energy_j")
        if energy_j <= self.reserve_energy_j:
            return self._emit(
                request,
                DeploymentProfile.HARVEST,
                latency_ms=latency(),
                reasons=(ReasonCode.ENERGY_FLOOR,),
                label="greedy_recover",
            )
        return self._emit(request, DeploymentProfile.OVERTAKE, latency_ms=latency(), label="greedy_attack")


class UnavailableController:
    """A comparison-matrix row whose implementation is not merged.

    ``AGENTS.md``: "A stub returns an explicit unavailable result." This one
    never proposes an action and never contributes a number to a comparison; the
    harness records its runs as missing and the report renders the row as
    unmeasured.
    """

    def __init__(
        self,
        name: str,
        *,
        owner: str,
        uses_actor: bool = False,
        uses_learned_return: bool = False,
        detail: str = "",
    ) -> None:
        self._name = name
        self.owner = owner
        self._uses_actor = uses_actor
        self._uses_learned_return = uses_learned_return
        self.detail = detail or f"{name} is owned by {owner} and is not merged in this package"

    @property
    def name(self) -> str:
        return self._name

    @property
    def uses_actor(self) -> bool:
        return self._uses_actor

    @property
    def uses_learned_return(self) -> bool:
        return self._uses_learned_return

    def decide(self, request: ControlRequest) -> ControlDecision:
        del request
        return ControlDecision(
            controller=self._name,
            status=PlanningStatus.SOLVER_UNAVAILABLE,
            action=None,
            reasons=(ReasonCode.LEARNED_MODEL_DISABLED,)
            if self._uses_actor or self._uses_learned_return
            else (),
            provenance="unimplemented",
            detail=self.detail,
        )


class HashCheckedController:
    """Disables a model-backed controller when its bundle hash does not match.

    ``SERVING_AND_EVALUATION.md``: "Load only local approved artifacts and
    validate every hash before initialization"; a missing or incorrect feature
    hash disables the model with a *visible baseline identity*. On a mismatch
    this delegates to ``fallback`` and stamps the decision with
    ``BASELINE_FALLBACK``, so the provenance names what actually answered.
    """

    def __init__(self, primary: Controller, fallback: Controller) -> None:
        self.primary = primary
        self.fallback = fallback

    @property
    def name(self) -> str:
        return f"{self.primary.name}+hash_checked"

    @property
    def uses_actor(self) -> bool:
        return self.primary.uses_actor

    @property
    def uses_learned_return(self) -> bool:
        return self.primary.uses_learned_return

    def decide(self, request: ControlRequest) -> ControlDecision:
        expected = request.expected_model_bundle_hash
        offered = request.offered_model_bundle_hash
        if expected is not None and offered != expected:
            decision = self.fallback.decide(request)
            return ControlDecision(
                controller=self.name,
                status=decision.status,
                action=decision.action,
                reasons=(*decision.reasons, ReasonCode.LEARNED_MODEL_DISABLED, ReasonCode.BASELINE_FALLBACK),
                latency_ms=decision.latency_ms,
                provenance=f"baseline_fallback:{self.fallback.name}",
                detail=f"model bundle hash mismatch (expected {expected}, offered {offered})",
            )
        return self.primary.decide(request)


@dataclass(frozen=True, slots=True)
class MatrixRow:
    """One row of the required comparison matrix, with its build status."""

    controller_name: str
    uses_actor: bool
    uses_learned_return: bool
    purpose: str
    owner: str
    measurable_today: bool
    unmeasured_reason: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


COMPARISON_MATRIX: tuple[MatrixRow, ...] = (
    MatrixRow(
        controller_name="legal_fixed_schedule",
        uses_actor=False,
        uses_learned_return=False,
        purpose="Reproducible simple reference",
        owner="A13",
        measurable_today=True,
    ),
    MatrixRow(
        controller_name="legal_greedy_attacker",
        uses_actor=False,
        uses_learned_return=False,
        purpose="Cost of short-term strategy",
        owner="A13",
        measurable_today=True,
    ),
    MatrixRow(
        controller_name="mpc_only",
        uses_actor=False,
        uses_learned_return=False,
        purpose="Core engineering baseline",
        owner="A06",
        measurable_today=False,
        unmeasured_reason="the MPC planner is not merged; no candidate exists to evaluate",
    ),
    MatrixRow(
        controller_name="mpc_plus_actor",
        uses_actor=True,
        uses_learned_return=False,
        purpose="Proposal contribution",
        owner="A06+A07",
        measurable_today=False,
        unmeasured_reason="requires both a merged MPC planner and a trained actor; neither exists",
    ),
    MatrixRow(
        controller_name="mpc_plus_value",
        uses_actor=False,
        uses_learned_return=True,
        purpose="Continuation contribution",
        owner="A06+A07",
        measurable_today=False,
        unmeasured_reason="requires a merged MPC planner and a trained continuation ensemble",
    ),
    MatrixRow(
        controller_name="full_system",
        uses_actor=True,
        uses_learned_return=True,
        purpose="Combined effect",
        owner="A06+A07",
        measurable_today=False,
        unmeasured_reason="requires the merged planner and a promoted model bundle",
    ),
)
"""The matrix from ``SERVING_AND_EVALUATION.md``, annotated with what exists."""


def unavailable_matrix_controllers() -> tuple[UnavailableController, ...]:
    """Explicit unavailable stubs for every matrix row that is not merged."""
    return tuple(
        UnavailableController(
            row.controller_name,
            owner=row.owner,
            uses_actor=row.uses_actor,
            uses_learned_return=row.uses_learned_return,
            detail=row.unmeasured_reason or "",
        )
        for row in COMPARISON_MATRIX
        if not row.measurable_today
    )


__all__ += ["COMPARISON_MATRIX", "MatrixRow", "ScheduleEntry", "unavailable_matrix_controllers"]
