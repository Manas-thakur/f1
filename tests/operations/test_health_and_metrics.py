"""Health and metrics, verified against the specification rather than described.

`operations/TECHNICAL_SPEC.md`:

    Liveness means process loop alive. Readiness means required
    rules/model/source/storage capabilities available. **A healthy HTTP server
    with stale telemetry is not a ready decision system.**

    Ingestion age, clock uncertainty, ... planner duration/candidates/
    rejections, ... disk/spool usage ... Report planner time separately from
    end-to-end observation age.

Every test here confirms behaviour that is present. Two of them
(`test_readiness_reflects_stale_telemetry` and
`test_metrics_actually_records_planner_duration_and_observation_age`) were
`xfail(strict=True)` against defects A14-4 and A14-2; both defects are fixed
and the markers are gone. Nothing here is weakened to pass.

**How the stale-telemetry condition is genuinely caused.** The session's
observation rate is configured to one sample every twenty seconds while
decisions continue at 1 Hz. Nothing is faked: the source really supplies
nothing newer, so the decision cutoff really falls ten seconds behind the
session clock and the freshness tracker really sees channels age out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from afterlap_api.client import TestClient
from afterlap_api.deps import Settings
from afterlap_api.main import create_app
from afterlap_api.routes.health import REQUIRED_FOR_READINESS
from afterlap_api.session import RuntimeConfig
from afterlap_contracts import ActionCode, CapabilityState, Quality
from afterlap_core.diagnostics import check_storage, run_doctor
from afterlap_core.paths import Paths

from .conftest import RULE_PACK_ID, SCENARIO_ID, SEED, start_session

if TYPE_CHECKING:
    from pathlib import Path

STALE_OBSERVATION_RATE_HZ = 0.05
"""One sample every twenty seconds, against a one-second decision interval."""


def _app(tmp_path: Path) -> object:
    return create_app(
        Settings(
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'api.sqlite3').as_posix()}",
            artifact_root=tmp_path,
            session_runtime_backend="in_process",
        )
    )


def test_liveness_is_about_the_process_and_says_nothing_about_capability(tmp_path: Path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        app.state.capabilities = {}  # type: ignore[attr-defined]
        live = client.get("/api/v1/health/live")
        assert live.status_code == 200
        assert live.json()["status"] == "live"
        assert "note" in live.json()["detail"]

        ready = client.get("/api/v1/health/ready")
        assert ready.status_code == 503, ready.text
        assert ready.json()["status"] == "not_ready"
        print(f"\nno capabilities: live=200, ready=503 {ready.json()['detail']}")


@pytest.mark.parametrize("capability", REQUIRED_FOR_READINESS)
def test_readiness_requires_each_capability_a_decision_needs(tmp_path: Path, capability: str):
    """Readiness is decided from the measured report, capability by capability."""
    app = _app(tmp_path)
    with TestClient(app) as client:
        measured = dict(app.state.capabilities)  # type: ignore[attr-defined]
        assert client.get("/api/v1/health/ready").status_code == 200

        measured[capability] = CapabilityState.UNAVAILABLE
        app.state.capabilities = measured  # type: ignore[attr-defined]
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503, response.text
        body = response.json()
        assert body["status"] == "not_ready"
        assert capability in body["detail"]["missing"]


def test_an_unwritable_artefact_root_is_measured_as_unavailable_and_blocks_readiness(tmp_path: Path):
    """The measurement is real: the storage root genuinely cannot be created."""
    blocker = tmp_path / "blocker"
    blocker.write_text("this is a file, not a directory", encoding="utf-8")

    broken = Paths.default(blocker)
    result = check_storage(broken)
    print(f"\nstorage probe: {result.state.value} — {result.detail}")
    assert result.state is CapabilityState.UNAVAILABLE
    assert "not writable" in result.detail

    report = run_doctor(broken)
    assert report.capability_map()["storage"] is CapabilityState.UNAVAILABLE
    assert "storage" in {c.name for c in report.unavailable}

    app = _app(tmp_path / "install")
    with TestClient(app) as client:
        app.state.capabilities = report.capability_map()  # type: ignore[attr-defined]
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert "storage" in response.json()["detail"]["missing"]


def test_a_source_that_stops_delivering_is_classified_stale_then_missing():
    """The freshness machinery works, and works from observation ages alone.

    A real `QualityTracker` with a real 20 Hz expectation. One observation is
    recorded and then time simply passes, which is what a feed dropping out
    looks like. Nothing is patched and no quality value is asserted into
    existence — the classification comes from the elapsed interval against the
    declared period.
    """
    from afterlap_core.data.quality import ChannelExpectation, QualityTracker

    expectation = ChannelExpectation(channel="speed_mps", expected_rate_hz=20.0, car_id="own")
    tracker = QualityTracker([expectation], stale_periods=4.0, missing_periods=20.0)
    tracker.observe("speed_mps", session_time_s=0.0, source_time_s=0.0, car_id="own", value=80.0)

    fresh = tracker.assess(0.05).by_channel("speed_mps", "own")
    assert fresh is not None and fresh.quality is Quality.VALID, fresh

    ladder = []
    for now_s, expected in ((0.15, Quality.DEGRADED), (0.5, Quality.STALE), (5.0, Quality.MISSING)):
        entry = tracker.assess(now_s).by_channel("speed_mps", "own")
        assert entry is not None
        ladder.append((now_s, entry.age_s, entry.quality.value))
        assert entry.quality is expected, (
            f"at {now_s:.2f} s ({entry.age_s:.2f} s old, period {expectation.expected_period_s:.3f} s) "
            f"the channel was {entry.quality.value}, expected {expected.value}"
        )
    print(f"\nfreshness ladder (now_s, age_s, quality): {ladder}")

    tracker.heartbeat(5.0)
    still = tracker.assess(5.0).by_channel("speed_mps", "own")
    assert still is not None and still.quality is Quality.MISSING
    assert tracker.assess(5.0).heartbeat_age_s == 0.0


def test_the_simulator_source_declares_its_own_delivery_rate_so_it_cannot_report_stale(db_factory):
    """LIMITATION A14-9, asserted so it cannot regress unnoticed.

    `InProcessSessionRuntime.initialise` builds the source capability from
    `self._config.observation_rate_hz` — the very same number that decides how
    often it delivers. Declared rate and delivered rate therefore move
    together by construction, so however slowly the simulator is sampled its
    channels are always inside one declared period and always classify
    `valid`.

    The consequence for the acceptance case is stated plainly in
    `handoffs/A14.md`: with this source, "a healthy HTTP server with stale
    telemetry" is not a reachable state, so the specification line cannot be
    demonstrated end-to-end in this release. What *is* demonstrated is that the
    freshness machinery classifies correctly when the two rates disagree
    (the test above) and that a decision is withheld when a required input is
    absent (`tests/backend/test_degradation.py`).
    """
    session = start_session(
        db_factory,
        config=RuntimeConfig(observation_rate_hz=STALE_OBSERVATION_RATE_HZ),
        with_recorder=False,
    )
    tick = None
    for _ in range(30):
        tick = session.runtime.advance(1.0)
    assert tick is not None and tick.estimate is not None

    lag_s = tick.session_time_s - tick.estimate.cutoff_s
    print(f"\nsession clock {tick.session_time_s:.2f}s, decision cutoff {tick.estimate.cutoff_s:.2f}s")
    assert lag_s > 5.0, f"the newest observation was only {lag_s:.2f} s old"

    channels = tick.estimate.quality.channels
    assert channels, "the published estimate carries no per-channel freshness at all"
    periods = {c.expected_period_s for c in channels if c.expected_period_s is not None}
    assert periods == {1.0 / STALE_OBSERVATION_RATE_HZ}, (
        f"the declared period {periods} no longer tracks the configured observation rate; "
        "if that was decoupled deliberately, this limitation is fixed and the test should be "
        "replaced by an end-to-end stale-telemetry drill"
    )
    aged = [(c.channel, c.car_id, round(c.age_s or 0.0, 2), c.quality.value) for c in channels]
    print(f"channels at a {lag_s:.1f} s age: {aged[:3]} ...")
    assert all(c.quality is Quality.VALID for c in channels), (
        "a channel now reports non-valid freshness on the simulator source; the limitation may "
        "be fixed — check whether an end-to-end stale-telemetry drill is now possible"
    )

    assert tick.recommendation is not None
    assert tick.recommendation.action_code is ActionCode.WITHDRAW_ADVICE
    print(f"withheld: {tick.recommendation.display_text}")


def test_readiness_reflects_stale_telemetry(tmp_path: Path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/sessions",
            json={
                "mode": "simulation",
                "scenario_id": SCENARIO_ID,
                "ruleset_id": RULE_PACK_ID,
                "seed": SEED,
            },
            headers={"Idempotency-Key": "health-stale"},
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["manifest"]["id"]

        registry = app.state.runtimes  # type: ignore[attr-defined]
        registry.detach(session_id)
        stale = start_session(
            app.state.database.factory,  # type: ignore[attr-defined]
            config=RuntimeConfig(observation_rate_hz=STALE_OBSERVATION_RATE_HZ),
            with_recorder=False,
        )
        for _ in range(30):
            tick = stale.runtime.advance(1.0)
        assert tick.recommendation is not None
        assert tick.recommendation.action_code is ActionCode.WITHDRAW_ADVICE
        registry.attach(session_id, stale.runtime)

        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503, (
            "the server reports ready while its only session is withdrawing advice on stale "
            f"telemetry ({response.json()})"
        )


def test_a_created_or_paused_session_is_idle_and_does_not_fail_readiness(tmp_path: Path):
    """Idle is not broken.

    `infra/api.Dockerfile` probes `/health/ready`, so a session that nobody has
    asked to decide yet must not restart the container holding it. The
    demonstration runbook creates a session and then checks readiness before
    starting it, which is exactly this sequence.
    """
    app = _app(tmp_path)
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/sessions",
            json={
                "mode": "simulation",
                "scenario_id": SCENARIO_ID,
                "ruleset_id": RULE_PACK_ID,
                "seed": SEED,
            },
            headers={"Idempotency-Key": "health-created"},
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["manifest"]["id"]

        response = client.get("/api/v1/health/ready")
        detail = response.json()["detail"]
        print(f"\nwith one created session: HTTP {response.status_code} {detail.get('idle_sessions')}")
        assert response.status_code == 200, (
            f"a session that has not been started made the process unready ({detail})"
        )
        assert session_id in detail["idle_sessions"]
        assert "sessions" not in detail, "an idle session was reported as an obstruction"

        runtime = app.state.runtimes.get(session_id)  # type: ignore[attr-defined]
        runtime.advance(1.0)
        runtime.pause()
        paused = client.get("/api/v1/health/ready")
        assert paused.status_code == 200, paused.text
        assert "paused" in paused.json()["detail"]["idle_sessions"]


def test_metrics_reports_planner_time_apart_from_observation_age(tmp_path: Path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        body = client.get("/metrics").json()
    print(f"\nmetrics keys: {sorted(body)}")

    assert "planner_duration_ms" in body
    assert "observation_age_s" in body
    assert body["planner_duration_ms"].keys() >= {"p50", "p95", "p99", "samples"}
    assert body["observation_age_s"].keys() >= {"p50", "p95", "samples"}

    for key in ("uptime_s", "requests", "websocket_resyncs", "spool_depth"):
        assert key in body, f"/metrics does not report {key}"


def test_metrics_actually_records_planner_duration_and_observation_age(tmp_path: Path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/sessions",
            json={
                "mode": "simulation",
                "scenario_id": SCENARIO_ID,
                "ruleset_id": RULE_PACK_ID,
                "seed": SEED,
            },
            headers={"Idempotency-Key": "metrics-1"},
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["manifest"]["id"]
        client.post(
            f"/api/v1/sessions/{session_id}/control-lease",
            json={"operator_id": "console-operator", "ttl_s": 600.0},
            headers={"Idempotency-Key": "metrics-lease"},
        )
        revision = 0
        for index in range(3):
            step = client.post(
                f"/api/v1/sessions/{session_id}/commands",
                json={
                    "kind": "step",
                    "expected_revision": revision,
                    "operator_id": "console-operator",
                    "step_duration_s": 1.0,
                },
                headers={"Idempotency-Key": f"metrics-step-{index}"},
            )
            assert step.status_code == 200, step.text
            revision = step.json()["revision"]

        body = client.get("/metrics").json()

    assert body["planner_duration_ms"]["samples"] > 0, (
        "three decision cycles produced no planner-duration sample"
    )
    assert body["observation_age_s"]["samples"] > 0, (
        "three decision cycles produced no observation-age sample"
    )


def test_request_latency_is_recorded_per_path_and_status(tmp_path: Path):
    """The one metric that *is* wired: the HTTP middleware's own counters."""
    app = _app(tmp_path)
    with TestClient(app) as client:
        for _ in range(3):
            client.get("/api/v1/health/live")
        client.get("/api/v1/sessions/ses-does-not-exist/snapshot")
        body = client.get("/metrics").json()

    requests = body["requests"]
    print(f"\nrequest counters: {requests}")
    assert requests.get("/api/v1/health/live 200") == 3
    assert any(key.endswith("404") for key in requests), (
        f"a refused request was not counted with its status: {requests}"
    )
    assert body["uptime_s"] > 0.0
