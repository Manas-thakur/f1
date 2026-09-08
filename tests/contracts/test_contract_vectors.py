"""Executable form of ``contracts/TEST_VECTORS.md``.

Each test names the vector it implements. These run before any downstream
integration; a failure here blocks the wave, it does not get an adjusted
expectation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from afterlap_contracts import (
    CHANNELS_BY_NAME,
    SCHEMA_VERSION,
    ActionCode,
    CheckStatus,
    DeploymentProfile,
    EligibilityState,
    ErrorCode,
    Provenance,
    Quality,
    RecommendationStatus,
    SessionMode,
    StreamEventType,
    channel,
    fixtures as fx,
)
from afterlap_contracts.errors import ApiError
from afterlap_contracts.events import (
    EstimateUpdatedPayload,
    SnapshotPayload,
    StreamEnvelope,
    StreamEnvelopeAdapter,
)
from afterlap_contracts.quantities import ProbabilityStatement, ScalarValue
from afterlap_contracts.requests import DriverActionRequest
from afterlap_contracts.telemetry import TelemetryEvent

SPEC_SCHEMA = (
    Path(__file__).resolve().parents[2] / "docs" / "contracts" / "schemas" / "telemetry-event.schema.json"
)
SPEC_EXAMPLE = SPEC_SCHEMA.with_name("telemetry-event.example.json")


@pytest.mark.parametrize(
    ("channel_name", "si_value", "expected_display", "expected_unit"),
    [
        ("electrical_power_w", 350_000.0, 350.0, "kW"),
        ("battery_energy_j", 1_500_000.0, 1.50, "MJ"),
        ("speed_mps", 90.0, 324.0, "km/h"),
    ],
)
def test_display_conversions(channel_name, si_value, expected_display, expected_unit):
    spec = channel(channel_name)
    assert spec.display_unit == expected_unit
    assert spec.to_display(si_value) == pytest.approx(expected_display, rel=1e-12)
    assert spec.from_display(spec.to_display(si_value)) == pytest.approx(si_value, rel=1e-12)


def test_temperature_display_uses_offset_not_scale():
    spec = channel("battery_temperature_k")
    assert spec.to_display(273.15) == pytest.approx(0.0, abs=1e-9)
    assert spec.to_display(318.15) == pytest.approx(45.0, abs=1e-9)


def test_every_registered_channel_declares_a_display_conversion():
    for name, spec in CHANNELS_BY_NAME.items():
        assert spec.display_scale > 0.0, name
        assert spec.unit and spec.display_unit, name


def test_missing_energy_is_null_with_missing_quality():
    estimate = fx.state_estimate(energy_j=None)
    energy = estimate.own_car.battery_energy_j
    assert energy.value is None
    assert energy.quality is Quality.MISSING
    assert estimate.own_car.has_energy_capability is False
    assert estimate.quality.own_energy_capability is False
    interval = estimate.own_car.battery_energy_interval
    assert interval is not None and interval.kind == "physical_bounds"
    assert interval.coverage is None


def test_a_null_value_cannot_claim_valid_quality():
    with pytest.raises(ValidationError, match="quality=valid"):
        ScalarValue(value=None, unit="J", provenance=Provenance.MEASURED, quality=Quality.VALID)


def test_a_known_value_cannot_claim_missing_quality():
    with pytest.raises(ValidationError, match="requires value=None"):
        ScalarValue(value=1.0, unit="J", provenance=Provenance.MEASURED, quality=Quality.MISSING)


def test_zero_is_a_legitimate_known_value():
    zero = ScalarValue(value=0.0, unit="W", provenance=Provenance.SIMULATED, quality=Quality.VALID)
    assert zero.is_known is True


def test_late_event_cannot_change_a_published_decision():
    published = fx.recommendation()
    assert published.observation_cutoff_s == 12.2

    late = fx.telemetry_event(sequence=99, source_time_s=12.0, received_time_s=12.4)
    assert late.source_time_s < published.observation_cutoff_s
    assert late.received_time_s > published.observation_cutoff_s

    with pytest.raises(ValidationError):
        published.observation_cutoff_s = 12.5  # type: ignore[misc]

    revised = published.revise(revision=published.revision + 1)
    assert revised.revision == published.revision + 1
    assert published.revision == 1, "the original record must not mutate"


def test_estimate_cannot_be_created_before_its_own_cutoff():
    with pytest.raises(ValidationError, match="before its own observation cutoff"):
        fx.state_estimate().revise(created_at_s=1.0)


def _envelope(sequence: int, payload) -> StreamEnvelope:
    return StreamEnvelope(
        schema_version=SCHEMA_VERSION,
        session_id=fx.FIXTURE_SESSION_ID,
        sequence=sequence,
        event_type=payload.event_type,
        session_time_s=12.3,
        payload=payload,
    )


def test_snapshot_then_gapped_delta_is_detectable():
    snapshot = fx.session_snapshot()
    assert snapshot.last_sequence == 100

    delta = _envelope(102, EstimateUpdatedPayload(estimate=fx.state_estimate(revision=5)))
    assert delta.sequence > snapshot.last_sequence + 1, "a gap must be visible to the client"

    contiguous = _envelope(101, EstimateUpdatedPayload(estimate=fx.state_estimate(revision=5)))
    assert contiguous.sequence == snapshot.last_sequence + 1


def test_envelope_rejects_a_payload_that_disagrees_with_its_type():
    payload = SnapshotPayload(snapshot=fx.session_snapshot())
    with pytest.raises(ValidationError, match="disagrees with payload"):
        StreamEnvelope(
            schema_version=SCHEMA_VERSION,
            session_id=fx.FIXTURE_SESSION_ID,
            sequence=1,
            event_type=StreamEventType.HEARTBEAT,
            session_time_s=1.0,
            payload=payload,
        )


def test_decision_and_quality_events_are_lossless_but_telemetry_may_coalesce():
    recommendation_envelope = _envelope(
        7,
        __import__(
            "afterlap_contracts.events", fromlist=["RecommendationUpdatedPayload"]
        ).RecommendationUpdatedPayload(recommendation=fx.recommendation()),
    )
    assert recommendation_envelope.is_lossless is True

    telemetry_envelope = _envelope(
        8,
        __import__("afterlap_contracts.events", fromlist=["TelemetryViewPayload"]).TelemetryViewPayload(
            series=()
        ),
    )
    assert telemetry_envelope.is_lossless is False


def test_envelope_round_trips_through_json():
    original = _envelope(11, SnapshotPayload(snapshot=fx.session_snapshot()))
    restored = StreamEnvelopeAdapter.validate_json(original.model_dump_json())
    assert restored == original


def test_identical_selections_share_an_idempotency_key_and_body_hash():
    first = fx.operator_event()
    second = fx.operator_event()
    assert first.idempotency_key == second.idempotency_key
    assert first.content_hash() == second.content_hash()

    different_body = second.revise(reason="changed my mind")
    assert different_body.idempotency_key == first.idempotency_key
    assert different_body.content_hash() != first.content_hash(), (
        "same key with a different body must be distinguishable, which is what makes it a 409"
    )
    assert ApiError.of(ErrorCode.IDEMPOTENCY_CONFLICT, "conflicting body", "req-1").http_status == 409


def test_recommendation_expiry_is_evaluated_against_session_time():
    published = fx.recommendation(valid_from_s=12.3, expires_at_s=20.0)
    assert published.is_actionable_at(15.0) is True
    assert published.is_expired_at(20.0) is True
    assert published.is_actionable_at(20.0) is False
    assert published.is_actionable_at(12.0) is False, "not yet valid"

    error = ApiError.of(ErrorCode.RECOMMENDATION_EXPIRED, "expired at 20.0 s", "req-2")
    assert error.http_status == 422
    assert error.retryable is False


def test_terminal_statuses_are_not_actionable():
    for status in (
        RecommendationStatus.EXPIRED,
        RecommendationStatus.INVALIDATED,
        RecommendationStatus.REJECTED,
        RecommendationStatus.COMPLETED,
    ):
        assert fx.recommendation(status=status).is_actionable_at(15.0) is False


def test_snapshot_schema_exposes_no_simulator_truth():
    payload = fx.session_snapshot().model_dump(mode="json")
    text = json.dumps(payload).lower()
    for forbidden in ("worldstate", "world_state", "rng_state", "integrator_state", "truth"):
        assert forbidden not in text, f"snapshot leaked {forbidden}"

    from afterlap_contracts.schema_export import build_json_schemas

    schema_text = json.dumps(build_json_schemas()).lower()
    assert "worldstate" not in schema_text, "WorldState must have no wire schema at all"


def test_rival_energy_can_never_be_labelled_measured():
    with pytest.raises(ValidationError, match="cannot be labelled measured"):
        fx.rival_belief().revise(
            energy_mean_j=ScalarValue(
                value=2_600_000.0, unit="J", provenance=Provenance.MEASURED, quality=Quality.VALID
            )
        )


def test_unknown_condition_removes_every_admissible_profile():
    context = fx.rule_context(unknown_conditions=("event_supporting_documents",))
    assert context.has_unknown_critical_condition is True
    assert context.admissible_profiles == ()
    assert context.permits(DeploymentProfile.OVERTAKE) is False


def test_ineligible_context_permits_non_overtake_profiles_only():
    context = fx.rule_context(eligibility=EligibilityState.INELIGIBLE)
    assert context.permits(DeploymentProfile.OVERTAKE) is False
    assert context.permits(DeploymentProfile.PUSH) is True


def test_unknown_check_carries_no_numeric_margin():
    result = fx.constraint_result(status=CheckStatus.UNKNOWN)
    assert result.status is CheckStatus.UNKNOWN
    assert result.margins == {}
    assert result.unresolved_conditions


def test_aggregate_status_cannot_disagree_with_its_checks():
    passing = fx.constraint_result()
    with pytest.raises(ValidationError, match="disagrees with worst individual check"):
        passing.revise(status=CheckStatus.FAIL)


@pytest.mark.parametrize("mode", [SessionMode.REPLAY, SessionMode.LIVE_TEAM])
def test_non_simulation_sessions_forbid_driver_input(mode):
    manifest = fx.session_manifest(mode=mode)
    assert manifest.allows_simulator_driver_input is False
    error = ApiError.of(ErrorCode.MODE_NOT_PERMITTED, f"{mode} forbids driver input", "req-3")
    assert error.http_status == 403


def test_simulation_sessions_permit_driver_input():
    assert fx.session_manifest(mode=SessionMode.SIMULATION).allows_simulator_driver_input is True
    request = DriverActionRequest(
        profile_id=DeploymentProfile.OVERTAKE, observed_at_s=13.1, operator_id="engineer-1"
    )
    assert request.profile_id is DeploymentProfile.OVERTAKE


def test_source_capability_mode_must_match_its_session():
    replay_capability = fx.source_capability(mode=SessionMode.REPLAY)
    with pytest.raises(ValidationError, match="declares mode"):
        fx.session_manifest(mode=SessionMode.SIMULATION).revise(source_capabilities=(replay_capability,))


def test_manifest_hash_is_stable_for_identical_inputs():
    assert fx.session_manifest().content_hash() == fx.session_manifest().content_hash()
    assert fx.session_manifest().revise(seed=43).content_hash() != fx.session_manifest().content_hash()


def test_canonical_json_is_order_independent():
    manifest = fx.session_manifest()
    reparsed = type(manifest).model_validate_json(manifest.model_dump_json())
    assert reparsed.canonical_json() == manifest.canonical_json()


def test_generated_telemetry_schema_matches_the_normative_seed():
    spec = json.loads(SPEC_SCHEMA.read_text(encoding="utf-8"))
    generated = TelemetryEvent.model_json_schema(mode="serialization")

    assert set(spec["required"]) == set(generated["required"])
    assert generated.get("additionalProperties") is False

    spec_props = spec["properties"]
    gen_props = generated["properties"]
    assert set(spec_props) == set(gen_props)

    assert gen_props["schema_version"]["const"] == "1.0"
    for name in ("event_id", "session_id", "car_id", "channel"):
        assert gen_props[name]["minLength"] == spec_props[name]["minLength"], name
    assert gen_props["sequence"]["minimum"] == 0
    for name in ("source_time_s", "received_time_s"):
        assert gen_props[name]["minimum"] == 0

    def enum_values(node: dict) -> set[str]:
        if "enum" in node:
            return set(node["enum"])
        ref = node.get("allOf", [node])[0].get("$ref", "")
        return set(generated["$defs"][ref.rsplit("/", 1)[-1]]["enum"])

    assert enum_values(gen_props["provenance"]) == set(spec_props["provenance"]["enum"])
    assert enum_values(gen_props["quality"]) == set(spec_props["quality"]["enum"])


def test_normative_example_validates_against_the_model():
    example = json.loads(SPEC_EXAMPLE.read_text(encoding="utf-8"))
    event = TelemetryEvent.model_validate(example)
    assert event.channel == "battery_energy_j"
    assert event.value == 2_400_000.0
    assert event.provenance is Provenance.SIMULATED
    assert event.model_dump(mode="json") == example


def test_unknown_fields_fail_closed():
    example = json.loads(SPEC_EXAMPLE.read_text(encoding="utf-8"))
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TelemetryEvent.model_validate({**example, "surprise_field": 1})


def test_a_probability_needs_an_event_definition_and_a_horizon():
    with pytest.raises(ValidationError, match="checkpoint or a horizon"):
        ProbabilityStatement(event_definition="pass", value=None)


def test_an_unavailable_probability_is_not_zero():
    statement = ProbabilityStatement(
        event_definition="pass_before(checkpoint=attack-exit)",
        checkpoint_id="attack-exit",
    )
    assert statement.value is None
    assert statement.calibration_status.value == "unavailable"


def test_withdraw_advice_is_the_only_action_without_a_plan():
    withdrawn = fx.recommendation().revise(action_code=ActionCode.WITHDRAW_ADVICE, plan_id=None)
    assert withdrawn.plan_id is None
    with pytest.raises(ValidationError, match="must reference its plan"):
        fx.recommendation().revise(plan_id=None)


def test_profile_segments_must_be_contiguous():
    plan = fx.candidate_plan()
    broken = list(plan.profile_segments)
    broken[1] = broken[1].revise(start_progress_m=2_500.0)
    with pytest.raises(ValidationError, match="contiguous"):
        plan.revise(profile_segments=tuple(broken))


def test_unsolicited_execution_is_not_attributed_to_a_recommendation():
    from afterlap_contracts import ExecutionMatch

    unsolicited = fx.execution_event(match=ExecutionMatch.UNSOLICITED)
    assert unsolicited.recommendation_id is None
    with pytest.raises(ValidationError, match="must not be attributed"):
        unsolicited.revise(recommendation_id="rec-001")


def test_reward_manifest_rejects_a_profitable_deliberate_failure():
    from afterlap_contracts.models import RewardManifest

    valid = fx.reward_manifest()
    assert valid.terminal_failure_penalty == 1200.0
    with pytest.raises(ValidationError, match="must exceed the discounted running-cost bound"):
        RewardManifest(
            revision="objective-broken",
            elapsed_second_penalty=1.0,
            instruction_change_penalty=0.1,
            finish_position_penalty=30.0,
            terminal_failure_penalty=100.0,
            potential_reference_time_scale_s=100.0,
            gamma=0.9966722160545233,
            maximum_supported_field_size=20,
            maximum_charged_instruction_changes_per_s=1.0,
        )


def test_promotion_cannot_be_enabled_without_frozen_thresholds():
    from afterlap_contracts.models import PromotionPolicy

    assert PromotionPolicy().enabled is False
    with pytest.raises(ValidationError, match="without frozen thresholds"):
        PromotionPolicy(enabled=True, minimum_benefit=0.5)
