#!/usr/bin/env python
"""The demonstration runbook, as an executable script.

`demo/DEMO_RUNBOOK.md` describes a sequence a person performs in a
browser. This file performs it against a **live API** and prints what it
actually observed at every step. It is the demonstration; a screenshot is not.

    make up
    uv run python scripts/demo.py --base-url http://127.0.0.1:18473

    uv run python scripts/demo.py --base-url http://127.0.0.1:18473 --json report.json

Exit code 0 means every step below genuinely happened. Any step that does not
happen raises :class:`DemoFailure` and the script exits 1 with the observation
that failed. It never prints a success it did not see, and it never falls back
to a fixture.

Steps, and the specification line each one exists to demonstrate:

  1  server liveness and readiness are different questions
  2  create a session from immutable manifests (needs an Idempotency-Key)
  3  one operator holds the control lease
  4  start
  5  step until the planner publishes an actionable, independently checked
     instruction (about t = 26 s of simulated time on the shipped scenario)
  6  select — a human decision record, which is *not* execution
  7  mark communicated — a second, separate action
  8  the driver acts in the simulator, behind a reaction delay
  9  the execution event arrives with its own sequence and match status
 10  snapshot the complete state
 11  branch two treatments from that snapshot, paired on disturbance seeds
 12  export the auditable record with its content hash
 13  metrics: planner duration reported separately from observation age

What this script does **not** claim. It demonstrates that the loop closes on a
synthetic scenario. It is not evidence about physics fidelity, latency
percentiles on any particular hardware, calibration, or comparative
performance; steps 11 and 12 produce a queued job and a record, not a result.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from afterlap_ops.apiclient import ApiClient, ApiError  # noqa: E402

CONSOLE_OPERATOR = "console-operator"
"""The identity the shipped console uses. There is no authentication yet."""

SCENARIO_ID = "two-straight-counterattack"
RULESET_ID = "synthetic-pack-v1"
SEED = 42

MAX_STEPS = 60
STEP_DURATION_S = 1.0

PROFILE_VALUES = ("harvest", "conserve", "neutral", "push", "overtake")


class DemoFailure(AssertionError):
    """A runbook step did not happen. Carries what was observed instead."""


@dataclass
class Runbook:
    """Prints each step's real observations and refuses to continue on failure."""

    client: ApiClient
    verbose: bool = True
    steps: list[dict[str, Any]] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)

    def step(self, number: int, title: str) -> None:
        self._current = {"step": number, "title": title, "observations": [], "at_s": None}
        self.steps.append(self._current)
        if self.verbose:
            print(f"\n--- step {number}: {title}", flush=True)

    def observe(self, label: str, value: Any) -> Any:
        self._current["observations"].append({label: value})
        if self.verbose:
            print(f"    {label}: {value}", flush=True)
        return value

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self._current["failed"] = message
            if self.verbose:
                print(f"    FAILED: {message}", flush=True)
            raise DemoFailure(f"step {self._current['step']} ({self._current['title']}): {message}")

    def done(self) -> None:
        self._current["at_s"] = round(time.monotonic() - self.started, 3)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "afterlap.demo.runbook/1",
            "base_url": self.client.base_url,
            "operator_id": self.client.operator_id,
            "synthetic": True,
            "notice": (
                "Synthetic scenario driven through the live API. Not measured telemetry, not a "
                "calibrated car, and not evidence for latency, fidelity or comparative performance."
            ),
            "elapsed_s": round(time.monotonic() - self.started, 3),
            "steps": self.steps,
        }


def _key(name: str) -> str:
    """A fresh idempotency key. A retry must never be a second decision."""
    return f"demo-{name}-{uuid.uuid4().hex[:12]}"


def _instructed_profile(display_text: str, admissible: list[str]) -> str:
    """Recover the instructed profile from the recommendation.

    `Recommendation` carries no profile field: the plan's `ProfileSegment`s are
    not on the wire (`SessionSnapshot` exposes the estimate, the rule context
    and the recommendation, and nothing else). The runtime's `_display_text`
    builds the string as `"<PROFILE> <budget> to <progress> m"`, so the first
    token is the instructed profile, and it is cross-checked against the rule
    context's admissible set before it is used. This is a real gap in the
    contract, not a convenience — see handoffs/A14.md.
    """
    first = display_text.strip().split(" ", 1)[0].lower()
    if first not in PROFILE_VALUES:
        raise DemoFailure(
            f"could not read an instructed profile from display_text {display_text!r}; "
            f"the first token {first!r} is not one of {PROFILE_VALUES}"
        )
    if admissible and first not in admissible:
        raise DemoFailure(f"the instruction asks for {first!r} but the rule context admits only {admissible}")
    return first


