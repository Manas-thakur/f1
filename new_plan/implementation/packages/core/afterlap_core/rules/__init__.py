"""Rules engine: rule packs, overtake eligibility and the independent checker.

Deterministic pure functions and one explicit state machine. No LLM, no
network, no randomness (``04_rules/TECHNICAL_SPEC.md``).

Public entry points:

* :func:`~afterlap_core.rules.packs.load_rule_pack` — load and validate a pack
  from ``configs/rules/``;
* :func:`~afterlap_core.rules.context.resolve_context` — resolve the applicable
  limits and admissible profiles at one progress point and session time;
* :func:`~afterlap_core.rules.context.admissible_profiles` — the profiles that
  are legal right now;
* :func:`~afterlap_core.rules.checker.check_plan` — the independent checker;
* :class:`~afterlap_core.rules.eligibility.EligibilityMachine` — the overtake
  permission state machine.

Nothing here asserts FIA certification. Coverage is declared per concern by the
loaded pack, and every pack shipped in this repository is synthetic.
"""

from __future__ import annotations

from .checker import (
    CHECK_ARTICLES,
    CHECKER_VERSION,
    CheckerConfig,
    PlanTrace,
    TracePoint,
    build_trace,
    check_plan,
)
from .context import (
    RESTRICTIVE_FLAGS,
    THERMAL_TEMPERATURE_UNKNOWN,
    ResolvedRaceControl,
    admissible_profiles,
    fold_race_events,
    resolve_context,
    resolve_pack_context,
    select_curve,
)
from .eligibility import EligibilityMachine, EligibilityTransition, LineCrossing
from .packs import (
    FORBIDDEN_CLAIM_PHRASES,
    CoverageSpec,
    CurveSpec,
    DetectionLineSpec,
    PackValidationError,
    RaceControlSpec,
    RulePack,
    RulePackDocument,
    RuleStatement,
    ThermalDerateSpec,
    UnknownConditionSpec,
    compose_manifest,
    list_rule_packs,
    load_rule_pack,
    load_rule_pack_file,
    references_for_article,
)
from .state import (
    CarState,
    CheckerState,
    RaceEvent,
    RaceEventKind,
    SpeedProfile,
    SpeedSample,
    sorted_race_events,
)

__all__ = [
    "CHECKER_VERSION",
    "CHECK_ARTICLES",
    "FORBIDDEN_CLAIM_PHRASES",
    "RESTRICTIVE_FLAGS",
    "THERMAL_TEMPERATURE_UNKNOWN",
    "CarState",
    "CheckerConfig",
    "CheckerState",
    "CoverageSpec",
    "CurveSpec",
    "DetectionLineSpec",
    "EligibilityMachine",
    "EligibilityTransition",
    "LineCrossing",
    "PackValidationError",
    "PlanTrace",
    "RaceControlSpec",
    "RaceEvent",
    "RaceEventKind",
    "ResolvedRaceControl",
    "RulePack",
    "RulePackDocument",
    "RuleStatement",
    "SpeedProfile",
    "SpeedSample",
    "ThermalDerateSpec",
    "TracePoint",
    "UnknownConditionSpec",
    "admissible_profiles",
    "build_trace",
    "check_plan",
    "compose_manifest",
    "fold_race_events",
    "list_rule_packs",
    "load_rule_pack",
    "load_rule_pack_file",
    "references_for_article",
    "resolve_context",
    "resolve_pack_context",
    "select_curve",
    "sorted_race_events",
]
