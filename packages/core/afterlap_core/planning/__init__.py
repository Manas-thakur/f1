"""AFTERLAP predictive energy and battle planning.

Public entry point::

    plan(estimate, rule_context, model_bundle, deadline) -> PlanningResult

The planner turns a controller belief and a resolved rule context into a small
set of legal, independently rechecked candidate plans, and names the one it
recommends. It never actuates anything, never writes an operator lifecycle
event, and never reads simulator truth: ``StateEstimate`` is its only view of
the world and ``afterlap_core.simulation``'s public branching API is its only
way to re-simulate.

Module map
----------

``config``       planner tuning document (``configs/planning/planner-v1.yaml``)
``objective``    reader for the frozen ``configs/objectives/objective-v1.yaml``
``scenarios``    weighted rival scenarios and the sampling protocol
``segments``     driver-selectable profile segments and the corridor frame
``surrogate``    the smooth loss the solver differentiates
``enumerator``   bounded tactical enumeration with pruning before optimisation
``optimiser``    the CasADi/IPOPT continuous segment-energy schedule
``rollout``      re-simulation against reacting rivals, and outcome probabilities
``scoring``      objective decomposition, learned reranking and hysteresis
``planner``      the runtime algorithm and the published recommendation

Honesty constraints this module is built around
-----------------------------------------------

* The independent checker's verdict is final; ``unknown`` is not acceptance.
* A late answer is not an answer: the deadline withdraws advice rather than
  publishing a stale plan.
* Learned continuation reranks finalists and never double-counts the analytic
  terminal term. With no bundle the result is exactly the baseline.
* A weighted objective is never relabelled as seconds; position, time, energy
  and probability are separate published fields.
* Every shipped configuration is synthetic. Nothing here establishes regulatory
  compliance or measured performance.
"""

from __future__ import annotations

from .config import PlannerConfig, load_planner_config
from .enumerator import (
    TEMPLATES,
    EnumeratedCandidate,
    EnumerationResult,
    IntentionTemplate,
    SuppressedCandidate,
    enumerate_intentions,
)
from .objective import ObjectiveManifest, load_objective
from .optimiser import (
    AllocationSolution,
    SolverDeadlineExpired,
    SolverUnavailable,
    solve_allocation,
    solver_identity,
)
from .planner import (
    DEFAULT_DEADLINE_S,
    BudgetProposal,
    DeadlineClock,
    active_plan_from,
    build_recommendation,
    plan,
)
from .rollout import (
    FORECASTER_VERSION,
    PlanningWorld,
    ProbabilityCalibration,
    RolloutEvidence,
    SegmentController,
    rollout_candidate,
)
from .scenarios import (
    PlanScenario,
    RivalScenarioView,
    ScenarioEnsembleView,
    ScenarioSample,
    scenarios_from_estimate,
    scenarios_from_views,
)
from .scoring import (
    ActivePlan,
    ContinuationModel,
    InvalidationCause,
    LearnedOutcome,
    ScoredCandidate,
    Selection,
    apply_learned_reranking,
    build_objective_terms,
    select_instruction,
    switch_count_for,
)
from .segments import (
    FrameSegment,
    PlanFrame,
    build_frame,
    checker_state_for,
    held_speed_profile,
    to_profile_segments,
)
from .surrogate import SurrogateWeights, build_weights, cvar, scenario_losses

__all__ = [
    "DEFAULT_DEADLINE_S",
    "FORECASTER_VERSION",
    "TEMPLATES",
    "ActivePlan",
    "AllocationSolution",
    "BudgetProposal",
    "ContinuationModel",
    "DeadlineClock",
    "EnumeratedCandidate",
    "EnumerationResult",
    "FrameSegment",
    "IntentionTemplate",
    "InvalidationCause",
    "LearnedOutcome",
    "ObjectiveManifest",
    "PlanFrame",
    "PlanScenario",
    "PlannerConfig",
    "PlanningWorld",
    "ProbabilityCalibration",
    "RivalScenarioView",
    "RolloutEvidence",
    "ScenarioEnsembleView",
    "ScenarioSample",
    "ScoredCandidate",
    "SegmentController",
    "Selection",
    "SolverDeadlineExpired",
    "SolverUnavailable",
    "SuppressedCandidate",
    "SurrogateWeights",
    "active_plan_from",
    "apply_learned_reranking",
    "build_frame",
    "build_objective_terms",
    "build_recommendation",
    "build_weights",
    "checker_state_for",
    "cvar",
    "enumerate_intentions",
    "held_speed_profile",
    "load_objective",
    "load_planner_config",
    "plan",
    "rollout_candidate",
    "scenario_losses",
    "scenarios_from_estimate",
    "scenarios_from_views",
    "select_instruction",
    "solve_allocation",
    "solver_identity",
    "switch_count_for",
    "to_profile_segments",
]
