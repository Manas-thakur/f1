"""One test per row of the ARCHITECTURE.md runtime degradation table.

Each asserts the *documented behaviour*, not merely that nothing crashed: the
analysis-only session must actually refuse to issue an energy directive, the
exhausted spool must actually stop new recommendations reaching the store, and
the mismatched bundle must actually name the baseline that replaced it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import OperationalError

from afterlap_api.db.engine import command_transaction
from afterlap_api.db.models import Decision
from afterlap_api.session import (
    RIVAL_ENERGY_QUANTILE_NOTE,
    BaselinePlanner,
    BoundedSpool,
    DegradationRow,
    PersistenceStatus,
    RuntimeConfig,
    SessionRecorder,
    check_model_compatibility,
    solver_timeout_outcome,
)
from afterlap_api.session.baseline_planner import BASELINE_IDENTITY, PlanRequest
from afterlap_api.session.degradation import persistence_findings
from afterlap_contracts import (
    SCHEMA_VERSION,
    ActionCode,
    CheckStatus,
    ModelManifest,
    PlanningStatus,
    Provenance,
    Quality,
    ReasonCode,
)
from afterlap_core.rules import check_plan

from .conftest import (
    NO_ENERGY_SCENARIO_ID,
    UNKNOWN_RULE_PACK_ID,
    actionable,
    start_session,
)

# --- row 1: missing required own-car energy ---------------------------------------


def test_missing_own_energy_is_analysis_only_with_no_precise_energy_directive(db_factory):
    session = start_session(db_factory, scenario_id=NO_ENERGY_SCENARIO_ID)
    tick = session.advance_until(lambda t: t.estimate is not None, limit_s=5.0)

    estimate = tick.estimate
    assert estimate is not None
    # The source cannot see stored energy, so the estimate says so rather than
    # inventing a number.
    assert estimate.quality.own_energy_capability is False
    assert estimate.own_car.battery_energy_j.value is None
    assert estimate.own_car.battery_energy_j.quality is Quality.MISSING
    assert estimate.own_car.battery_energy_interval is not None
    assert estimate.own_car.battery_energy_interval.kind == "physical_bounds"

    report = session.runtime.degradation
    finding = report.find(DegradationRow.MISSING_OWN_ENERGY)
    assert finding is not None
    assert finding.effect == "analysis_only_no_precise_energy_directive"
    assert finding.suppresses_energy_directive is True
    assert report.analysis_only is True

    # The documented consequence: no precise energy directive is issued.
    planning = tick.planning
    assert planning is not None
    assert planning.status is PlanningStatus.INPUT_UNAVAILABLE
    assert planning.accepted == ()
    recommendation = tick.recommendation
    assert recommendation is not None
    assert recommendation.action_code is ActionCode.WITHDRAW_ADVICE
    assert recommendation.plan_id is None
    assert ReasonCode.OWN_ENERGY_UNAVAILABLE in recommendation.reason_codes

    # ... while the analysis itself is still published.
    assert tick.rule_context is not None
    assert tick.rule_context.applicable_limits.deployment_ceiling_w is not None


# --- row 2: unknown opponent energy -----------------------------------------------


def test_unknown_opponent_energy_widens_scenarios_and_never_becomes_a_point_value(db_factory):
    session = start_session(db_factory)
    tick = session.advance_until(lambda t: bool(t.estimate and t.estimate.rival_beliefs), limit_s=6.0)
    estimate = tick.estimate
    assert estimate is not None and estimate.rival_beliefs

    for rival in estimate.rival_beliefs:
        interval = rival.energy_interval_j
        assert interval is not None, "the rival energy belief collapsed to nothing"
        # A05's interval is a model quantile with a declared coverage; it is
        # never a calibrated bound and never a measurement.
        assert interval.kind == "quantile"
        assert interval.coverage is not None
        assert interval.provenance is not Provenance.MEASURED
        assert interval.quality is not Quality.VALID
        width = interval.width
        assert width is not None and width > 0.0, "the interval is a point value"
        if rival.energy_mean_j is not None:
            assert rival.energy_mean_j.provenance is not Provenance.MEASURED
            assert rival.energy_mean_j.standard_deviation is not None

    finding = session.runtime.degradation.find(DegradationRow.UNKNOWN_OPPONENT_ENERGY)
    assert finding is not None
    assert finding.effect == "wider_scenarios_never_a_point_value"
    assert ReasonCode.RIVAL_ENERGY_UNKNOWN in finding.reason_codes
    # The measured under-coverage travels with the finding rather than being
    # rounded off at the edge.
    assert RIVAL_ENERGY_QUANTILE_NOTE in finding.notes
    assert "0.7885" in RIVAL_ENERGY_QUANTILE_NOTE and "0.90" in RIVAL_ENERGY_QUANTILE_NOTE

    published = session.advance_until(actionable)
    assert published.recommendation is not None
    assert ReasonCode.RIVAL_ENERGY_UNKNOWN in published.recommendation.reason_codes


# --- row 3: missing event rules ---------------------------------------------------


def test_missing_event_rules_leave_eligibility_unsupported_and_suppress_advice(db_factory):
    session = start_session(db_factory, ruleset_id=UNKNOWN_RULE_PACK_ID)
    tick = session.advance_until(lambda t: t.rule_context is not None, limit_s=5.0)

    context = tick.rule_context
    assert context is not None
    assert "overtake_gap_threshold_from_unresolved_event_document" in context.unknown_conditions
    # Unsupported eligibility: no profile is admissible at all, rather than a
    # permissive default.
    assert context.admissible_profiles == ()
    assert context.has_unknown_critical_condition

    finding = session.runtime.degradation.find(DegradationRow.MISSING_EVENT_RULES)
    assert finding is not None
    assert finding.effect == "unsupported_eligibility_and_curve_state"
    assert finding.withdraw_advice is True

    planning = tick.planning
    assert planning is not None
    assert planning.status is PlanningStatus.RULES_UNKNOWN
    recommendation = tick.recommendation
    assert recommendation is not None
    assert recommendation.action_code is ActionCode.WITHDRAW_ADVICE
    assert recommendation.constraint_result.status is CheckStatus.UNKNOWN
    assert recommendation.constraint_result.unresolved_conditions


# --- row 4: solver timeout --------------------------------------------------------


class _TimeoutAfter:
    """A planner that produces plans and then starts missing its deadline."""

    identity = "timeout-probe"

    def __init__(self, good_decisions: int) -> None:
        self._inner = BaselinePlanner()
        self._remaining = good_decisions
        self.timeouts = 0

    def plan(self, request: PlanRequest):  # type: ignore[no-untyped-def]
        if self._remaining > 0:
            self._remaining -= 1
            return self._inner.plan(request)
        self.timeouts += 1
        from afterlap_contracts import PlanningResult

        return PlanningResult(
            schema_version=SCHEMA_VERSION,
            session_id=request.session_id,
            state_revision=request.revision,
            status=PlanningStatus.DEADLINE_EXCEEDED,
            created_at_s=request.now_s,
            deadline_s=request.deadline_s,
            duration_ms=request.deadline_s * 1000.0 + 25.0,
            reason_codes=(ReasonCode.SOLVER_TIMEOUT,),
            baseline_identity=request.baseline_identity,
            detail="synthetic solver timeout",
        )


def test_a_solver_timeout_reissues_a_revalidated_prior_plan(db_factory):
    planner = _TimeoutAfter(good_decisions=100)
    # A three-second lead means a plan issued one decision ago still starts
    # ahead of the car, so revalidating it is a live question rather than a
    # foregone failure. With the default 1.2 s lead the car has already passed
    # the plan's start point by the next decision and the prior plan is
    # correctly withdrawn instead - that branch is the next test.
    session = start_session(
        db_factory, planner=planner, config=RuntimeConfig(driver_reaction_delay_s=0.35, lead_time_s=3.0)
    )
    session.advance(1.0)
    session.runtime.queue_driver_input(
        __import__("afterlap_contracts", fromlist=["DeploymentProfile"]).DeploymentProfile.HARVEST
    )
    accepted = session.advance_until(actionable)
    prior_plan_id = accepted.planning.accepted[0].id  # type: ignore[union-attr]

    # From here the solver misses every deadline.
    planner._remaining = 0
    after = session.advance(1.0)
    assert planner.timeouts >= 1

    finding = session.runtime.degradation.find(DegradationRow.SOLVER_TIMEOUT)
    assert finding is not None
    assert finding.effect == "revalidated_prior_plan"
    assert finding.withdraw_advice is False
    planning = after.planning
    assert planning is not None
    assert planning.status is PlanningStatus.OK
    assert planning.accepted[0].id == prior_plan_id, "a different plan was issued, not the prior one"
    assert ReasonCode.SOLVER_TIMEOUT in planning.reason_codes
    # The reissued plan carries a *fresh* independent check, not the old verdict.
    assert planning.accepted[0].constraint_result.checked_at_s == pytest.approx(after.session_time_s, abs=1.0)
    assert after.recommendation is not None
    assert after.recommendation.action_code is not ActionCode.WITHDRAW_ADVICE


def test_a_solver_timeout_with_no_prior_plan_withdraws_tactical_advice(db_factory):
    planner = _TimeoutAfter(good_decisions=0)
    session = start_session(db_factory, planner=planner)
    tick = session.advance(1.0)

    finding = session.runtime.degradation.find(DegradationRow.SOLVER_TIMEOUT)
    assert finding is not None
    assert finding.effect == "withdrawn_tactical_advice"
    assert finding.withdraw_advice is True
    assert tick.recommendation is not None
    assert tick.recommendation.action_code is ActionCode.WITHDRAW_ADVICE
    assert ReasonCode.SOLVER_TIMEOUT in tick.recommendation.reason_codes


def test_a_prior_plan_that_no_longer_checks_out_is_withdrawn_not_carried_forward(db_factory):
    """The revalidation is a real check, and a FAIL forces a withdrawal."""
    session = start_session(db_factory)
    session.advance(1.0)
    session.runtime.queue_driver_input(
        __import__("afterlap_contracts", fromlist=["DeploymentProfile"]).DeploymentProfile.HARVEST
    )
    tick = session.advance_until(actionable)
    plan = tick.planning.accepted[0]  # type: ignore[union-attr]
    context = tick.rule_context
    estimate = tick.estimate
    assert context is not None and estimate is not None

    # Re-check the accepted plan against a state whose battery is nearly empty:
    # the same plan is no longer legal.
    from afterlap_api.session.baseline_planner import checker_state_for

    car = __import__("afterlap_core.simulation", fromlist=["load_bundle"]).load_bundle(
        "two-straight-counterattack"
    )
    ego = car.scenario.ego_car_id
    empty_state = checker_state_for(
        estimate=estimate,
        session_time_s=tick.session_time_s,
        track_length_m=car.track.length,
        battery_energy_j=1.0,
        driver_reaction_time_s=session.runtime.config.driver_reaction_delay_s,
        charge_bus_efficiency=car.car_configs[ego].eta_charge.value,
        discharge_efficiency=car.car_configs[ego].eta_discharge.value,
    )
    revalidation = check_plan(plan, empty_state, context, manifest=session.runtime.rule_pack.manifest)
    assert revalidation.status is CheckStatus.FAIL

    outcome = solver_timeout_outcome(
        elapsed_ms=250.0, deadline_ms=200.0, prior_plan_id=plan.id, revalidation=revalidation
    )
    assert outcome.revalidated_prior_plan is False
    assert outcome.withdrawn is True
    assert outcome.finding.effect == "withdrawn_tactical_advice"
    assert "fail" in outcome.finding.detail


# --- rows 5 and 6: persistence ----------------------------------------------------


class _BrokenFactory:
    """A session factory whose sessions cannot be opened. Models a store outage."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise OperationalError("SELECT 1", {}, Exception("database is unavailable"))


