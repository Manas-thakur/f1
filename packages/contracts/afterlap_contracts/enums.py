"""Closed enumerations shared by every AFTERLAP boundary.

Contract revision 1. Adding a member is a minor version change; removing or
re-meaning a member is a major version change (see DOMAIN_MODEL.md).
"""

from __future__ import annotations

from enum import StrEnum


class SessionMode(StrEnum):
    """How a session obtains its observations."""

    SIMULATION = "simulation"
    REPLAY = "replay"
    LIVE_TEAM = "live_team"


class Provenance(StrEnum):
    """Where a numeric value came from. Never omit this next to a number."""

    MEASURED = "measured"
    ESTIMATED = "estimated"
    CONFIGURED = "configured"
    SIMULATED = "simulated"


class Quality(StrEnum):
    """Fitness of an observation or derived value for operational use."""

    VALID = "valid"
    DEGRADED = "degraded"
    STALE = "stale"
    MISSING = "missing"
    INVALID = "invalid"


class RecommendationStatus(StrEnum):
    """Lifecycle of a published recommendation.

    ``SELECTED`` records a human decision. It is not execution: only an
    ``ExecutionEvent`` moves a recommendation to ``EXECUTING``.
    """

    PROPOSED = "proposed"
    SELECTED = "selected"
    COMMUNICATED = "communicated"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


TERMINAL_RECOMMENDATION_STATUSES: frozenset[RecommendationStatus] = frozenset(
    {
        RecommendationStatus.COMPLETED,
        RecommendationStatus.REJECTED,
        RecommendationStatus.EXPIRED,
        RecommendationStatus.INVALIDATED,
    }
)


class ActionCode(StrEnum):
    """Machine action vocabulary. Display wording is a separate template map."""

    MAINTAIN = "maintain"
    PREPARE_ATTACK = "prepare_attack"
    ATTACK = "attack"
    DEFEND = "defend"
    RECOVER = "recover"
    WITHDRAW_ADVICE = "withdraw_advice"


class OperatorAction(StrEnum):
    """Actions an authorised operator can take on a recommendation."""

    SELECT = "select"
    REJECT = "reject"
    MARK_COMMUNICATED = "mark_communicated"


class SessionCommandKind(StrEnum):
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    STEP = "step"


class CheckStatus(StrEnum):
    """Three-valued constraint result. ``UNKNOWN`` is a first-class outcome."""

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class CoverageStatus(StrEnum):
    """How well a regulatory concern is covered by the loaded rule pack."""

    IMPLEMENTED_AND_TESTED = "implemented_and_tested"
    REVIEW_REQUIRED = "review_required"
    NOT_APPLICABLE = "not_applicable"
    UNSUPPORTED = "unsupported"


class EligibilityState(StrEnum):
    """Overtake-permission state machine."""

    UNKNOWN = "unknown"
    INELIGIBLE = "ineligible"
    ELIGIBLE_DETECTED = "eligible_detected"
    ACTIVE = "active"


