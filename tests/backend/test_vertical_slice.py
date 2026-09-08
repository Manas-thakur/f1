"""The first integrated vertical slice, asserted link by link.

``program/ACCEPTANCE_AND_HANDOFF.md``:

    Start with synthetic two-car scenario; step simulation; emit delayed own-car
    observations; estimate state; load synthetic reviewed rules; generate legal
    baseline plan; publish recommendation; select and communicate via API;
    execute deliberately in simulator; observe execution; record named
    checkpoint outcome.

One test runs the whole loop once and asserts each link. It is deliberately long:
splitting it would let a link pass on a state some other test set up.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from afterlap_api.db.engine import command_transaction
from afterlap_api.db.models import Decision, ExecutionEventRow, OutcomeRecordRow
from afterlap_api.routes.exports import build_export_body
from afterlap_api.session import InProcessSessionRuntime
from afterlap_api.session.baseline_planner import UNCHECKED_CHECKER_VERSION
from afterlap_api.session.observation_source import FORBIDDEN_RIVAL_FIELDS
from afterlap_api.session.runtime import SNAPSHOT_SCHEMA
from afterlap_contracts import (
    SCHEMA_VERSION,
    ActionCode,
    CandidatePlan,
    CheckStatus,
    DeploymentProfile,
    EligibilityState,
    ExecutionMatch,
    OperatorAction,
    ProfileSegment,
    Provenance,
    RecommendationStatus,
)
from afterlap_core.rules import CHECKER_VERSION, check_plan, load_rule_pack
from afterlap_core.simulation import load_bundle

from .conftest import RULE_PACK_ID, SCENARIO_ID, SEED, actionable, start_session

CHECKPOINT_HORIZON_S = 40.0


def test_the_vertical_slice_closes_end_to_end(db_factory, tmp_path):
    session = start_session(db_factory)
    runtime = session.runtime
    bundle = load_bundle(SCENARIO_ID)
    pack = load_rule_pack(RULE_PACK_ID)

    # --- 1. the session starts from an immutable manifest with real hashes ---
    manifest = session.manifest
    assert manifest.mode.value == "simulation"
    assert manifest.scenario_id == SCENARIO_ID
    assert manifest.seed == SEED
    assert manifest.synthetic is True
    # Real content hashes, recomputable from the artefacts on disk.
    assert manifest.track_hash == bundle.track.config_hash
    assert manifest.car_hashes == {
        car_id: cfg.config_hash for car_id, cfg in sorted(bundle.car_configs.items())
    }
    assert manifest.ruleset_hash == pack.ruleset_hash
    for digest in (manifest.track_hash, manifest.ruleset_hash, manifest.objective_hash):
        assert digest.startswith("sha256:") and len(digest) == 71
    # Immutable: the frozen contract refuses mutation, and its identity is stable.
    assert manifest.content_hash() == manifest.content_hash()
    with pytest.raises(ValidationError):
        manifest.seed = 7  # type: ignore[misc]
    # Two cars, as the acceptance case requires.
    assert len(bundle.scenario.car_ids) == 2

    # --- 2. simulation steps and emits delayed own-car observations ---
    first = session.advance(1.0)
    assert first.session_time_s == pytest.approx(1.0)
    ingestion = runtime.last_ingestion
    assert ingestion is not None and ingestion.events, "no observation reached the estimator"
    delay_s = float(bundle.scenario.observation.delay_s.value)
    assert delay_s > 0.0
    newest = ingestion.newest_event_time_s
    assert newest is not None
    # The newest observation is genuinely older than the simulator clock, by at
    # least the configured source delay.
    assert first.session_time_s - newest >= delay_s - 1e-6

    # --- 3. observations contain no rival truth (asserted on the payload) ---
    records = runtime.normalised_records
    assert records, "the ingestion pipeline published nothing"
    ego = bundle.scenario.ego_car_id
    rival_ids = set(bundle.scenario.rival_ids)
    rival_records = [r for r in records if r.event.car_id in rival_ids]
    assert rival_records, "the rival was never observed at all"
    for record in rival_records:
        assert record.event.channel not in FORBIDDEN_RIVAL_FIELDS
        assert record.event.channel in ("speed_mps", "progress_m")
    serialised = json.dumps([r.event.model_dump(mode="json") for r in records])
    for forbidden in (
        'battery_energy_j", "car_id": "rival',
        "world_state",
        "rng_state",
        "recharge_ledger",
        "opponent_policy",
    ):
        assert forbidden not in serialised
    # The own car's energy is observed; the rival's never is.
    assert any(r.event.channel == "battery_energy_j" and r.event.car_id == ego for r in records)
    assert not any(r.event.channel == "battery_energy_j" and r.event.car_id in rival_ids for r in records)

    # --- 4. an estimate exists with a cutoff, and nothing later contributed ---
    estimate = first.estimate
    assert estimate is not None
    assert estimate.cutoff_s <= estimate.created_at_s
    assert estimate.contributing_event_ids
    times = ingestion.event_times_s
    for event_id in estimate.contributing_event_ids:
        assert event_id in times, f"{event_id} is not one of this decision's observations"
        assert times[event_id] <= estimate.cutoff_s + 1e-9, (
            f"observation {event_id} at {times[event_id]} s is later than the "
            f"decision cutoff {estimate.cutoff_s} s"
        )

    # --- 5a. while eligibility is unresolved, the illegal profile is excluded ---
    context = first.rule_context
    assert context is not None
    assert context.eligibility is EligibilityState.UNKNOWN
    assert DeploymentProfile.OVERTAKE not in context.admissible_profiles
    # ... and advice is suppressed rather than issued against an unknown rule.
    assert first.recommendation is not None
    assert first.recommendation.action_code is ActionCode.WITHDRAW_ADVICE

    # The driver is not frozen while the tool has no advice. A deliberate
    # conserving input during the run-up keeps the battery off its floor, and it
    # is recorded as UNSOLICITED: an unmatched driver action is evidence, and it
    # is never forced onto a recommendation.
    unsolicited = runtime.queue_driver_input(DeploymentProfile.HARVEST)
    assert unsolicited.recommendation_id is None

    # Run on until eligibility resolves and a checked plan is publishable.
    tick = session.advance_until(actionable)
    assert [e.match_status for e in runtime.executions] == [ExecutionMatch.UNSOLICITED]
    assert runtime.executions[0].recommendation_id is None
    with command_transaction(session.factory) as db:
        rows = db.query(ExecutionEventRow).filter_by(session_id=session.session_id).all()
        assert len(rows) == 1 and rows[0].decision_id is None
    context = tick.rule_context
    estimate = tick.estimate
    recommendation = tick.recommendation
    assert context is not None and estimate is not None and recommendation is not None
    assert context.eligibility is not EligibilityState.UNKNOWN
    assert not context.unknown_conditions
    assert context.admissible_profiles

    # --- 5b. an illegal profile is still excluded once permission exists ---
    checker_state = _checker_state(runtime, estimate, tick.session_time_s, bundle)
    illegal = _overtake_plan_outside_the_zone(runtime, checker_state, context)
    illegal_result = check_plan(illegal, checker_state, context, manifest=pack.manifest)
    assert illegal_result.status is CheckStatus.FAIL, "an overtake outside the zone was accepted"
    assert any(
        c.check_id == "overtake_eligibility" and c.status is CheckStatus.FAIL for c in illegal_result.checks
    )

    # --- 6. a legal plan was produced and independently checked ---
    planning = tick.planning
    assert planning is not None and planning.accepted
    plan = planning.accepted[0]
    assert plan.id == recommendation.plan_id
    for segment in plan.profile_segments:
        assert segment.profile_id in context.admissible_profiles
    checked = recommendation.constraint_result
    # The verdict came from A04's independent checker, not from the planner.
    assert checked.checker_version == CHECKER_VERSION
    assert checked.checker_version != UNCHECKED_CHECKER_VERSION
    assert plan.solver_status != checked.checker_version
    assert checked.status is CheckStatus.PASS
    assert {c.check_id for c in checked.checks} >= {
        "power_ceiling",
        "battery_energy_window",
        "recharge_allowance",
        "power_ramp",
        "overtake_eligibility",
        "execution_lead_time",
    }
    assert checked.ruleset_hash == pack.ruleset_hash

    # --- 7. the recommendation is published with its constraint result ---
    with command_transaction(session.factory) as db:
        stored = db.get(Decision, recommendation.id)
        assert stored is not None, "the published recommendation was not persisted"
        assert stored.payload["constraint_result"]["status"] == "pass"
        assert stored.payload["constraint_result"]["checker_version"] == CHECKER_VERSION
        # The decision keeps the estimate it was actually made from.
        assert stored.estimate_payload["revision"] == estimate.revision
        assert stored.estimate_payload["cutoff_s"] == estimate.cutoff_s

    # --- 8. the engineer selects it, and no execution event exists yet ---
    session.take_lease()
    outcome = session.act(recommendation, OperatorAction.SELECT, idempotency_key="select-1")
    assert outcome.recommendation.status is RecommendationStatus.SELECTED
    assert session.status_of(recommendation.id) is RecommendationStatus.SELECTED
    before_selection = len(runtime.executions)
    with command_transaction(session.factory) as db:
        matched = (
            db.query(ExecutionEventRow)
            .filter_by(session_id=session.session_id, decision_id=recommendation.id)
            .all()
        )
        assert matched == [], "selection produced an execution event; selection is not execution"
    assert len(runtime.executions) == before_selection

    # --- 9. mark communicated, then the driver executes deliberately, later ---
    # Selection bumped the recommendation's revision; the next action must be
    # issued against the revision the server now holds, not the one the UI saw.
    communicated = session.act(
        outcome.recommendation, OperatorAction.MARK_COMMUNICATED, idempotency_key="comm-1"
    )
    assert communicated.recommendation.status is RecommendationStatus.COMMUNICATED
    communicated_at_s = runtime.mark_communicated(recommendation.id)

    branch_hash, branch_snapshot = runtime.snapshot("before the driver acts")
    assert branch_snapshot["schema"] == SNAPSHOT_SCHEMA

    queued = runtime.queue_driver_input(
        plan.profile_segments[0].profile_id, recommendation_id=recommendation.id
    )
    assert queued.apply_at_s > runtime.session_time_s, "the input landed with no reaction delay"
    assert queued.delay_s == pytest.approx(runtime.config.driver_reaction_delay_s)
    # Still nothing has been executed against this recommendation: the queued
    # input is pending its reaction delay.
    assert not any(e.recommendation_id == recommendation.id for e in runtime.executions)
    assert runtime.pending_driver_inputs == (queued,)

    executed_tick = session.advance(1.0)
    assert len(executed_tick.executions) == 1
    execution = executed_tick.executions[0]
    assert execution.id == f"exe-{queued.id}"
    assert execution.source is Provenance.SIMULATED
    assert execution.match_status is ExecutionMatch.MATCHED
    assert execution.recommendation_id == recommendation.id
    # A separate, later event: after the communication and after the reaction delay.
    assert execution.start_time_s > communicated_at_s
    assert execution.delay_from_communication_s is not None
    assert execution.delay_from_communication_s >= runtime.config.driver_reaction_delay_s - 1e-9
    with command_transaction(session.factory) as db:
        rows = (
            db.query(ExecutionEventRow)
            .filter_by(session_id=session.session_id, decision_id=recommendation.id)
            .all()
        )
        assert len(rows) == 1 and rows[0].id == execution.id
    assert session.status_of(recommendation.id) is RecommendationStatus.EXECUTING

    # --- 10. the resulting telemetry changes the next estimate and decision ---
    after = session.advance_until(actionable, limit_s=6.0)
    executed_estimate = after.estimate
    executed_recommendation = after.recommendation
    assert executed_estimate is not None and executed_recommendation is not None

    counterfactual = InProcessSessionRuntime(
        bundle=bundle, pack=pack, planner=runtime.planner, config=runtime.config
    )
    counterfactual.initialise(session.manifest, SCENARIO_ID, SEED)
    counterfactual.restore(branch_snapshot)
    counterfactual.resume_after_restore()
    while counterfactual.session_time_s < after.session_time_s - 1e-9:
        counterfactual.advance(min(1.0, after.session_time_s - counterfactual.session_time_s))
    idle_estimate = counterfactual.last_estimate
    assert idle_estimate is not None
    assert counterfactual.executions == (), "the counterfactual branch executed nothing"
    assert (
        counterfactual.debug_truth()["cars"][ego]["active_profile"]
        != runtime.debug_truth()["cars"][ego]["active_profile"]
    ), "the deliberate input never reached the car"
    assert counterfactual.session_time_s == pytest.approx(after.session_time_s, abs=1e-6)

    executed_energy = executed_estimate.own_car.battery_energy_j.value
    idle_energy = idle_estimate.own_car.battery_energy_j.value
    assert executed_energy is not None and idle_energy is not None
    assert executed_energy != pytest.approx(idle_energy, abs=1.0), (
        "the deliberate driver execution left the observed energy unchanged, so the loop is "
        "not closed through the physics"
    )
    idle_recommendation = counterfactual.last_recommendation
    assert idle_recommendation is not None
    assert (
        executed_recommendation.state_revision != idle_recommendation.state_revision
        or executed_recommendation.display_text != idle_recommendation.display_text
        or executed_recommendation.plan_id != idle_recommendation.plan_id
    ), "the changed telemetry produced an identical next decision"
    assert branch_hash != runtime.snapshot()[0], "the snapshot hash did not move with the physics"

    # --- 11. a named checkpoint outcome is recorded and the record exports ---
    session.advance_until(lambda _t: bool(runtime.outcomes), limit_s=CHECKPOINT_HORIZON_S, step_s=1.0)
    outcomes = runtime.outcomes
    assert outcomes, "no named checkpoint outcome was recorded"
    recorded = outcomes[0]
    assert recorded.checkpoint.checkpoint_id in bundle.scenario.evaluation_checkpoints
    assert recorded.event_observed is True
    assert recorded.provenance is Provenance.SIMULATED
    assert recorded.elapsed_time_s is not None and recorded.energy_j is not None
    with command_transaction(session.factory) as db:
        stored_outcomes = db.query(OutcomeRecordRow).filter_by(session_id=session.session_id).all()
        assert {o.checkpoint_id for o in stored_outcomes} == {o.checkpoint.checkpoint_id for o in outcomes}

    session.sync()
    with command_transaction(session.factory) as db:
        from afterlap_api.db.models import Session as SessionRow

        row = db.get(SessionRow, session.session_id)
        assert row is not None
        export = build_export_body(db, row, None, None)

    assert export["synthetic"] is True and "SYNTHETIC EXPORT" in export["notice"]
    assert export["hashes"]["ruleset"] == pack.ruleset_hash
    assert export["hashes"]["track"] == bundle.track.config_hash
    assert export["hashes"]["objective"] == manifest.objective_hash
    assert export["units"]["energy_j"] == "J"
    assert any(d["id"] == recommendation.id for d in export["decisions"])
    assert any(e["id"] == execution.id for e in export["execution_events"])
    assert export["outcome_records"], "the export carries no outcome record"
    assert export["operator_commands"], "the export carries no operator command"
    assert any(t["to_state"] == "executing" for t in export["lifecycle_transitions"]), (
        "the export does not show the execution transition"
    )
    text = json.dumps(export).lower()
    for forbidden in ("worldstate", "world_state", "rng_state", "sensor_buffer", "ledgers"):
        assert forbidden not in text

    # The runtime's own record is exportable too, and equally free of truth.
    runtime_record = runtime.export_record()
    assert runtime_record["ruleset_hash"] == pack.ruleset_hash
    assert runtime_record["outcomes"]
    assert runtime_record["executions"]
    assert "world" not in json.dumps(runtime_record).lower()


def _checker_state(runtime, estimate, now_s, bundle):  # type: ignore[no-untyped-def]
    from afterlap_api.session.baseline_planner import checker_state_for

    car = bundle.car_configs[bundle.scenario.ego_car_id]
    return checker_state_for(
        estimate=estimate,
        session_time_s=now_s,
        track_length_m=bundle.track.length,
        battery_energy_j=float(estimate.own_car.battery_energy_j.value or 0.0),
        driver_reaction_time_s=runtime.config.driver_reaction_delay_s,
        charge_bus_efficiency=car.eta_charge.value,
        discharge_efficiency=car.eta_discharge.value,
    )


def _overtake_plan_outside_the_zone(runtime, checker_state, context) -> CandidatePlan:
    """A plan that asks for OVERTAKE well past the pack's activation zone.

    The pack's activation line is at 1900 m and the next checkpoint at 2100 m, so
    a request beyond 2100 m lies outside any permitted zone even when the
    permission itself has been granted.
    """
    from afterlap_contracts import ObjectiveTerms

    start = 3000.0
    return CandidatePlan(
        schema_version=SCHEMA_VERSION,
        id="illegal-overtake",
        state_revision=runtime.revision,
        intention=ActionCode.ATTACK,
        profile_segments=(
            ProfileSegment(
                start_progress_m=start,
                end_progress_m=start + 400.0,
                profile_id=DeploymentProfile.OVERTAKE,
                requested_budget_j=0.0,
                harvest_target_j=0.0,
                execution_window_s=2.0,
            ),
        ),
        objective=ObjectiveTerms(
            objective_version="objective-v1",
            expected_utility=0.0,
            tail_alpha=0.1,
            cvar_loss=0.0,
            lambda_tail=0.0,
            switch_count=1,
            lambda_switch=0.1,
            final_score=0.0,
        ),
        constraint_result=context and _unchecked(context),
        objective_version="objective-v1",
    )


def _unchecked(context):  # type: ignore[no-untyped-def]
    from afterlap_contracts import ConstraintResult

    return ConstraintResult(
        schema_version=SCHEMA_VERSION,
        status=CheckStatus.UNKNOWN,
        checks=(),
        ruleset_hash=context.ruleset_hash,
        checked_at_s=context.resolved_at_s,
        checker_version=UNCHECKED_CHECKER_VERSION,
        unresolved_conditions=("constructed_for_a_negative_test",),
    )
