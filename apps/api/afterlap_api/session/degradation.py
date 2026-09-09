"""Every row of the ARCHITECTURE.md degradation table, as a real code path.

| Condition | Documented behaviour |
|---|---|
| Missing required own-car energy | analysis-only mode, no precise energy directive |
| Unknown opponent energy | wider scenarios, not a made-up point value |
| Missing event rules | unsupported eligibility/curve state |
| Solver timeout | revalidated prior plan or withdrawn tactical advice |
| Database failure | bounded local spool and visible persistence warning |
| Spool full | halt new operational recommendations to preserve auditability |
| Training/model mismatch | disable learned contribution, identify the validated baseline |

Each row is produced by one function here and carries an explicit *result*, not
just a warning string: ``suppresses_energy_directive``, ``halts_recommendations``
and ``withdraw_advice`` are what the runtime actually branches on. A finding that
changed nothing would be decoration.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum

from afterlap_contracts import (
    ApprovalStatus,
    CapabilityState,
    CheckStatus,
    ConstraintResult,
    ModelManifest,
    ReasonCode,
    RuleContext,
    StateEstimate,
)

RIVAL_ENERGY_QUANTILE_NOTE = (
    "Rival stored energy is a model quantile from A05's particle filter, never a measurement and "
    "never a calibrated bound: its nominal 0.90 label was measured at 0.7885 empirical coverage on "
    "156 synthetic samples. Plan across the interval; do not quote a point value."
)
"""A05 handoff §5/§7. Carried verbatim so an operator surface cannot round it off."""

ANALYSIS_ONLY_NOTE = (
    "No measured battery-energy channel for the advised car. The session is analysis-only: "
    "state and rule context are still published, but no precise energy directive is issued."
)


class DegradationRow(StrEnum):
    """One row of the runtime degradation table."""

    MISSING_OWN_ENERGY = "missing_own_energy"
    UNKNOWN_OPPONENT_ENERGY = "unknown_opponent_energy"
    MISSING_EVENT_RULES = "missing_event_rules"
    SOLVER_TIMEOUT = "solver_timeout"
    DATABASE_FAILURE = "database_failure"
    SPOOL_FULL = "spool_full"
    MODEL_MISMATCH = "model_mismatch"


@dataclass(frozen=True, slots=True)
class DegradationFinding:
    """A named degraded condition and the behaviour it forces."""

    row: DegradationRow
    state: CapabilityState
    effect: str
    detail: str
    suppresses_energy_directive: bool = False
    halts_recommendations: bool = False
    withdraw_advice: bool = False
    reason_codes: tuple[ReasonCode, ...] = ()
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "row": self.row.value,
            "state": self.state.value,
            "effect": self.effect,
            "detail": self.detail,
            "suppresses_energy_directive": self.suppresses_energy_directive,
            "halts_recommendations": self.halts_recommendations,
            "withdraw_advice": self.withdraw_advice,
            "reason_codes": [code.value for code in self.reason_codes],
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class DegradationReport:
    """Every finding at one tick, plus the aggregate the runtime branches on."""

    findings: tuple[DegradationFinding, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.findings)

    def __iter__(self) -> Iterator[DegradationFinding]:
        return iter(self.findings)

    def has(self, row: DegradationRow) -> bool:
        return any(finding.row is row for finding in self.findings)

    def find(self, row: DegradationRow) -> DegradationFinding | None:
        return next((finding for finding in self.findings if finding.row is row), None)

    @property
    def analysis_only(self) -> bool:
        return any(finding.suppresses_energy_directive for finding in self.findings)

    @property
    def halted(self) -> bool:
        return any(finding.halts_recommendations for finding in self.findings)

    @property
    def withdraw_advice(self) -> bool:
        return any(finding.withdraw_advice for finding in self.findings)

    @property
    def reason_codes(self) -> tuple[ReasonCode, ...]:
        codes: list[ReasonCode] = []
        for finding in self.findings:
            codes.extend(finding.reason_codes)
        return tuple(dict.fromkeys(codes))

    @property
    def notes(self) -> tuple[str, ...]:
        notes: list[str] = []
        for finding in self.findings:
            notes.extend(finding.notes)
        return tuple(dict.fromkeys(notes))

    def merged_with(self, *extra: DegradationFinding | None) -> DegradationReport:
        return DegradationReport(findings=self.findings + tuple(f for f in extra if f is not None))

    def as_list(self) -> list[dict[str, object]]:
        return [finding.as_dict() for finding in self.findings]


def own_energy_finding(estimate: StateEstimate) -> DegradationFinding | None:
    """Missing required own-car energy -> analysis-only, no precise energy directive."""
    quality = estimate.quality
    own = estimate.own_car
    if quality.own_energy_capability and own.has_energy_capability:
        return None
    interval = own.battery_energy_interval
    bound = (
        f"reachable set {interval.lower} .. {interval.upper} {interval.unit} ({interval.kind})"
        if interval is not None
        else "no reachable set is available either"
    )
    return DegradationFinding(
        row=DegradationRow.MISSING_OWN_ENERGY,
        state=CapabilityState.DEGRADED,
        effect="analysis_only_no_precise_energy_directive",
        detail=(
            f"own battery energy is {own.battery_energy_j.quality.value} "
            f"(capability={quality.own_energy_capability}); {bound}"
        ),
        suppresses_energy_directive=True,
        withdraw_advice=True,
        reason_codes=(ReasonCode.OWN_ENERGY_UNAVAILABLE,),
        notes=(ANALYSIS_ONLY_NOTE,),
    )


def conservative_energy_floor_j(estimate: StateEstimate, *, manifest_floor_j: float) -> float:
    """The energy the car is *guaranteed* to have, for resolving a rule context.

    Used only in analysis-only mode, and only to resolve limits for display. The
    lower bound of the reachable set is the conservative choice: it can make a
    profile inadmissible, never admissible. It is never published as a value and
    never sizes a budget — the runtime withdraws the energy directive instead.
    """
    interval = estimate.own_car.battery_energy_interval
    if interval is not None and interval.lower is not None:
        return max(manifest_floor_j, float(interval.lower))
    return manifest_floor_j


def rival_energy_finding(estimate: StateEstimate) -> DegradationFinding | None:
    """Unknown opponent energy -> wider scenarios, never a made-up point value."""
    if not estimate.rival_beliefs:
        return None
    unmeasured: list[str] = []
    widths: list[float] = []
    for rival in estimate.rival_beliefs:
        interval = rival.energy_interval_j
        if interval is None:
            unmeasured.append(f"{rival.slot}: no energy belief at all")
            continue
        if interval.kind != "quantile":
            unmeasured.append(f"{rival.slot}: interval kind {interval.kind!r} is not a model quantile")
            continue
        width = interval.width
        if width is not None:
            widths.append(width)
        unmeasured.append(f"{rival.slot}: {interval.kind} interval, nominal coverage {interval.coverage}")
    widest = max(widths) if widths else None
    return DegradationFinding(
        row=DegradationRow.UNKNOWN_OPPONENT_ENERGY,
        state=CapabilityState.DEGRADED,
        effect="wider_scenarios_never_a_point_value",
        detail=(
            "rival stored energy is not observable without an authorised feed; "
            + "; ".join(unmeasured)
            + (f"; widest interval {widest:.0f} J" if widest is not None else "")
        ),
        reason_codes=(ReasonCode.RIVAL_ENERGY_UNKNOWN,),
        notes=(RIVAL_ENERGY_QUANTILE_NOTE,),
    )


def rules_finding(context: RuleContext) -> DegradationFinding | None:
    """Missing event rules -> unsupported eligibility/curve state."""
    if not context.unknown_conditions and context.admissible_profiles:
        return None
    if context.unknown_conditions:
        detail = (
            "unresolved applicable conditions: "
            + ", ".join(context.unknown_conditions)
            + f"; eligibility={context.eligibility.value}, curve={context.active_curve_id}"
        )
    else:
        detail = (
            f"the rule context admits no profile at progress {context.progress_m:.1f} m "
            f"(eligibility={context.eligibility.value}, flags="
            f"{[f.value for f in context.current_flags]})"
        )
    return DegradationFinding(
        row=DegradationRow.MISSING_EVENT_RULES,
        state=CapabilityState.UNAVAILABLE,
        effect="unsupported_eligibility_and_curve_state",
        detail=detail,
        withdraw_advice=True,
        reason_codes=(ReasonCode.ELIGIBILITY_UNKNOWN,),
    )


@dataclass(frozen=True, slots=True)
class TimeoutOutcome:
    """What a solver timeout resolved to. Exactly one of the two is true."""

    revalidated_prior_plan: bool
    withdrawn: bool
    finding: DegradationFinding
    constraint_result: ConstraintResult | None = None
    prior_plan_id: str | None = None


def solver_timeout_outcome(
    *,
    elapsed_ms: float,
    deadline_ms: float,
    prior_plan_id: str | None,
    revalidation: ConstraintResult | None,
) -> TimeoutOutcome:
    """Resolve a solver timeout into a revalidated prior plan or withdrawn advice.

    ``revalidation`` is the *independent* checker's verdict on the prior plan
    against the current context. Only a ``PASS`` may be reissued: a prior plan
    that no longer checks out is withdrawn, never carried forward on the grounds
    that it was legal a second ago.
    """
    revalidated = (
        prior_plan_id is not None and revalidation is not None and revalidation.status is CheckStatus.PASS
    )
    if revalidated:
        detail = (
            f"solver exceeded its {deadline_ms:.1f} ms deadline after {elapsed_ms:.1f} ms; "
            f"prior plan {prior_plan_id} was re-checked against the current context and passed"
        )
    elif prior_plan_id is None:
        detail = (
            f"solver exceeded its {deadline_ms:.1f} ms deadline after {elapsed_ms:.1f} ms; "
            "there is no prior plan to revalidate, so tactical advice is withdrawn"
        )
    else:
        status = "no revalidation was performed" if revalidation is None else revalidation.status.value
        detail = (
            f"solver exceeded its {deadline_ms:.1f} ms deadline after {elapsed_ms:.1f} ms; "
            f"prior plan {prior_plan_id} re-checked as {status}, so tactical advice is withdrawn"
        )
    return TimeoutOutcome(
        revalidated_prior_plan=revalidated,
        withdrawn=not revalidated,
        prior_plan_id=prior_plan_id,
        constraint_result=revalidation,
        finding=DegradationFinding(
            row=DegradationRow.SOLVER_TIMEOUT,
            state=CapabilityState.DEGRADED,
            effect=("revalidated_prior_plan" if revalidated else "withdrawn_tactical_advice"),
            detail=detail,
            withdraw_advice=not revalidated,
            reason_codes=(ReasonCode.SOLVER_TIMEOUT,),
        ),
    )


@dataclass(frozen=True, slots=True)
class PersistenceStatus:
    """Measured health of the lifecycle store for one session."""

    state: CapabilityState = CapabilityState.AVAILABLE
    spooled: int = 0
    capacity: int = 0
    last_error: str | None = None
    exhausted: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def degraded(self) -> bool:
        return self.state is not CapabilityState.AVAILABLE


def persistence_findings(status: PersistenceStatus) -> tuple[DegradationFinding, ...]:
    """Database failure -> bounded spool + visible warning; spool full -> halt."""
    findings: list[DegradationFinding] = []
    if status.spooled or status.last_error is not None:
        findings.append(
            DegradationFinding(
                row=DegradationRow.DATABASE_FAILURE,
                state=CapabilityState.DEGRADED,
                effect="bounded_local_spool_and_visible_persistence_warning",
                detail=(
                    f"lifecycle writes are being spooled ({status.spooled}/{status.capacity}); "
                    f"last error: {status.last_error or 'none recorded'}"
                ),
                notes=(
                    (
                        "Persistence is degraded: decisions are held in a bounded local spool and are "
                        "not yet durable in the session store."
                    ),
                ),
            )
        )
    if status.exhausted:
        findings.append(
            DegradationFinding(
                row=DegradationRow.SPOOL_FULL,
                state=CapabilityState.UNAVAILABLE,
                effect="halt_new_operational_recommendations",
                detail=(
                    f"the persistence spool is full ({status.spooled}/{status.capacity}); "
                    "new recommendations are halted so no advice is issued that cannot be audited"
                ),
                halts_recommendations=True,
                withdraw_advice=True,
                notes=(
                    (
                        "New recommendations are halted because the audit trail cannot be persisted. "
                        "Existing advice is unchanged; recover the store, then drain the spool."
                    ),
                ),
            )
        )
    return tuple(findings)


@dataclass(frozen=True, slots=True)
class ModelDecision:
    """Whether the learned contribution is enabled, and which baseline is in force."""

    enabled: bool
    baseline_identity: str
    detail: str
    mismatches: tuple[str, ...] = ()
    finding: DegradationFinding | None = None


def check_model_compatibility(
    *,
    requested_model_hash: str | None,
    bundle: ModelManifest | None,
    expected_feature_hash: str | None,
    expected_rule_family: str | None,
    expected_reward_revision: str | None,
    baseline_identity: str,
    scenario_family: str | None = None,
    expected_ruleset_hash: str | None = None,
    expected_track_id: str | None = None,
    expected_track_package_hash: str | None = None,
    expected_conditions_id: str | None = None,
) -> ModelDecision:
    """Training/model mismatch -> disable learned scoring, name the baseline.

    A missing bundle is not a mismatch; it is simply the baseline path, and the
    result says so without raising a degradation row. A bundle that *is* present
    but disagrees with the session's feature manifest, rule family, ruleset
    contents, reward revision, scenario support, circuit split or conditions
    regime is a mismatch and the learned contribution is switched off: never
    silently trusted, never silently replaced.

    Every check fails closed, and an undeclared field is treated as *unknown*
    rather than as permission. A bundle that names no circuit is refused on a
    compiled real circuit: "we did not record which circuits this was trained
    on" is not evidence that it was trained on this one.
    """
    if requested_model_hash is None and bundle is None:
        return ModelDecision(
            enabled=False,
            baseline_identity=baseline_identity,
            detail=f"no learned bundle was requested; the validated baseline is {baseline_identity}",
        )
    if bundle is None:
        return _model_mismatch(
            baseline_identity,
            (f"bundle {requested_model_hash} was requested but is not loaded",),
        )

    mismatches: list[str] = []

    if bundle.approval_status is not ApprovalStatus.APPROVED:
        mismatches.append(
            f"bundle approval status is {bundle.approval_status.value!r}, not 'approved'; "
            "only a bundle promoted through the protocol may contribute"
        )

    if expected_feature_hash is None:
        mismatches.append(
            "the session did not declare a feature manifest hash, so the bundle's encoding cannot be verified"
        )
    elif bundle.feature_schema_hash != expected_feature_hash:
        mismatches.append(f"feature manifest {bundle.feature_schema_hash} != session {expected_feature_hash}")

    if expected_rule_family is None:
        mismatches.append("the session did not declare a rule family, so the bundle cannot be verified")
    elif bundle.rule_family != expected_rule_family:
        mismatches.append(f"rule family {bundle.rule_family!r} != session {expected_rule_family!r}")

    if expected_reward_revision is not None and bundle.reward_revision != expected_reward_revision:
        mismatches.append(
            f"reward revision {bundle.reward_revision!r} != session {expected_reward_revision!r}"
        )
    if (
        scenario_family is not None
        and bundle.supported_scenario_families
        and scenario_family not in bundle.supported_scenario_families
    ):
        mismatches.append(
            f"scenario family {scenario_family!r} is outside the bundle's declared support "
            f"{list(bundle.supported_scenario_families)}"
        )
    mismatches.extend(_ruleset_mismatches(bundle, expected_ruleset_hash))
    mismatches.extend(_circuit_mismatches(bundle, expected_track_id, expected_track_package_hash))
    mismatches.extend(_environment_mismatches(bundle, expected_conditions_id))

    if mismatches:
        return _model_mismatch(baseline_identity, tuple(mismatches))
    return ModelDecision(
        enabled=True,
        baseline_identity=baseline_identity,
        detail=(
            f"bundle {bundle.id} matches the session's feature, rule, reward, circuit and "
            "conditions manifests"
        ),
    )


def _ruleset_mismatches(bundle: ModelManifest, expected_ruleset_hash: str | None) -> list[str]:
    """The pack's *contents*, not only its name.

    ``rule_family`` identifies the pack; a pack whose energy window or
    detection lines moved keeps its id and is a different environment.
    """
    if expected_ruleset_hash is None:
        return []
    if bundle.ruleset_hash is None:
        return [
            (
                f"bundle {bundle.id} declares no rule pack content hash, so the limits it trained "
                "against cannot be identified"
            )
        ]
    if bundle.ruleset_hash != expected_ruleset_hash:
        return [
            (
                f"rule pack contents {bundle.ruleset_hash[:19]} != session {expected_ruleset_hash[:19]}; "
                "the pack kept its id but its limits moved"
            )
        ]
    return []


def _circuit_mismatches(
    bundle: ModelManifest,
    expected_track_id: str | None,
    expected_track_package_hash: str | None,
) -> list[str]:
    """Circuit split and compiled-geometry identity.

    The package hash is the sharper of the two: the same circuit id recompiled
    from different telemetry is different geometry, so a bundle trained on the
    earlier package is outside its regime on the later one.
    """
    if expected_track_package_hash is None:
        return []

    if not bundle.supported_track_ids:
        return [
            (
                f"bundle {bundle.id} declares no circuit split, and this session runs on the "
                f"compiled circuit {expected_track_id!r}; an undeclared split is unknown "
                "coverage, not coverage"
            )
        ]
    if expected_track_id is not None and expected_track_id not in bundle.supported_track_ids:
        return [
            f"circuit {expected_track_id!r} is outside the bundle's split {list(bundle.supported_track_ids)}"
        ]

    trained_on = bundle.track_package_hashes.get(expected_track_id or "")
    if trained_on is None:
        return [
            (
                f"bundle {bundle.id} names circuit {expected_track_id!r} but records no compiled "
                "package hash for it, so the geometry it trained on cannot be identified"
            )
        ]
    if trained_on != expected_track_package_hash:
        return [
            (
                f"circuit {expected_track_id!r} package {expected_track_package_hash[:19]} != the "
                f"{trained_on[:19]} the bundle trained on; recompiled geometry is different dynamics"
            )
        ]
    return []


def _environment_mismatches(bundle: ModelManifest, expected_conditions_id: str | None) -> list[str]:
    """A conditions tape the bundle was never evaluated under."""
    if expected_conditions_id is None:
        return []
    if not bundle.supported_conditions_ids:
        return [
            (
                f"the session runs under conditions {expected_conditions_id!r} and bundle "
                f"{bundle.id} declares no conditions support, so this is outside its evaluated regime"
            )
        ]
    if expected_conditions_id not in bundle.supported_conditions_ids:
        return [
            (
                f"conditions {expected_conditions_id!r} is outside the bundle's declared regime "
                f"{list(bundle.supported_conditions_ids)}"
            )
        ]
    return []


def _model_mismatch(baseline_identity: str, mismatches: tuple[str, ...]) -> ModelDecision:
    detail = (
        "learned contribution disabled: "
        + "; ".join(mismatches)
        + f". The validated baseline path in force is {baseline_identity}."
    )
    return ModelDecision(
        enabled=False,
        baseline_identity=baseline_identity,
        detail=detail,
        mismatches=mismatches,
        finding=DegradationFinding(
            row=DegradationRow.MODEL_MISMATCH,
            state=CapabilityState.UNAVAILABLE,
            effect="learned_contribution_disabled_baseline_named",
            detail=detail,
            reason_codes=(ReasonCode.LEARNED_MODEL_DISABLED, ReasonCode.BASELINE_FALLBACK),
            notes=(f"Validated baseline in force: {baseline_identity}.",),
        ),
    )


@dataclass(frozen=True, slots=True)
class DegradationInputs:
    """Everything the assessment reads. Explicit so the table stays auditable."""

    estimate: StateEstimate | None = None
    rule_context: RuleContext | None = None
    persistence: PersistenceStatus = field(default_factory=PersistenceStatus)
    model: ModelDecision | None = None
    timeout: TimeoutOutcome | None = None


def assess(inputs: DegradationInputs) -> DegradationReport:
    """Evaluate every row against one tick's inputs."""
    findings: list[DegradationFinding] = []
    if inputs.estimate is not None:
        for finding in (own_energy_finding(inputs.estimate), rival_energy_finding(inputs.estimate)):
            if finding is not None:
                findings.append(finding)
    if inputs.rule_context is not None:
        rules = rules_finding(inputs.rule_context)
        if rules is not None:
            findings.append(rules)
    if inputs.timeout is not None:
        findings.append(inputs.timeout.finding)
    findings.extend(persistence_findings(inputs.persistence))
    if inputs.model is not None and inputs.model.finding is not None:
        findings.append(inputs.model.finding)
    return DegradationReport(findings=tuple(findings))


__all__ = [
    "ANALYSIS_ONLY_NOTE",
    "RIVAL_ENERGY_QUANTILE_NOTE",
    "DegradationFinding",
    "DegradationInputs",
    "DegradationReport",
    "DegradationRow",
    "ModelDecision",
    "PersistenceStatus",
    "TimeoutOutcome",
    "assess",
    "check_model_compatibility",
    "conservative_energy_floor_j",
    "own_energy_finding",
    "persistence_findings",
    "rival_energy_finding",
    "rules_finding",
    "solver_timeout_outcome",
]