class FlagState(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    DOUBLE_YELLOW = "double_yellow"
    SAFETY_CAR = "safety_car"
    VIRTUAL_SAFETY_CAR = "virtual_safety_car"
    RED = "red"
    CHEQUERED = "chequered"
    UNKNOWN = "unknown"


class RivalIntention(StrEnum):
    """Reactive opponent behaviour modes shared by simulator and belief filter."""

    CONSERVE = "conserve"
    NORMAL = "normal"
    ATTACK = "attack"
    DEFEND = "defend"


class DeploymentProfile(StrEnum):
    """Driver-selectable electrical profiles.

    These are coarse, human-executable modes, not a millisecond power trace.
    """

    HARVEST = "harvest"
    CONSERVE = "conserve"
    NEUTRAL = "neutral"
    PUSH = "push"
    OVERTAKE = "overtake"


class PlanningStatus(StrEnum):
    """Outcome of one planner invocation."""

    OK = "ok"
    NO_FEASIBLE_CANDIDATE = "no_feasible_candidate"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    INPUT_UNAVAILABLE = "input_unavailable"
    RULES_UNKNOWN = "rules_unknown"
    SOLVER_UNAVAILABLE = "solver_unavailable"


class ExecutionMatch(StrEnum):
    """Relation between an observed driver action and the advice in force."""

    MATCHED = "matched"
    DIFFERENT_PROFILE = "different_profile"
    LATE = "late"
    UNSOLICITED = "unsolicited"


class ApprovalStatus(StrEnum):
    """Promotion state of a model bundle. Never default to approved."""

    UNEVALUATED = "unevaluated"
    CANDIDATE = "candidate"
    REJECTED = "rejected"
    APPROVED = "approved"


class TrackReadiness(StrEnum):
    """Readiness ladder of a physical circuit (TRACK_REGISTRY_2026.md).

    Each rung is derived from evidence by the independent validator; a rung is
    never set by hand and ``rejected`` sits below every other rung.

    This deliberately restates ``afterlap_core.tracks.package.ReadinessStatus``
    rather than importing it: contracts is the innermost layer and depends on
    no domain package. ``tests/contracts/test_readiness_enum.py`` fails if the
    two ladders ever diverge, so the duplication cannot drift silently.
    """

    DISCOVERED = "discovered"
    GEOMETRY_VALIDATED = "geometry_validated"
    EVENT_RULES_VALIDATED = "event_rules_validated"
    CONDITION_CALIBRATED = "condition_calibrated"
    SIMULATION_ELIGIBLE = "simulation_eligible"
    REJECTED = "rejected"


class CalibrationStatus(StrEnum):
    """Whether a probability has been calibrated against held-out outcomes."""

    UNCALIBRATED = "uncalibrated"
    CALIBRATED = "calibrated"
    UNAVAILABLE = "unavailable"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StreamEventType(StrEnum):
    """WebSocket message types (API.md)."""

    SNAPSHOT = "snapshot"
    TELEMETRY_VIEW = "telemetry_view"
    ESTIMATE_UPDATED = "estimate_updated"
    RECOMMENDATION_UPDATED = "recommendation_updated"
    EXECUTION_OBSERVED = "execution_observed"
    RULE_CONTEXT_CHANGED = "rule_context_changed"
    QUALITY_CHANGED = "quality_changed"
    EXPERIMENT_PROGRESS = "experiment_progress"
    HEARTBEAT = "heartbeat"
    RESYNC_REQUIRED = "resync_required"


class CapabilityState(StrEnum):
    """Runtime capability availability, used for honest degradation."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ReasonCode(StrEnum):
    """Template reason codes attached to recommendations and rejections.

    These label computed differences; they are not free-form generated text.
    """

    RESERVE_FOR_COUNTERATTACK = "reserve_for_counterattack"
    INSUFFICIENT_EXECUTION_LEAD = "insufficient_execution_lead"
    ELIGIBILITY_UNKNOWN = "eligibility_unknown"
    ENERGY_FLOOR = "energy_floor"
    SMALL_EXPECTED_IMPROVEMENT = "small_expected_improvement"
    THERMAL_DERATE = "thermal_derate"
    RECHARGE_ALLOWANCE_EXHAUSTED = "recharge_allowance_exhausted"
    POWER_CEILING_EXCEEDED = "power_ceiling_exceeded"
    RIVAL_ENERGY_UNKNOWN = "rival_energy_unknown"
    GAP_TOO_LARGE = "gap_too_large"
    EXPECTED_PASS_RETAINED = "expected_pass_retained"
    LEARNED_MODEL_OUT_OF_SUPPORT = "learned_model_out_of_support"
    LEARNED_MODEL_DISABLED = "learned_model_disabled"
    BASELINE_FALLBACK = "baseline_fallback"
    OWN_ENERGY_UNAVAILABLE = "own_energy_unavailable"
    STALE_OBSERVATIONS = "stale_observations"
    SOLVER_TIMEOUT = "solver_timeout"
    SWITCH_COST_DOMINATES = "switch_cost_dominates"


class FailureCategory(StrEnum):
    """Failure taxonomy for evaluation reports (SERVING_AND_EVALUATION.md)."""

    ENERGY_DEPLETION = "energy_depletion"
    MISSED_RESPONSE = "missed_response"
    POOR_OPPONENT_BELIEF = "poor_opponent_belief"
    UNKNOWN_ELIGIBILITY = "unknown_eligibility"
    INFEASIBLE_PROJECTION = "infeasible_projection"
    PLANNER_TIMEOUT = "planner_timeout"
    MODEL_SUPPORT_REJECTION = "model_support_rejection"
    LOST_COMMUNICATION = "lost_communication"
    SIMULATOR_DEFECT = "simulator_defect"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"


__all__ = [
    "TERMINAL_RECOMMENDATION_STATUSES",
    "ActionCode",
    "ApprovalStatus",
    "CalibrationStatus",
    "CapabilityState",
    "CheckStatus",
    "CoverageStatus",
    "DeploymentProfile",
    "EligibilityState",
    "ExecutionMatch",
    "FailureCategory",
    "FlagState",
    "JobStatus",
    "OperatorAction",
    "PlanningStatus",
    "Provenance",
    "Quality",
    "ReasonCode",
    "RecommendationStatus",
    "RivalIntention",
    "SessionCommandKind",
    "SessionMode",
    "StreamEventType",
    "TrackReadiness",
]