def test_a_database_failure_spools_the_write_and_raises_a_visible_warning(db_factory, tmp_path):
    # No recorder: this session's decisions have not been stored, so the drained
    # replay below is the first and only write of them.
    session = start_session(db_factory, with_recorder=False)
    tick = session.advance(1.0)
    estimate = tick.estimate
    recommendation = tick.recommendation
    assert estimate is not None and recommendation is not None

    spool = BoundedSpool(tmp_path / "spool", session.session_id, capacity=4)
    broken = SessionRecorder(_BrokenFactory(), session_id=session.session_id, spool=spool)  # type: ignore[arg-type]

    outcome = broken.publish_recommendation(
        recommendation=recommendation, estimate=estimate, session_time_s=tick.session_time_s
    )
    assert outcome.committed is False
    assert outcome.spooled is True
    assert len(spool) == 1
    assert spool.entries[0].kind == "store_decision"

    status = broken.status()
    assert status.degraded is True
    assert status.spooled == 1 and status.capacity == 4
    assert status.last_error is not None and "OperationalError" in status.last_error
    assert status.warnings, "the persistence degradation is not visible anywhere"

    finding = next(f for f in persistence_findings(status) if f.row is DegradationRow.DATABASE_FAILURE)
    assert finding.effect == "bounded_local_spool_and_visible_persistence_warning"
    assert finding.halts_recommendations is False
    assert broken.accepts_new_recommendations() is True

    # Recovery: point the recorder at a working store and drain in order.
    recovered = SessionRecorder(db_factory, session_id=session.session_id, spool=spool)
    replayed, remaining = recovered.drain_spool()
    assert (replayed, remaining) == (1, 0)
    with command_transaction(db_factory) as db:
        assert db.get(Decision, recommendation.id) is not None


