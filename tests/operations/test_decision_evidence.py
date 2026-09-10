"""What `GET /decisions/{id}` owes the console's decision timeline.

`engineer-console/TECHNICAL_SPEC.md` puts an "immutable decision timeline" in
the lower region of the workspace, and `backend/TECHNICAL_SPEC.md` requires
human and automated changes to be audited distinctly. The console renders that
panel from `DecisionEvidenceResponse.operator_events`.

A browser audit of `fa841e6` found the field declared on the response and never
populated: the route read execution events only, so selecting and marking a
recommendation communicated left the timeline reading "No decision timeline
records yet" while the store held both actions. The evidence was recorded and
then not served.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from afterlap_api.client import TestClient
from afterlap_api.deps import Settings
from afterlap_api.main import create_app

from .conftest import RULE_PACK_ID, SCENARIO_ID, SEED

if TYPE_CHECKING:
    from pathlib import Path

OPERATOR = "console-operator"


def _settings(root: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+pysqlite:///{(root / 'afterlap.sqlite3').as_posix()}",
        artifact_root=root,
        session_runtime_backend="in_process",
    )


def _actionable_session(client: TestClient) -> tuple[str, dict[str, object]]:
    created = client.post(
        "/api/v1/sessions",
        json={
            "mode": "simulation",
            "scenario_id": SCENARIO_ID,
            "ruleset_id": RULE_PACK_ID,
            "seed": SEED,
            "label": "decision evidence drill",
        },
        headers={"Idempotency-Key": "evidence-create", "X-Operator-Id": OPERATOR},
    )
    assert created.status_code == 201, created.text
    session_id: str = created.json()["manifest"]["id"]

    lease = client.post(
        f"/api/v1/sessions/{session_id}/control-lease",
        json={"operator_id": OPERATOR, "ttl_s": 600.0},
        headers={"Idempotency-Key": "evidence-lease", "X-Operator-Id": OPERATOR},
    )
    assert lease.status_code == 200, lease.text

    revision = 0
    for index in range(40):
        step = client.post(
            f"/api/v1/sessions/{session_id}/commands",
            json={
                "kind": "step",
                "expected_revision": revision,
                "operator_id": OPERATOR,
                "step_duration_s": 1.0,
            },
            headers={"Idempotency-Key": f"evidence-step-{index}", "X-Operator-Id": OPERATOR},
        )
        assert step.status_code == 200, step.text
        revision = int(step.json()["revision"])

        candidate = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()["recommendation"]
        if candidate is not None and candidate["action_code"] != "withdraw_advice":
            return session_id, candidate

    raise AssertionError("the shipped scenario never produced an actionable recommendation")


def test_the_decision_record_carries_the_human_actions_taken_on_it(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        session_id, recommendation = _actionable_session(client)
        decision_id = str(recommendation["id"])

        before = client.get(f"/api/v1/decisions/{decision_id}").json()
        assert before["operator_events"] == [], "a decision nobody acted on has no operator events"

        for action, key, reason in (
            ("select", "evidence-select", None),
            ("mark_communicated", "evidence-communicated", None),
        ):
            body: dict[str, object] = {
                "action": action,
                "operator_id": OPERATOR,
                "expected_revision": recommendation["revision"],
            }
            if reason is not None:
                body["reason"] = reason
            response = client.post(
                f"/api/v1/sessions/{session_id}/recommendations/{decision_id}/actions",
                json=body,
                headers={"Idempotency-Key": key, "X-Operator-Id": OPERATOR},
            )
            assert response.status_code == 200, response.text
            recommendation = response.json()["recommendation"]

        evidence = client.get(f"/api/v1/decisions/{decision_id}").json()

    events = evidence["operator_events"]
    assert [event["action"] for event in events] == ["select", "mark_communicated"], (
        f"the decision timeline cannot show what the operator did: {events}"
    )
    assert [event["resulting_status"] for event in events] == ["selected", "communicated"]
    assert all(event["operator_id"] == OPERATOR for event in events)
    assert all(event["recommendation_id"] == decision_id for event in events)
    assert all(event["idempotency_key"] for event in events), (
        "the audit record must carry the key the command was submitted under"
    )
    assert [event["sequence"] for event in events] == sorted(event["sequence"] for event in events), (
        "operator events must be returned in server sequence order"
    )
    assert evidence["execution_events"] == [], "selection is not execution"
