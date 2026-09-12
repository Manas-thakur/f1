from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from afterlap_contracts.requests import (
    AcquireLeaseRequest,
    CreateExperimentRequest,
    CreateExportRequest,
    CreateSessionRequest,
    SessionCommandRequest,
)


def session_body(**changes):
    return dict(
        mode="simulation",
        scenario_id="two-straight-counterattack",
        ruleset_id="synthetic-pack-v1",
        seed=42,
        **changes,
    )


@pytest.mark.parametrize("seed", [True, False, "42", 1.5, -1, 2**32])
def test_seed_rejects_coercion_and_out_of_range_values(seed):
    body = session_body()
    body["seed"] = seed
    with pytest.raises(ValidationError):
        CreateSessionRequest.model_validate_json(json.dumps(body))


@pytest.mark.parametrize("identifier", ["", " ", "../escape", "a/b", "a\\b", "a" * 129, "a\nother"])
@pytest.mark.parametrize("field", ["scenario_id", "ruleset_id", "model_bundle_id"])
def test_identifiers_reject_invalid_formats_and_lengths(field, identifier):
    body = session_body()
    body[field] = identifier
    with pytest.raises(ValidationError):
        CreateSessionRequest.model_validate(body)


@pytest.mark.parametrize("duration", [float("inf"), float("nan"), -1, 0, 60.01, "1", True])
def test_step_duration_is_finite_strict_and_bounded(duration):
    with pytest.raises(ValidationError):
        SessionCommandRequest(kind="step", expected_revision=0, operator_id="op", step_duration_s=duration)


@pytest.mark.parametrize("revision", [True, "0", -1, 0.5])
def test_revision_is_an_integer_without_coercion(revision):
    with pytest.raises(ValidationError):
        AcquireLeaseRequest(operator_id="op", expected_lease_revision=revision)


@pytest.mark.parametrize(
    "change",
    [
        {"seeds": [-1]},
        {"seeds": [True]},
        {"seeds": [1, 1]},
        {"seeds": list(range(65))},
        {"evaluation_horizon_s": float("inf")},
        {"evaluation_horizon_s": 3601},
        {"treatments": [{"treatment_id": "same", "controller": "baseline"}] * 2},
        {"treatments": [{"treatment_id": f"t{i}", "controller": "baseline"} for i in range(17)]},
    ],
)
def test_experiments_reject_ambiguous_or_unbounded_work(change):
    body = {
        "snapshot_id": "snap-1",
        "treatments": [{"treatment_id": "reference", "controller": "baseline"}],
        "seeds": [42],
        "evaluator_version": "v1",
        "evaluation_horizon_s": 20,
    }
    body.update(change)
    with pytest.raises(ValidationError):
        CreateExperimentRequest.model_validate(body)


def test_export_range_is_ordered_at_the_contract_boundary():
    with pytest.raises(ValidationError, match="ends before"):
        CreateExportRequest(session_id="s", format="json", start_session_time_s=5, end_session_time_s=1)


def test_valid_boundary_values_round_trip_through_json():
    request = CreateSessionRequest.model_validate({**session_body(label="x" * 120), "seed": 2**32 - 1})
    assert CreateSessionRequest.model_validate_json(request.model_dump_json()) == request
    step = SessionCommandRequest(kind="step", expected_revision=0, operator_id="op", step_duration_s=60)
    assert step.step_duration_s == 60