def test_an_exhausted_spool_halts_new_recommendations(db_factory, tmp_path):
    session = start_session(db_factory, with_recorder=False)
    tick = session.advance(1.0)
    estimate, recommendation = tick.estimate, tick.recommendation
    assert estimate is not None and recommendation is not None

    spool = BoundedSpool(tmp_path / "spool", session.session_id, capacity=1)
    broken = SessionRecorder(_BrokenFactory(), session_id=session.session_id, spool=spool)  # type: ignore[arg-type]

    first = broken.publish_recommendation(
        recommendation=recommendation, estimate=estimate, session_time_s=tick.session_time_s
    )
    assert first.spooled is True and first.halted is True, "a full spool must announce the halt"
    assert broken.accepts_new_recommendations() is False

    status = broken.status()
    assert status.exhausted is True
    halt = next(f for f in persistence_findings(status) if f.row is DegradationRow.SPOOL_FULL)
    assert halt.effect == "halt_new_operational_recommendations"
    assert halt.halts_recommendations is True

    # The halt is real: a further publish is refused outright and nothing more
    # is spooled, so no advice exists that could not be audited.
    second = broken.publish_recommendation(
        recommendation=recommendation, estimate=estimate, session_time_s=tick.session_time_s
    )
    assert second.committed is False and second.spooled is False and second.halted is True
    assert len(spool) == 1


