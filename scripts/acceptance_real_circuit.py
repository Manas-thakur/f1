"""The real-circuit acceptance run: thirteen claims, on two circuits, end to end.

`docs/specs/17_real_tracks_conditions/AGENT_BRIEF.md` says the work is complete
only when validated packages drive the simulator, and that displaying circuit
names or maps is not enough. This script is the check on that. It runs the
whole chain twice, on two physically different circuits, and prints what it
measured at every point so a reader can disagree with a number rather than
take a claim.

Each point is proved by comparing two runs that differ in exactly one thing,
or by reading a value back out of a place it had to travel through. Nothing
here asserts that code was called; every point ends in a physical or recorded
quantity.

The API section runs the real application in process, so the run needs no
server and no network:

    uv run python scripts/acceptance_real_circuit.py

A circuit whose package is not `geometry_validated` is refused rather than
skipped quietly, because a run that silently covers fewer circuits than it
claims is worse than one that fails.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

CIRCUITS = ("monza", "spa")
CONDITIONS = {"monza": "monza-2025-race", "spa": "spa-2025-race"}
SCENARIOS = {"monza": "monza-real-battle", "spa": "spa-real-battle"}
STATIC_CONDITIONS = "static-reference"
RULESET_ID = "synthetic-pack-v1"
OPERATOR = "acceptance-operator"
SEED = 20260909

DT_S = 0.02
WARMUP_STEPS = 200


class AcceptanceFailure(RuntimeError):
    """A claim did not hold. The message says which number refuted it."""


@dataclass
class Ledger:
    """Records every claim with the evidence that settled it."""

    verbose: bool = True
    circuit: str = ""
    claims: list[dict[str, Any]] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)
    _current: dict[str, Any] = field(default_factory=dict)

    def claim(self, number: int, title: str) -> None:
        self._current = {
            "circuit": self.circuit,
            "claim": number,
            "title": title,
            "evidence": [],
            "held": None,
        }
        self.claims.append(self._current)
        if self.verbose:
            print(f"\n[{self.circuit}] {number:>2}. {title}")

    def note(self, label: str, value: Any) -> Any:
        self._current["evidence"].append({label: value})
        if self.verbose:
            print(f"      {label}: {value}")
        return value

    def hold(self, condition: bool, message: str) -> None:
        if not condition:
            self._current["held"] = False
            if self.verbose:
                print(f"      REFUTED: {message}")
            raise AcceptanceFailure(
                f"[{self.circuit}] claim {self._current['claim']} ({self._current['title']}): {message}"
            )
        self._current["held"] = True

    def fail(self, message: str) -> NoReturn:
        """Refute the current claim. Never returns, so what follows is unreachable."""
        self.hold(False, message)
        raise AcceptanceFailure(message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "claims": self.claims,
            "elapsed_s": round(time.monotonic() - self.started, 3),
            "all_held": all(c["held"] for c in self.claims),
        }


def _run(
    bundle: Any,
    steps: int,
    *,
    seed: int = SEED,
    wake: Any = None,
    action: Any = None,
    sample: Any = None,
) -> Any:
    """Advance a bundle and, optionally, sample state at every step.

    ``sample`` is called with the simulator after each step. Reading the car
    state once at the end instead would report the last step's value as though
    it were the whole run, which is how a bounded quantity can look bounded
    without ever having been measured.
    """
    from afterlap_core.simulation import Simulator
    from afterlap_core.simulation.policies import DriverAction

    simulator = Simulator()
    if wake is None:
        simulator.reset(bundle, seed=seed)
    else:
        simulator.reset(bundle, seed=seed, wake=wake)
    scenario = bundle.scenario
    reports = []
    samples: list[Any] = []
    for _ in range(steps):
        inputs = {car: (action or DriverAction()) for car in scenario.car_ids}
        reports.append(simulator.step(inputs, DT_S))
        if sample is not None:
            samples.append(sample(simulator))
    return simulator, reports, samples


def _speed(snapshot: dict[str, Any]) -> float | None:
    """The ego speed the estimate carries, in metres per second.

    The estimate holds the own car under ``own_car``; a measured channel may be
    a bare number or a value with its own uncertainty, and an unavailable
    channel is null rather than zero.
    """
    own = (snapshot.get("estimate") or {}).get("own_car") or {}
    value = own.get("speed_mps")
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, dict) and isinstance(value.get("value"), int | float):
        return float(value["value"])
    return None


def _progress(snapshot: dict[str, Any]) -> float | None:
    """Distance travelled, which moves even when a speed channel is unavailable."""
    own = (snapshot.get("estimate") or {}).get("own_car") or {}
    value = own.get("progress_m")
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, dict) and isinstance(value.get("value"), int | float):
        return float(value["value"])
    return None


def _instructed_profile(recommendation: dict[str, Any]) -> str:
    """The deployment profile the instruction names, read from its display text.

    ``Recommendation`` carries no profile field: the plan's profile segments are
    not on the wire. The runtime builds the display text as
    ``"<PROFILE> <budget> to <progress> m"``, so the first token is the profile
    the engineer would read aloud, and it is the same string the driver route
    accepts. The action code is a different vocabulary and the route rejects it.
    """
    from afterlap_contracts import DeploymentProfile

    first = str(recommendation.get("display_text", "")).strip().split(" ", 1)[0].lower()
    known = {profile.value for profile in DeploymentProfile}
    if first not in known:
        raise AcceptanceFailure(
            f"could not read a deployment profile from {recommendation.get('display_text')!r}; "
            f"the first token {first!r} is not one of {sorted(known)}"
        )
    return first


def physics_claims(circuit: str, ledger: Ledger) -> dict[str, Any]:
    """Claims 1 to 5: the compiled circuit, its weather, its energy and its traffic."""
    from afterlap_contracts import DeploymentProfile
    from afterlap_core.conditions import environment_for, load_conditions
    from afterlap_core.simulation.config import ScenarioBundle, load_track, resolve_bundle
    from afterlap_core.simulation.policies import DriverAction
    from afterlap_core.simulation.wake import WakeModel
    from afterlap_core.tracks.loader import load_track_package
    from afterlap_core.tracks.package import ReadinessStatus

    measured: dict[str, Any] = {}

    ledger.claim(1, "the compiled geometry loads and carries its own validation evidence")
    package = load_track_package(circuit)
    track = load_track(circuit)
    ledger.note("readiness", package.validation.status.value)
    package_hash = package.package_hash or ""
    ledger.note("package hash", package_hash[:16])
    ledger.note("lap length (m)", round(track.length, 1))
    ledger.note("official length (m)", package.validation.official_length_m)
    ledger.note("length error", round(package.validation.length_error_fraction or -1, 5))
    ledger.note("closure error (m)", f"{package.validation.closure_error_m:.2e}")
    ledger.note("provenance", package.geometry.provenance.value)
    ledger.note("corridor", package.geometry.corridor_quality.value)
    failing = [k for k, v in package.validation.checks.items() if v == "fail"]
    ledger.note("failing checks", failing or "none")
    ledger.hold(
        package.validation.status is ReadinessStatus.GEOMETRY_VALIDATED and not failing,
        f"{circuit} is {package.validation.status.value}, so it cannot drive the simulator",
    )
    ledger.hold(
        track.lateral_geometry_surveyed is False and math.isnan(track.width_at(10.0)),
        "an unsurveyed corridor must report nan width and refuse lateral claims",
    )
    measured["package_hash"] = package_hash
    measured["length_m"] = track.length

    ledger.claim(2, "the recorded weather changes the car's behaviour")
    tape = load_conditions(CONDITIONS[circuit], allow_network=False)
    weathered = resolve_bundle(SCENARIOS[circuit])
    still = weathered.model_copy(
        update={
            "environment": environment_for(load_conditions(STATIC_CONDITIONS, allow_network=False), track),
            "environment_hash": load_conditions(STATIC_CONDITIONS, allow_network=False).content_hash,
        }
    )
    ledger.note("tape", f"{CONDITIONS[circuit]} {tape.content_hash[:19]}")
    ledger.note("samples", len(tape.samples) if hasattr(tape, "samples") else "n/a")
    sim_w, _, _ = _run(weathered, WARMUP_STEPS)
    sim_s, _, _ = _run(still, WARMUP_STEPS)
    ego = weathered.scenario.ego_car_id
    v_w = sim_w.world.cars[ego].speed_mps
    v_s = sim_s.world.cars[ego].speed_mps
    rho_w = weathered.environment.air_density_kgpm3(0.0, 600.0, 1.2)
    rho_s = still.environment.air_density_kgpm3(0.0, 600.0, 1.2)
    ledger.note("air density, tape vs static (kg/m3)", f"{rho_w:.4f} vs {rho_s:.4f}")
    ledger.note("speed after warm-up, tape vs static (m/s)", f"{v_w:.4f} vs {v_s:.4f}")
    ledger.note("bundle hash differs", weathered.bundle_hash != still.bundle_hash)
    ledger.hold(
        v_w != v_s and weathered.bundle_hash != still.bundle_hash,
        "the weather tape left the trajectory and the run identity unchanged",
    )
    measured["conditions_hash"] = tape.content_hash

    ledger.claim(3, "deploying electrical energy costs energy and buys speed")
    push = DriverAction(profile=DeploymentProfile.PUSH, throttle=1.0, brake=0.0)
    hold = DriverAction(profile=DeploymentProfile.NEUTRAL, throttle=1.0, brake=0.0)
    sim_p, _, _ = _run(weathered, 300, action=push)
    sim_n, _, _ = _run(weathered, 300, action=hold)
    v_push = sim_p.world.cars[ego].speed_mps
    v_neutral = sim_n.world.cars[ego].speed_mps
    e_push = sim_p.world.cars[ego].battery_energy_j
    e_neutral = sim_n.world.cars[ego].battery_energy_j
    ledger.note("speed, push vs neutral (m/s)", f"{v_push:.3f} vs {v_neutral:.3f}")
    ledger.note("battery, push vs neutral (MJ)", f"{e_push / 1e6:.4f} vs {e_neutral / 1e6:.4f}")
    ledger.hold(
        v_push > v_neutral and e_push < e_neutral,
        "deploying did not both raise speed and lower stored energy",
    )

    ledger.claim(4, "regeneration under braking is bounded by a declared ceiling")
    brake = DriverAction(profile=DeploymentProfile.HARVEST, throttle=0.0, brake=1.0, harvest_request=1.0)

    def _harvest(simulator: Any) -> tuple[float, float, float]:
        state = simulator.world.cars[ego]
        limits = simulator.electrical_limits(ego)
        mechanical_w = (
            float(state.brake_force_n) * state.speed_mps if hasattr(state, "brake_force_n") else 1.0e9
        )
        ceiling = 0.0 if limits is None else limits.harvest_ceiling_dc_w(state.speed_mps, mechanical_w)
        return state.harvest_power_dc_w, ceiling, state.battery_energy_j

    start_energy = None
    sim_b, _, samples = _run(weathered, 400, action=brake, sample=_harvest)
    harvesting = [(h, c) for h, c, _ in samples if h > 0.0]
    over = [(h, c) for h, c in harvesting if h > c + 1.0]
    peak = max((h for h, _ in harvesting), default=0.0)
    start_energy = weathered.scenario.initial_states[ego].energy_j.value
    gained = sim_b.world.cars[ego].battery_energy_j - start_energy
    ledger.note("steps harvesting", len(harvesting))
    ledger.note("peak harvest (kW)", round(peak / 1000.0, 2))
    ledger.note("ceiling at that step (kW)", round(max((c for _, c in harvesting), default=0.0) / 1000.0, 2))
    ledger.note("steps above ceiling", len(over))
    ledger.note("battery gained (MJ)", round(gained / 1e6, 4))
    ledger.hold(bool(harvesting), "no regeneration occurred at all under full braking")
    ledger.hold(gained > 0.0, "braking did not put any energy back into the battery")
    ledger.hold(
        not over,
        f"{len(over)} steps harvested above the declared ceiling, worst {max(h for h, _ in over):.1f} W"
        if over
        else "",
    )

    ledger.claim(5, "a following car is towed, and no lateral claim is invented")
    closing = weathered.scenario.initial_states.copy()
    rival = next(c for c in weathered.scenario.car_ids if c != ego)
    closing[ego] = closing[ego].model_copy(
        update={
            "progress_m": closing[ego].progress_m.model_copy(
                update={"value": closing[rival].progress_m.value - 12.0}
            )
        }
    )
    tow_bundle = ScenarioBundle(
        scenario=weathered.scenario.model_copy(update={"initial_states": closing, "gap_ahead_s": None}),
        track=weathered.track,
        car_configs=weathered.car_configs,
        environment=weathered.environment,
        environment_hash=weathered.environment_hash,
    )
    _, reports_t, _ = _run(tow_bundle, 900, wake=WakeModel(), action=DriverAction(throttle=1.0, brake=0.0))
    active = [
        r.wake_effects[ego] for r in reports_t if r.wake_effects.get(ego, {}).get("label") != "free_air"
    ]
    ledger.note("steps with an active wake", len(active))
    if active:
        closest = min(active, key=lambda e: e["separation_m"])
        ledger.note("closest separation (m)", round(closest["separation_m"], 1))
        ledger.note("drag multiplier there", round(closest["drag_multiplier"], 4))
        ledger.note("label", closest["label"])
        ledger.note("lateral known", closest["lateral_known"])
        ledger.hold(
            closest["lateral_known"] is False,
            "the model claimed a lateral position on an unsurveyed corridor",
        )
    ledger.hold(bool(active), "the follower never entered the leader's wake over 18 s")
    return measured


def api_claims(circuit: str, ledger: Ledger, measured: dict[str, Any], root: Path) -> None:
    """Claims 6 to 13: the decision chain, the operator, the driver, the record."""
    from afterlap_api.client import TestClient
    from afterlap_api.deps import Settings
    from afterlap_api.main import create_app
    from afterlap_infrastructure.persistence import create_all

    settings = Settings(
        database_url=f"sqlite+pysqlite:///{(root / f'{circuit}.sqlite3').as_posix()}",
        artifact_root=root,
        session_runtime_backend="in_process",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        create_all(app.state.database.engine)

        ledger.claim(6, "a session on this circuit carries the geometry and weather identity")
        created = client.post(
            "/api/v1/sessions",
            json={
                "mode": "simulation",
                "scenario_id": SCENARIOS[circuit],
                "ruleset_id": RULESET_ID,
                "seed": SEED,
                "label": f"acceptance {circuit}",
            },
            headers={"Idempotency-Key": f"acceptance-{circuit}-create"},
        )
        ledger.note("create status", created.status_code)
        ledger.hold(created.status_code == 201, f"session creation failed: {created.text[:300]}")
        body = created.json()
        manifest = body["manifest"]
        session_id = manifest["id"]
        ledger.note("session", session_id)
        ledger.note("track / readiness", f"{manifest['track_id']} / {manifest['track_readiness']}")
        ledger.note("package hash", (manifest["track_package_hash"] or "")[:16])
        conditions_hash = manifest["conditions_hash"] or ""
        ledger.note("conditions", f"{manifest['conditions_id']} {conditions_hash[:19]}")
        ledger.hold(
            manifest["track_package_hash"] == measured["package_hash"],
            "the manifest's package hash is not the hash of the package the physics ran on",
        )
        ledger.hold(
            manifest["conditions_hash"] == measured["conditions_hash"],
            "the manifest's conditions hash is not the tape the physics ran on",
        )
        capabilities = (body.get("snapshot") or {}).get("capabilities") or {}
        ledger.note("track_geometry", capabilities.get("track_geometry"))
        ledger.note("lateral_geometry", capabilities.get("lateral_geometry"))
        ledger.note(
            "corridor note", next((n for n in (capabilities.get("notes") or []) if "corridor" in n), "none")
        )
        ledger.hold(
            capabilities.get("track_geometry") == "available",
            f"validated geometry was not advertised available: {capabilities.get('track_geometry')!r}",
        )
        lateral = capabilities.get("lateral_geometry")
        ledger.hold(
            lateral in {"unavailable", "degraded"},
            f"lateral geometry must not be available on an unsurveyed corridor, it read {lateral!r}",
        )

        ledger.claim(7, "the catalogue reports the same circuit identity the session used")
        listing = client.get("/api/v1/tracks").json()
        row = next(t for t in listing["tracks"] if t["track_id"] == circuit)
        ledger.note("catalogue readiness", row["readiness"])
        ledger.note("catalogue hash", (row.get("package_hash") or "")[:16])
        centreline = client.get(f"/api/v1/tracks/{circuit}/centreline?stride_m=25").json()
        ledger.note("centreline points", centreline["point_count"])
        ledger.note("centreline hash", centreline["package_hash"][:16])
        finite = all(
            math.isfinite(x) and math.isfinite(y)
            for x, y in zip(centreline["x_m"], centreline["y_m"], strict=False)
        )
        ledger.note("all coordinates finite", finite)
        ledger.hold(
            row.get("package_hash") == measured["package_hash"]
            and centreline["package_hash"] == measured["package_hash"],
            "the catalogue reports a different package than the session ran",
        )
        ledger.hold(finite, "the centreline the interface would draw contains a non-finite point")

        ledger.claim(8, "one operator holds the lease, and the session starts")
        lease = client.post(
            f"/api/v1/sessions/{session_id}/control-lease",
            json={"operator_id": OPERATOR, "ttl_s": 3600.0},
            headers={"Idempotency-Key": f"acceptance-{circuit}-lease"},
        )
        ledger.note("lease status", lease.status_code)
        ledger.hold(lease.status_code in (200, 201), f"lease refused: {lease.text[:200]}")
        lease_body = lease.json()["lease"]
        ledger.note("lease holder", lease_body["operator_id"])
        revision = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()["revision"]
        ledger.note("session revision", revision)
        started = client.post(
            f"/api/v1/sessions/{session_id}/commands",
            json={"kind": "start", "expected_revision": revision, "operator_id": OPERATOR},
            headers={"Idempotency-Key": f"acceptance-{circuit}-start"},
        )
        ledger.note("start status", started.status_code)
        ledger.hold(started.status_code == 200, f"start refused: {started.text[:300]}")
        started_body = started.json()
        ledger.note("accepted / status", f"{started_body['accepted']} / {started_body['status']}")
        ledger.hold(started_body["status"] == "running", f"the session did not start: {started_body}")
        revision = started_body["revision"]

        ledger.claim(9, "the engineer receives a checked recommendation on this circuit")
        recommendation = None
        snapshot: dict[str, Any] = {}
        for index in range(90):
            stepped = client.post(
                f"/api/v1/sessions/{session_id}/commands",
                json={
                    "kind": "step",
                    "expected_revision": revision,
                    "operator_id": OPERATOR,
                    "step_duration_s": 1.0,
                },
                headers={"Idempotency-Key": f"acceptance-{circuit}-step-{index}"},
            )
            ledger.hold(stepped.status_code == 200, f"step refused: {stepped.text[:200]}")
            revision = stepped.json()["revision"]
            snapshot = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()
            candidate = snapshot.get("recommendation")
            if candidate and candidate.get("action_code") not in (None, "withdraw_advice"):
                recommendation = candidate
                break
        ledger.note("recommendation present", recommendation is not None)
        if recommendation is None:
            last = (snapshot.get("recommendation") or {}).get("action_code")
            ledger.note("last action code", last)
            ledger.fail("no actionable recommendation was published on a real circuit")
        ledger.note("action", recommendation["action_code"])
        ledger.note("display text", recommendation["display_text"][:80])
        ledger.note("admissible actions", recommendation.get("admissible_actions"))
        ledger.note("learned contribution", recommendation.get("learned_contribution_enabled"))
        ledger.hold(bool(recommendation.get("display_text")), "the recommendation carries no instruction")

        ledger.claim(10, "the independent checker ruled on it, apart from the planner")
        verdict = recommendation.get("constraint_result") or {}
        ledger.note("checker verdict", verdict.get("status", verdict))
        ledger.note("violated constraints", verdict.get("violations") or verdict.get("violated") or "none")
        ledger.note("rule pack hash", (recommendation.get("ruleset_hash") or "")[:16])
        ledger.note("baseline identity", recommendation.get("baseline_identity"))
        ledger.note("reason codes", recommendation.get("reason_codes"))
        ledger.hold(
            bool(verdict),
            "the published instruction carries no independent constraint result at all",
        )
        ledger.hold(
            recommendation.get("learned_contribution_enabled") is False,
            "an untrained actor was reported as contributing to this instruction",
        )
        ledger.hold(
            bool(recommendation.get("ruleset_hash")),
            "the instruction does not name the rule pack it was checked against",
        )

        ledger.claim(11, "selecting is a record, and executing is a separate later event")
        before = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()
        speed_before = _speed(before)
        progress_before = _progress(before)
        profile = _instructed_profile(recommendation)
        ledger.note("instructed profile", profile)
        select = client.post(
            f"/api/v1/sessions/{session_id}/recommendations/{recommendation['id']}/actions",
            json={
                "action": "select",
                "expected_revision": recommendation["revision"],
                "operator_id": OPERATOR,
                "reason": "acceptance run: the instruction the checker admitted",
            },
            headers={"Idempotency-Key": f"acceptance-{circuit}-select"},
        )
        ledger.note("select status", select.status_code)
        ledger.hold(select.status_code == 200, f"selection refused: {select.text[:300]}")
        executed = client.post(
            f"/api/v1/sessions/{session_id}/simulator/driver-action",
            json={
                "profile_id": profile,
                "observed_at_s": before.get("session_time_s", 0.0),
                "recommendation_id": recommendation["id"],
                "operator_id": OPERATOR,
            },
            headers={"Idempotency-Key": f"acceptance-{circuit}-execute"},
        )
        ledger.note("execute status", executed.status_code)
        ledger.hold(executed.status_code in (200, 201), f"execution refused: {executed.text[:300]}")

        ledger.claim(12, "execution moves the telemetry, and the next decision sees the new state")
        revision = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()["revision"]
        for index in range(5):
            stepped = client.post(
                f"/api/v1/sessions/{session_id}/commands",
                json={
                    "kind": "step",
                    "expected_revision": revision,
                    "operator_id": OPERATOR,
                    "step_duration_s": 1.0,
                },
                headers={"Idempotency-Key": f"acceptance-{circuit}-after-{index}"},
            )
            ledger.hold(
                stepped.status_code == 200,
                f"the session refused to advance after execution: {stepped.text[:200]}",
            )
            revision = stepped.json()["revision"]
        after = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()
        speed_after = _speed(after)
        progress_after = _progress(after)
        ledger.note("speed before / after (m/s)", f"{speed_before} / {speed_after}")
        ledger.note("progress before / after (m)", f"{progress_before} / {progress_after}")
        later = after.get("recommendation") or {}
        ledger.note("later recommendation revision", later.get("revision"))
        est_before = (before.get("estimate") or {}).get("revision")
        est_after = (after.get("estimate") or {}).get("revision")
        ledger.note("estimate revision before / after", f"{est_before} / {est_after}")
        moved = (speed_before is not None and speed_after is not None and speed_before != speed_after) or (
            progress_before is not None and progress_after is not None and progress_after > progress_before
        )
        ledger.hold(
            moved,
            "the telemetry did not move after the driver executed the instruction "
            f"(speed {speed_before} -> {speed_after}, progress {progress_before} -> {progress_after})",
        )
        ledger.hold(
            later.get("revision") != recommendation["revision"] or later.get("id") != recommendation["id"],
            "the next decision is the same record, so it cannot have seen the changed state",
        )

        ledger.claim(13, "the run is persisted and exportable with its circuit identity")
        from afterlap_infrastructure.persistence import transaction
        from afterlap_infrastructure.persistence.models import Session as SessionRow

        with transaction(app.state.database.factory) as db:
            row_db = db.get(SessionRow, session_id)
            if row_db is None:
                ledger.fail(f"the session {session_id} was never persisted at all")
            persisted = {
                "track_id": row_db.track_id,
                "track_package_hash": row_db.track_package_hash,
                "conditions_id": row_db.conditions_id,
                "conditions_hash": row_db.conditions_hash,
                "readiness": row_db.track_readiness,
            }
        shown = {k: (v[:16] if k.endswith("hash") and v else v) for k, v in persisted.items()}
        ledger.note("persisted row", shown)
        ledger.hold(
            persisted["track_package_hash"] == measured["package_hash"],
            "the persisted row carries a different package hash than the manifest",
        )
        export = client.post(
            "/api/v1/exports",
            json={"session_id": session_id, "format": "json"},
            headers={"Idempotency-Key": f"acceptance-{circuit}-export"},
        )
        ledger.note("export status", export.status_code)
        ledger.hold(
            export.status_code in (200, 201, 202),
            f"the run could not be exported: {export.text[:200]}",
        )
        exported = export.json()
        ledger.note("export status / synthetic", f"{exported['status']} / {exported['synthetic']}")
        ledger.hold(
            exported["status"] == "completed",
            f"the export did not complete: {exported.get('status')}",
        )
        ledger.hold(
            bool(exported.get("synthetic")),
            "the exported record of a real circuit is not labelled synthetic",
        )
        written = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
        circuit_block = written.get("circuit") or {}
        ledger.note("exported circuit block", circuit_block or "absent")
        ledger.note("exported run label", circuit_block.get("run_label"))
        ledger.hold(
            circuit_block.get("track_package_hash") == measured["package_hash"],
            "the exported record does not carry the package hash the run used",
        )
        ledger.hold(
            circuit_block.get("conditions_hash") == measured["conditions_hash"],
            "the exported record does not carry the conditions tape the run used",
        )
        ledger.hold(
            bool(circuit_block.get("run_label")),
            "the exported record of a real circuit carries no run label",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--circuits", nargs="*", default=list(CIRCUITS))
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--physics-only", action="store_true")
    args = parser.parse_args(argv)

    results: list[dict[str, Any]] = []
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for circuit in args.circuits:
            ledger = Ledger(verbose=not args.quiet, circuit=circuit)
            if not args.quiet:
                print(f"\n{'=' * 72}\nreal-circuit acceptance: {circuit}\n{'=' * 72}")
            try:
                measured = physics_claims(circuit, ledger)
                if not args.physics_only:
                    api_claims(circuit, ledger, measured, root)
            except AcceptanceFailure as failure:
                failures.append(str(failure))
            except Exception as error:
                failures.append(f"[{circuit}] unexpected: {type(error).__name__}: {error}")
            results.append(ledger.as_dict())

    held = sum(1 for r in results for c in r["claims"] if c["held"])
    total = sum(len(r["claims"]) for r in results)
    print(f"\n{'=' * 72}")
    print(f"claims held: {held} of {total} across {len(args.circuits)} circuits")
    for refutation in failures:
        print(f"  REFUTED {refutation}")
    if args.json:
        args.json.write_text(
            json.dumps({"circuits": args.circuits, "results": results, "failures": failures}, indent=2),
            encoding="utf-8",
        )
        print(f"wrote {args.json}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
