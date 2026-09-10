"""Control-plane behaviour: typed errors, capability honesty and mode enforcement."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from afterlap_api.db import create_all
from afterlap_api.db.models import Manifest, ModelBundle, RuleManifestRow, Session
from afterlap_api.deps import Settings
from afterlap_api.main import create_app
from afterlap_contracts import SessionMode, fixtures as fx


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'api.sqlite3').as_posix()}",
        artifact_root=tmp_path,
        session_runtime_backend="in_process",
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        create_all(app.state.database.engine)
        test_client.app_instance = app  # type: ignore[attr-defined]
        yield test_client


def _seed_session(client, mode: SessionMode = SessionMode.SIMULATION) -> None:
    app = client.app_instance  # type: ignore[attr-defined]
    manifest = fx.session_manifest(mode=mode)
    from afterlap_api.db import transaction

    with transaction(app.state.database.factory) as db:
        db.add(
            Manifest(
                hash=manifest.content_hash(),
                kind="session",
                schema_version=manifest.schema_version,
                payload=manifest.model_dump(mode="json"),
            )
        )
        db.add(
            Session(
                id=manifest.id,
                mode=manifest.mode.value,
                revision=0,
                manifest_hash=manifest.content_hash(),
                status="running",
                session_time_s=12.3,
                last_sequence=100,
                scenario_id=manifest.scenario_id,
                ruleset_hash=manifest.ruleset_hash,
                synthetic=True,
            )
        )


def test_liveness_is_about_the_process_not_the_data(client):
    body = client.get("/api/v1/health/live").json()
    assert body["status"] == "live"


def test_readiness_reports_measured_capabilities(client):
    response = client.get("/api/v1/health/ready")
    body = response.json()
    assert body["status"] in ("ready", "not_ready")
    assert "numerics" in body["detail"]
    assert "solver" in body["detail"]


def test_errors_are_typed_and_never_leak_a_traceback(client):
    response = client.get("/api/v1/sessions/does-not-exist/snapshot")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["retryable"] is False
    assert error["request_id"].startswith("req-")
    body = json.dumps(response.json()).lower()
    assert "traceback" not in body and 'file "' not in body


def test_every_response_carries_its_request_id(client):
    response = client.get("/api/v1/sessions")
    assert response.headers["X-Request-Id"].startswith("req-")


def test_a_mutable_route_requires_an_idempotency_key(client):
    response = client.post(
        "/api/v1/sessions",
        json={"mode": "simulation", "scenario_id": "s", "ruleset_id": "r", "seed": 1},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_malformed_body_reports_field_locations_not_values(client):
    response = client.post(
        "/api/v1/sessions",
        json={"mode": "not-a-mode", "scenario_id": "s", "ruleset_id": "r", "seed": -1},
        headers={"Idempotency-Key": "k"},
    )
    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert "mode" in details["fields"]
    assert "not-a-mode" not in json.dumps(details)


def test_unknown_fields_fail_closed(client):
    response = client.post(
        "/api/v1/sessions",
        json={
            "mode": "simulation",
            "scenario_id": "s",
            "ruleset_id": "r",
            "seed": 1,
            "surprise": True,
        },
        headers={"Idempotency-Key": "k"},
    )
    assert response.status_code == 422


def test_a_missing_capability_is_503_not_a_fabricated_success(client):
    """A capability that is genuinely absent must be reported, not worked around.

    This used to pass because no session factory was attached by default. One
    now is, so the absence has to be created deliberately -- otherwise the test
    asserts a scaffolding gap rather than the behaviour it is named after.
    """
    app = client.app_instance  # type: ignore[attr-defined]
    attached = app.state.session_factory
    app.state.session_factory = None
    try:
        response = client.post(
            "/api/v1/sessions",
            json={"mode": "simulation", "scenario_id": "s", "ruleset_id": "r", "seed": 1},
            headers={"Idempotency-Key": "k"},
        )
    finally:
        app.state.session_factory = attached

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "capability_unavailable"
    assert error["retryable"] is True
    assert error["details"]["capability"] == "session_factory"


def test_an_unknown_scenario_is_refused_explicitly(client):
    """With a factory attached, an unknown scenario is a named refusal.

    Not a default, not a substituted scenario, and not a 500.
    """
    response = client.post(
        "/api/v1/sessions",
        json={"mode": "simulation", "scenario_id": "no-such-scenario", "ruleset_id": "r", "seed": 1},
        headers={"Idempotency-Key": "unknown-scenario"},
    )
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert "no-such-scenario" in json.dumps(error)


def test_a_session_without_a_runtime_reports_unavailable(client):
    _seed_session(client)
    response = client.post(
        f"/api/v1/sessions/{fx.FIXTURE_SESSION_ID}/snapshots",
        json={"label": "before the move"},
        headers={"Idempotency-Key": "snap-1"},
    )
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "capability_unavailable"

    message = error["message"]
    assert "start the session" not in message, (
        "the refusal advised an action that hits the same guard: start, pause, resume, step and "
        "stop all resolve a runtime first, so a session whose runtime is gone cannot be started. "
        f"message: {message}"
    )
    assert "restart" in message, (
        "a detached runtime is what a control-plane restart leaves behind, and the operator has no "
        f"way to tell that from the message: {message}"
    )


@pytest.mark.parametrize("mode", [SessionMode.REPLAY, SessionMode.LIVE_TEAM])
def test_driver_action_is_refused_outside_simulation(client, mode):
    _seed_session(client, mode=mode)
    response = client.post(
        f"/api/v1/sessions/{fx.FIXTURE_SESSION_ID}/simulator/driver-action",
        json={"profile_id": "overtake", "observed_at_s": 13.1, "operator_id": "engineer-1"},
        headers={"Idempotency-Key": "drive-1"},
    )
    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "mode_not_permitted"
    assert error["details"]["mode"] == mode.value


def test_snapshot_never_contains_simulator_truth(client):
    _seed_session(client)
    body = client.get(f"/api/v1/sessions/{fx.FIXTURE_SESSION_ID}/snapshot").json()
    text = json.dumps(body).lower()
    for forbidden in ("worldstate", "world_state", "rng_state", "integrator_state"):
        assert forbidden not in text


def test_snapshot_declares_its_capabilities_and_synthetic_notice(client):
    _seed_session(client)
    body = client.get(f"/api/v1/sessions/{fx.FIXTURE_SESSION_ID}/snapshot").json()
    capabilities = body["capabilities"]
    assert capabilities["rival_energy"] == "unavailable", "rival energy is never claimed available"
    assert any("synthetic" in note.lower() for note in capabilities["notes"])
    assert body["manifest"]["synthetic"] is True


def test_session_listing_is_paginated_and_typed(client):
    _seed_session(client)
    body = client.get("/api/v1/sessions", params={"limit": 1}).json()
    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["synthetic"] is True


def test_ruleset_and_model_reads_return_what_is_loaded(client):
    app = client.app_instance  # type: ignore[attr-defined]
    from afterlap_api.db import transaction

    manifest = fx.rule_manifest()
    with transaction(app.state.database.factory) as db:
        db.add(
            RuleManifestRow(
                hash=manifest.content_hash(),
                ruleset_id=manifest.ruleset_id,
                season_revision=manifest.season_revision,
                synthetic=manifest.synthetic,
                payload=manifest.model_dump(mode="json"),
            )
        )

    body = client.get(f"/api/v1/rulesets/{manifest.ruleset_id}").json()
    assert body["manifest"]["synthetic"] is True
    assert body["manifest"]["unknown_conditions"] == []

    assert client.get("/api/v1/models").json()["models"] == []


def test_an_unapproved_bundle_is_never_listed_as_approved(client):
    app = client.app_instance  # type: ignore[attr-defined]
    from datetime import UTC, datetime

    from afterlap_api.db import transaction
    from afterlap_contracts import SCHEMA_VERSION, ModelManifest

    candidate = ModelManifest(
        schema_version=SCHEMA_VERSION,
        id="candidate-1",
        algorithm="SAC",
        weights_hash="sha256:" + "0" * 64,
        feature_schema_hash="sha256:" + "1" * 64,
        rule_family="synthetic-pack-v1",
        reward_revision="objective-v1",
        created_at=datetime.now(UTC),
    )
    with transaction(app.state.database.factory) as db:
        db.add(
            ModelBundle(
                hash=candidate.content_hash(),
                bundle_id=candidate.id,
                manifest=candidate.model_dump(mode="json"),
                approval_status="unevaluated",
            )
        )

    models = client.get("/api/v1/models").json()["models"]
    assert len(models) == 1
    assert models[0]["approval_status"] == "unevaluated"
    assert client.get("/api/v1/models", params={"approval_status": "approved"}).json()["models"] == []


def test_metrics_separate_planner_time_from_observation_age(client):
    client.get("/api/v1/sessions")
    body = client.get("/metrics").json()
    assert "planner_duration_ms" in body
    assert "observation_age_s" in body
    assert body["planner_duration_ms"]["p95"] is None, "no planner samples yet, so no invented number"