def test_a_runtime_whose_store_is_halted_publishes_no_new_recommendation(db_factory, tmp_path):
    """The halt reaches the runtime, not just the recorder."""
    session = start_session(db_factory)
    session.advance(1.0)
    runtime = session.runtime
    recorder = session.recorder
    assert recorder is not None

    with command_transaction(db_factory) as db:
        before = db.query(Decision).filter_by(session_id=session.session_id).count()

    recorder._exhausted = True  # the spool filled during an outage
    assert recorder.accepts_new_recommendations() is False
    tick = session.advance(1.0)
    assert tick.recommendation is None, "a recommendation was published while the store was halted"

    with command_transaction(db_factory) as db:
        after = db.query(Decision).filter_by(session_id=session.session_id).count()
    assert after == before, "a decision was written while new recommendations were halted"
    assert runtime.degradation.halted is True


def test_persistence_findings_are_absent_while_the_store_is_healthy():
    assert persistence_findings(PersistenceStatus()) == ()


# --- row 7: training/model mismatch -----------------------------------------------


def _bundle(**overrides) -> ModelManifest:  # type: ignore[no-untyped-def]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "id": "sac-candidate-1",
        "algorithm": "SAC",
        "weights_hash": "sha256:" + "a" * 64,
        "feature_schema_hash": "sha256:" + "b" * 64,
        "rule_family": "synthetic-pack-v1",
        "reward_revision": "objective-v1",
        "supported_scenario_families": ("two-straight-counterattack",),
        "created_at": datetime.now(UTC),
    }
    payload.update(overrides)
    return ModelManifest(**payload)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"feature_schema_hash": "sha256:" + "c" * 64}, "feature manifest"),
        ({"rule_family": "some-other-pack"}, "rule family"),
        ({"reward_revision": "objective-v2"}, "reward revision"),
        ({"supported_scenario_families": ("a-different-family",)}, "scenario family"),
    ],
)
def test_a_model_mismatch_disables_the_learned_contribution_and_names_the_baseline(overrides, expected):
    decision = check_model_compatibility(
        requested_model_hash="sha256:" + "d" * 64,
        bundle=_bundle(**overrides),
        expected_feature_hash="sha256:" + "b" * 64,
        expected_rule_family="synthetic-pack-v1",
        expected_reward_revision="objective-v1",
        baseline_identity=BASELINE_IDENTITY,
        scenario_family="two-straight-counterattack",
    )
    assert decision.enabled is False
    assert decision.mismatches and expected in decision.mismatches[0]
    # The validated baseline path is named explicitly, not implied.
    assert BASELINE_IDENTITY in decision.detail
    assert decision.baseline_identity == BASELINE_IDENTITY
    finding = decision.finding
    assert finding is not None
    assert finding.row is DegradationRow.MODEL_MISMATCH
    assert finding.effect == "learned_contribution_disabled_baseline_named"
    assert ReasonCode.LEARNED_MODEL_DISABLED in finding.reason_codes
    assert ReasonCode.BASELINE_FALLBACK in finding.reason_codes


def test_a_matching_bundle_is_not_reported_as_a_mismatch():
    decision = check_model_compatibility(
        requested_model_hash="sha256:" + "d" * 64,
        bundle=_bundle(),
        expected_feature_hash="sha256:" + "b" * 64,
        expected_rule_family="synthetic-pack-v1",
        expected_reward_revision="objective-v1",
        baseline_identity=BASELINE_IDENTITY,
        scenario_family="two-straight-counterattack",
    )
    assert decision.enabled is True
    assert decision.finding is None


def test_a_session_with_no_bundle_runs_the_named_baseline(db_factory):
    session = start_session(db_factory)
    decision = session.runtime.model_decision
    assert decision is not None
    assert decision.enabled is False
    assert decision.baseline_identity == BASELINE_IDENTITY
    tick = session.advance(1.0)
    assert tick.recommendation is not None
    assert tick.recommendation.learned_contribution_enabled is False
    assert tick.recommendation.baseline_identity == BASELINE_IDENTITY