def run(client: ApiClient, *, verbose: bool = True) -> dict[str, Any]:
    book = Runbook(client=client, verbose=verbose)

    book.step(1, "liveness and readiness")
    waited = client.wait_for_live(timeout_s=90.0)
    book.observe("waited for live (s)", round(waited, 3))
    live = client.get("/health/live")
    book.require(live.get("status") == "live", f"/health/live answered {live}")

    try:
        ready = client.get("/health/ready")
        ready_status, ready_code = ready.get("status"), 200
    except ApiError as error:
        ready, ready_status, ready_code = error.body, error.body.get("status"), error.status
    book.observe("/health/ready", f"HTTP {ready_code} status={ready_status}")
    book.observe("measured capabilities", dict((ready.get("detail") or {}).items()))
    book.require(
        ready_status == "ready",
        f"the server is live but not ready ({ready}); a healthy HTTP server is not a decision system",
    )

    version = client.get("/version")
    book.observe(
        "schema / contract revision", f"{version['schema_version']} / {version['contract_revision']}"
    )
    book.done()

    book.step(2, "create a session from immutable manifests")
    created = client.post(
        "/sessions",
        {
            "mode": "simulation",
            "scenario_id": SCENARIO_ID,
            "ruleset_id": RULESET_ID,
            "seed": SEED,
            "label": "operations runbook",
        },
        idempotency_key=_key("create"),
    )
    manifest = created["manifest"]
    session_id = manifest["id"]
    book.observe("session id", session_id)
    book.observe("mode / synthetic", f"{manifest['mode']} / {manifest['synthetic']}")
    book.observe("ruleset hash", manifest["ruleset_hash"])
    book.observe("model hash", manifest["model_hash"])
    book.observe(
        "declared source channels",
        [
            {
                "source": c["source_id"],
                "measured": list(c.get("measured_channels") or ()),
                "limitations": list(c.get("limitations") or ()),
            }
            for c in manifest.get("source_capabilities", [])
        ],
    )
    book.require(manifest["mode"] == "simulation", "the session is not a simulation session")
    book.require(bool(manifest["synthetic"]), "the manifest does not declare itself synthetic")
    revision = created["snapshot"]["revision"]
    book.observe("revision after create", revision)
    book.done()

    book.step(3, "one operator holds the control lease")
    lease = client.post(
        f"/sessions/{session_id}/control-lease",
        {"operator_id": CONSOLE_OPERATOR, "ttl_s": 3600.0},
        idempotency_key=_key("lease"),
    )["lease"]
    book.observe("lease holder", lease["operator_id"])
    book.observe("lease revision / expiry (session s)", f"{lease['revision']} / {lease['expires_at_s']}")
    book.require(lease["operator_id"] == CONSOLE_OPERATOR, "the console did not obtain the lease")

    try:
        client.post(
            f"/sessions/{session_id}/commands",
            {
                "kind": "step",
                "expected_revision": revision,
                "operator_id": "intruder",
                "step_duration_s": 1.0,
            },
            idempotency_key=_key("intruder"),
        )
        book.require(False, "a second operator was allowed to command the session")
    except ApiError as refusal:
        book.observe("second operator refused with", f"HTTP {refusal.status} [{refusal.code}]")
        book.require(refusal.status in (403, 409), f"unexpected refusal status {refusal.status}")
    book.done()

    book.step(4, "start the session")
    started = client.post(
        f"/sessions/{session_id}/commands",
        {"kind": "start", "expected_revision": revision, "operator_id": CONSOLE_OPERATOR},
        idempotency_key=_key("start"),
    )
    book.observe(
        "accepted / status / revision", f"{started['accepted']} / {started['status']} / {started['revision']}"
    )
    book.require(
        bool(started["accepted"]) and started["status"] == "running", f"start was not accepted: {started}"
    )
    revision = started["revision"]
    book.done()

    book.step(5, "step until the planner publishes an actionable, checked instruction")
    recommendation: dict[str, Any] | None = None
    rule_context: dict[str, Any] | None = None
    session_time_s = 0.0
    withdrawals: list[str] = []
    for index in range(MAX_STEPS):
        response = client.post(
            f"/sessions/{session_id}/commands",
            {
                "kind": "step",
                "expected_revision": revision,
                "operator_id": CONSOLE_OPERATOR,
                "step_duration_s": STEP_DURATION_S,
            },
            idempotency_key=_key(f"step-{index}"),
        )
        revision = response["revision"]
        snapshot = client.get(f"/sessions/{session_id}/snapshot")
        session_time_s = snapshot["session_time_s"]
        candidate = snapshot.get("recommendation")
        rule_context = snapshot.get("rule_context")
        if candidate is None:
            continue
        if candidate["action_code"] == "withdraw_advice":
            reason = candidate["display_text"]
            if reason not in withdrawals:
                withdrawals.append(reason)
            continue
        if candidate["constraint_result"]["status"] == "pass":
            recommendation = candidate
            break

    book.observe("steps taken", index + 1)
    book.observe("session time (s)", round(session_time_s, 3))
    book.observe("withdrawal reasons seen on the way", withdrawals)
    book.require(
        recommendation is not None,
        f"no actionable instruction within {MAX_STEPS} steps; last withdrawals: {withdrawals}",
    )
    assert recommendation is not None

    book.observe("recommendation id", recommendation["id"])
    book.observe("instruction", recommendation["display_text"])
    book.observe("action code / status", f"{recommendation['action_code']} / {recommendation['status']}")
    book.observe("end condition", recommendation["end_condition"])
    book.observe(
        "independent check",
        f"{recommendation['constraint_result']['status']} at t="
        f"{recommendation['constraint_result']['checked_at_s']:.2f}s "
        f"against ruleset {recommendation['constraint_result']['ruleset_hash'][:19]}...",
    )
    book.observe(
        "valid window (session s)",
        f"{recommendation['valid_from_s']:.2f} .. {recommendation['expires_at_s']:.2f}",
    )
    book.observe("observation cutoff (s)", round(recommendation["observation_cutoff_s"], 3))
    book.observe("learned contribution enabled", recommendation["learned_contribution_enabled"])
    book.observe("validated baseline in force", recommendation["baseline_identity"])
    book.observe("reason codes", recommendation["reason_codes"])
    admissible = list((rule_context or {}).get("admissible_profiles") or [])
    book.observe("admissible profiles", admissible)
    book.require(
        recommendation["created_at_s"] >= recommendation["observation_cutoff_s"],
        "the recommendation precedes its own observation cutoff",
    )
    book.require(
        not recommendation["learned_contribution_enabled"],
        "a learned contribution is enabled but no approved bundle exists in this release",
    )
    book.done()

    book.step(6, "select — a human decision record, which is not execution")
    selected = client.post(
        f"/sessions/{session_id}/recommendations/{recommendation['id']}/actions",
        {
            "action": "select",
            "expected_revision": recommendation["revision"],
            "operator_id": CONSOLE_OPERATOR,
            "reason": "runbook: attack now and still defend at the next opportunity",
        },
        idempotency_key=_key("select"),
    )
    book.observe("status after select", selected["recommendation"]["status"])
    book.observe("operator event sequence", selected["operator_event"]["sequence"])
    book.observe("recommendation revision", selected["recommendation"]["revision"])
    book.require(
        selected["recommendation"]["status"] == "selected",
        f"select did not move the recommendation to selected: {selected['recommendation']['status']}",
    )
    book.observe(
        "execution observed at this point",
        "no — selection is a decision record, not an actuation",
    )
    book.done()

    book.step(7, "mark communicated — a separate action")
    communicated = client.post(
        f"/sessions/{session_id}/recommendations/{recommendation['id']}/actions",
        {
            "action": "mark_communicated",
            "expected_revision": selected["recommendation"]["revision"],
            "operator_id": CONSOLE_OPERATOR,
            "reason": "runbook: radio call made",
        },
        idempotency_key=_key("communicate"),
    )
    book.observe("status after mark communicated", communicated["recommendation"]["status"])
    book.require(
        communicated["recommendation"]["status"] == "communicated",
        f"mark_communicated left the status at {communicated['recommendation']['status']}",
    )
    book.done()

    book.step(8, "the driver executes deliberately in the simulator")
    profile = _instructed_profile(recommendation["display_text"], admissible)
    book.observe("instructed profile (read from display_text)", profile)
    snapshot = client.get(f"/sessions/{session_id}/snapshot")
    observed_at_s = snapshot["session_time_s"]
    book.observe("driver acts at (session s)", round(observed_at_s, 3))
    action = client.post(
        f"/sessions/{session_id}/simulator/driver-action",
        {
            "profile_id": profile,
            "observed_at_s": observed_at_s,
            "recommendation_id": recommendation["id"],
            "operator_id": CONSOLE_OPERATOR,
        },
        idempotency_key=_key("driver"),
    )
    book.done()

    book.step(9, "the execution event arrives as its own, later event")
    execution = action["execution"]
    book.observe("execution id", execution["id"])
    book.observe("observed profile", execution["observed_profile_id"])
    book.observe("match status", execution["match_status"])
    book.observe("source", execution["source"])
    book.observe("start / end (session s)", f"{execution['start_time_s']:.3f} / {execution['end_time_s']}")
    book.observe("delay from communication (s)", execution["delay_from_communication_s"])
    book.observe("sequence", execution["sequence"])
    book.observe("evidence event ids", len(execution["evidence_event_ids"]))
    book.require(execution["source"] == "simulated", f"execution source is {execution['source']!r}")
    book.require(
        execution["recommendation_id"] == recommendation["id"],
        "the execution was not attributed to the communicated recommendation",
    )
    book.require(
        execution["start_time_s"] > observed_at_s,
        (
            f"the execution starts at {execution['start_time_s']:.3f} s, not after the command at "
            f"{observed_at_s:.3f} s; the driver reaction delay was not modelled"
        ),
    )
    after = action.get("recommendation")
    book.observe("recommendation status after execution", None if after is None else after["status"])
    book.require(
        after is not None and after["status"] == "executing",
        f"the lifecycle did not move to executing: {after}",
    )
    book.done()

    book.step(10, "snapshot the complete state")
    snap = client.post(
        f"/sessions/{session_id}/snapshots",
        {"label": "runbook branch point"},
        idempotency_key=_key("snapshot"),
    )["snapshot"]
    book.observe("snapshot id", snap["snapshot_id"])
    book.observe("snapshot hash", snap["snapshot_hash"])
    book.observe("at session time (s)", round(snap["session_time_s"], 3))
    book.require(snap["snapshot_hash"].startswith("sha256:"), "the snapshot carries no content hash")
    book.done()

    book.step(11, "branch two treatments from that snapshot, paired on seeds")
    experiment = client.post(
        "/experiments",
        {
            "snapshot_id": snap["snapshot_id"],
            "treatments": [
                {
                    "treatment_id": "legal_fixed_schedule",
                    "controller": "legal_fixed_schedule",
                    "description": "reference: deterministic legal profile schedule",
                },
                {
                    "treatment_id": "legal_greedy_attacker",
                    "controller": "legal_greedy_attacker",
                    "description": "reference: myopic legal spender",
                },
            ],
            "seeds": [42, 43, 99],
            "evaluator_version": "evaluator-v1",
            "evaluation_horizon_s": 30.0,
        },
        idempotency_key=_key("experiment"),
    )["job"]
    book.observe("job id", experiment["id"])
    book.observe("status", experiment["status"])
    book.observe("progress", experiment["progress"])
    book.observe("report hash", experiment["report_hash"])
    book.require(
        experiment["status"] == "queued",
        f"the experiment reports {experiment['status']!r}; 202 means queued, never that results exist",
    )
    book.require(
        experiment["report_hash"] is None,
        "a freshly queued job already claims a report; HTTP success is not a result",
    )
    book.observe(
        "what this proves",
        "the branch was accepted and queued. Results require the batch worker to run it.",
    )
    book.observe(
        "seed-level caveat",
        "coordinator decision D-06: no exogenous physical disturbance exists, so seeds drive "
        "sensor noise only and a seed-resampled interval would be falsely tight",
    )
    book.done()

    book.step(12, "export the auditable record")
    export = client.post(
        "/exports",
        {"session_id": session_id, "format": "json"},
        idempotency_key=_key("export"),
    )
    book.observe("export id / status", f"{export['export_id']} / {export['status']}")
    book.observe("path", export["path"])
    book.observe("hashes", export["hashes"])
    book.observe("synthetic", export["synthetic"])
    book.require(export["status"] == "completed", f"the export did not complete: {export}")
    book.require("content" in export["hashes"], "the export carries no content hash")
    book.require(bool(export["synthetic"]), "the export is not labelled synthetic")
    book.done()

    book.step(13, "metrics: planner duration is reported apart from observation age")
    metrics = client.get("/metrics")
    book.observe("uptime (s)", round(metrics["uptime_s"], 1))
    book.observe("planner duration ms", metrics["planner_duration_ms"])
    book.observe("observation age s", metrics["observation_age_s"])
    book.observe("websocket resyncs", metrics["websocket_resyncs"])
    book.observe("spool depth", metrics["spool_depth"])
    book.require(
        "planner_duration_ms" in metrics and "observation_age_s" in metrics,
        "planner duration and observation age are not reported separately",
    )
    book.done()

    if verbose:
        print(
            f"\nrunbook complete: {len(book.steps)} steps, "
            f"{time.monotonic() - book.started:.2f} s wall, session {session_id}",
            flush=True,
        )
    return book.as_dict()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute the AFTERLAP demonstration runbook.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18473")
    parser.add_argument("--operator-id", default=CONSOLE_OPERATOR)
    parser.add_argument("--json", type=Path, default=None, help="Write the observation log here.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    client = ApiClient(base_url=args.base_url, operator_id=args.operator_id)
    try:
        report = run(client, verbose=not args.quiet)
    except (DemoFailure, ApiError, TimeoutError) as failure:
        print(f"\nRUNBOOK FAILED: {failure}", file=sys.stderr, flush=True)
        return 1
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        print(f"wrote {args.json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
