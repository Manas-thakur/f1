# A14 — integration patch proposals

A14 owns `infra/`, `scripts/`, `tests/operations/` and its own handoff. Every
change below is outside those paths, so none of it was applied. Each item names
the file, the exact hunk, the drill that proves it is needed, and what happens
if it is not applied.

Five of these correspond to `xfail(strict=True)` tests in `tests/operations/`.
Strict xfail means the suite **fails when the defect is fixed** — so applying a
patch and removing its marker are one commit, and a fix cannot land unnoticed.

| ID | File | Severity | Drill |
|---|---|---|---|
| A14-1 | `session/publisher.py` | high — evidence not delivered | `test_shutdown.py::test_graceful_shutdown_flushes_the_outbox` |
| A14-2 | `routes/sessions.py`, `session/runtime.py` | high — required metrics always empty | `test_health_and_metrics.py::test_metrics_actually_records_planner_duration_and_observation_age` |
| A14-3 | `routes/sessions.py` | high — operator-to-execution delay never measured | observed in `scripts/demo.py` step 9 |
| A14-4 | `routes/health.py` | high — readiness ignores decision capability | `test_health_and_metrics.py::test_readiness_reflects_stale_telemetry` |
| A14-5 | `routes/experiments.py` | medium — disk-full admission | `test_disk_quota.py` |
| A14-7 | `session/degradation.py` | **high — an unapproved model can be enabled** | `test_model_hash.py::test_an_unapproved_bundle_is_never_enabled` |
| A14-8 | `session/factory.py` | **high — the feature-hash check is inert** | `test_model_hash.py::test_a_live_session_checks_the_feature_manifest_hash` |
| A14-9 | `session/runtime.py` | medium — stale telemetry unreachable | `test_health_and_metrics.py::test_the_simulator_source_declares_its_own_delivery_rate_so_it_cannot_report_stale` |
| A14-10 | `workers/session_worker.py` | medium — an out-of-process session persists nothing | `test_worker_restart.py` |
| A14-11 | `packages/contracts/.../planning.py` | low, contract change | `scripts/demo.py` parses `display_text` |

---

## A14-7 — an unapproved model bundle is enabled on manifest agreement alone

**Read this one first.** `AGENTS.md` invariants: *"No live RL exploration,
silent model replacement or automatic promotion."*

`afterlap_api/session/degradation.py::check_model_compatibility` compares the
feature-manifest hash, the rule family, the reward revision and the scenario
family. It never looks at `ModelManifest.approval_status` or at
`promotion_policy.enabled`. A bundle that agrees on all four is returned as
`ModelDecision(enabled=True)` even when its approval status is `unevaluated`.

`LoadedBundle.learned_contribution_enabled` in
`afterlap_core/learning/serving.py` gets this right —

```python
return self.approved and self.promotion_policy.enabled
```

— but the runtime does not take that path: it holds a `ModelManifest`, not a
`LoadedBundle`. So the correct rule exists and is bypassed.

**Verified**: `test_model_hash.py::test_an_unapproved_bundle_is_never_enabled`
constructs a manifest agreeing on every pinned field with
`approval_status=unevaluated`; the current code returns `enabled=True`.

### Patch — `apps/api/afterlap_api/session/degradation.py`

In `check_model_compatibility`, after the four `mismatches` checks and before
the final `return ModelDecision(enabled=True, ...)`:

```python
    if mismatches:
        return _model_mismatch(baseline_identity, tuple(mismatches))

    # Approval is a separate question from compatibility, and it fails
    # closed. A bundle that agrees with every pinned manifest is *loadable*;
    # it is not thereby promoted. AGENTS.md forbids automatic promotion, and
    # `LoadedBundle.learned_contribution_enabled` already encodes the rule
    # (approved AND promotion enabled) for the path that holds a bundle
    # rather than a manifest.
    if bundle.approval_status is not ApprovalStatus.APPROVED:
        return _model_mismatch(
            baseline_identity,
            (
                f"bundle {bundle.id} is {bundle.approval_status.value}, not approved; "
                "a matching manifest is not a promotion",
            ),
        )
    if not bundle.promotion_policy.enabled:
        return _model_mismatch(
            baseline_identity,
            (f"bundle {bundle.id} is approved but its promotion policy is disabled",),
        )

    return ModelDecision(
        enabled=True,
        ...
```

Add `ApprovalStatus` to the `afterlap_contracts` import block at the top of the
module.

Then remove the `xfail` marker from
`tests/operations/test_model_hash.py::test_an_unapproved_bundle_is_never_enabled`.

**If not applied:** the first bundle anyone writes with `write_bundle` and
loads through `SessionFactory(model_bundles=...)` contributes to live
recommendations without ever having been evaluated, and
`Recommendation.learned_contribution_enabled` reports `true` for it.

---

## A14-8 — the session's feature-manifest check never runs

`InProcessSessionRuntime.__init__` takes `expected_feature_hash: str | None =
None` and `SessionFactory.create` never supplies it. `initialise` therefore
calls:

```python
check_model_compatibility(..., expected_feature_hash=self._expected_feature_hash, ...)
```

with `None`, and `check_model_compatibility` skips the comparison entirely when
the expectation is `None`. A bundle trained against a different observation
encoding is accepted.

A08's degradation suite passes because it calls `check_model_compatibility`
directly with an explicit hash. Nothing exercises the wiring.

**Verified**: `test_model_hash.py::test_a_live_session_checks_the_feature_manifest_hash`
creates a real session with a bundle declaring `feature_schema_hash =
sha256:bbbb...` and observes `ModelDecision(enabled=True, detail="bundle
ops-drill-bundle matches the session's feature, rule and reward manifests")`.

### Patch — `apps/api/afterlap_api/session/factory.py`

In `SessionFactory.create`, where the runtime is constructed:

```python
        from afterlap_core.feature_manifest import ENERGY_V1

        runtime = InProcessSessionRuntime(
            bundle=artefacts.bundle,
            pack=artefacts.pack,
            planner=self._planner,
            config=config,
            recorder=recorder,
            model_bundle=artefacts.model,
            objective_version=artefacts.objective_id,
            # The observation encoding this runtime actually feeds the model.
            # Passing None makes the compatibility check skip the comparison,
            # so a bundle trained on a different encoding is accepted.
            expected_feature_hash=ENERGY_V1.content_hash(),
        )
```

Consider additionally making the parameter non-optional on
`InProcessSessionRuntime`, so a future construction site cannot repeat the
omission. That is a wider change and A08 should decide it.

Then remove the `xfail` marker from
`tests/operations/test_model_hash.py::test_a_live_session_checks_the_feature_manifest_hash`.

---

## A14-1 — graceful shutdown does not flush the outbox

`afterlap_api/session/publisher.py`:

```python
    async def stop_running(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        self._task.cancel()
        ...
```

The task is cancelled with no final drain. `run()` drains *then* sleeps, so
anything committed after the last drain and before shutdown keeps
`published_at IS NULL`. In production the window is the 50 ms poll interval;
`14_operations/TECHNICAL_SPEC.md` lists graceful shutdown as an acceptance case
in its own right, and `main.py`'s lifespan calls `stop_running()` on every
clean stop.

**Verified**: `test_shutdown.py::test_graceful_shutdown_flushes_the_outbox`
starts the publisher with a 600 s interval, lets its first pass clear the
backlog, commits two more lifecycle rows, then shuts down — and both rows are
still unpublished. `test_a_final_drain_at_shutdown_does_deliver_everything` is
the same sequence with one extra `drain_once()` and delivers 2 of 2.

### Patch — `apps/api/afterlap_api/session/publisher.py`

```python
    async def stop_running(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        # One last pass. `run()` drains before it sleeps, so a lifecycle change
        # committed after the final poll would otherwise stay undelivered until
        # the process is started again. Delivery is at-least-once and consumers
        # deduplicate on (session_id, sequence), so a repeat is harmless and a
        # loss is not.
        try:
            await self.drain_once()
        except Exception:
            logger.exception("final outbox drain at shutdown failed; rows remain unpublished")
```

Note the ordering: the final drain goes **after** the cancel, not before, so a
hung `drain_once` inside the loop cannot delay shutdown twice.

Then remove the `xfail` marker from
`tests/operations/test_shutdown.py::test_graceful_shutdown_flushes_the_outbox`.

---

## A14-2 — planner duration, observation age and spool depth are never recorded

`RequestMetrics` (in `observability.py`) defines `observe_planner`,
`observe_observation_age` and `spool_depth`. `grep -rn "observe_planner\|
observe_observation_age\|spool_depth" apps/` matches **only the definitions**.
`/metrics` therefore reports the shape the operations specification asks for
with `samples: 0` forever, and spool usage reads `0` even during an outage.

**Verified twice**: `scripts/demo.py` step 13 against a live server after a
complete session reported
`planner_duration_ms {'p50': None, 'p95': None, 'p99': None, 'samples': 0}`;
`test_health_and_metrics.py::test_metrics_actually_records_planner_duration_and_observation_age`
drives three decision cycles through the app and both sample counts stay 0.

`PlanningResult.duration_ms` and `StateEstimate.cutoff_s` already carry
everything needed, so this is wiring, not new measurement.

### Patch 1 — `apps/api/afterlap_api/session/runtime.py`

Expose the recorder's measured persistence status (there is no accessor today):

```python
    @property
    def persistence(self) -> PersistenceStatus:
        """Measured health of this session's lifecycle store."""
        return PersistenceStatus() if self._recorder is None else self._recorder.status()
```

`PersistenceStatus` is already imported in that module.

### Patch 2 — `apps/api/afterlap_api/routes/sessions.py`

In `_remember_state`, which already runs after every `step`:

```python
def _remember_state(request: Request, session_id: str, tick) -> None:  # type: ignore[no-untyped-def]
    """Cache the last observable state so a snapshot request does not re-run physics."""
    store = getattr(request.app.state, "latest_state", None)
    if store is None:
        store = {}
        request.app.state.latest_state = store
    store[session_id] = {"estimate": tick.estimate, "rule_context": tick.rule_context}

    # Operational metrics. Planner time and end-to-end observation age are
    # recorded separately and deliberately: conflating them lets a fast solver
    # hide a stale feed, which 14_operations/TECHNICAL_SPEC.md calls out.
    metrics = getattr(request.app.state, "metrics", None)
    if metrics is None:
        return
    if tick.planning is not None:
        metrics.observe_planner(tick.planning.duration_ms)
    if tick.estimate is not None:
        metrics.observe_observation_age(max(0.0, tick.session_time_s - tick.estimate.cutoff_s))
    runtime = _registry(request).get(session_id)
    persistence = getattr(runtime, "persistence", None)
    if persistence is not None:
        metrics.spool_depth = persistence.spooled
```

Then remove the `xfail` marker from
`tests/operations/test_health_and_metrics.py::test_metrics_actually_records_planner_duration_and_observation_age`.

**Additional metrics still unwired after this patch**, listed so the gap is not
mistaken for closed: ingestion age by channel, clock uncertainty, queue depth,
estimator residuals/coverage, planner candidate and rejection counts,
rule-context unknown counts, recommendation expiry and churn, WebSocket resync
count, database latency, failed-job count and model/version mismatch count.
Every one of them exists as a value somewhere in a tick or a repository row;
none reaches `RequestMetrics`. That is a larger piece of work and belongs with
whoever owns `observability.py`.

---

## A14-3 — operator-to-execution delay is never measured

`ExecutionEvent.delay_from_communication_s` is populated by the runtime from
`self._communicated_at_s[recommendation_id]`, which is written only by
`InProcessSessionRuntime.mark_communicated`. Nothing calls it:
`grep -rn "mark_communicated" apps/api/` matches the definition and nothing
else. The HTTP route `POST /sessions/{id}/recommendations/{rid}/actions` with
`action=mark_communicated` performs the durable lifecycle transition and never
tells the runtime.

**Verified**: `scripts/demo.py` runs select → mark communicated → driver action
through the real API and step 9 reports
`delay from communication (s): None`.

The specification names this metric explicitly ("operator-to-execution delay",
and "Record ingestion-to-display age and human execution delay separately"), so
it is currently unmeasurable through the product's own interface.

### Patch — `apps/api/afterlap_api/routes/sessions.py`

In `act_on_recommendation`, after `apply_operator_action` succeeds:

```python
    outcome = apply_operator_action(...)
    db.flush()

    # The durable transition is the record; the runtime also needs the moment,
    # because that is what `ExecutionEvent.delay_from_communication_s` is
    # measured from. Without this the human execution delay is never
    # observable, and 14_operations/TECHNICAL_SPEC.md asks for it by name.
    if payload.action is OperatorAction.MARK_COMMUNICATED:
        runtime = _registry(request).get(session_id)
        marker = getattr(runtime, "mark_communicated", None)
        if marker is not None:
            marker(recommendation_id, row.session_time_s)
```

`act_on_recommendation` does not currently take `request: Request`; add it to
the signature. Guard with `getattr` because `mark_communicated` is beyond
`SessionRuntimePort` and a future out-of-process proxy may not implement it —
in which case the delay is reported as unknown rather than as zero.

---

## A14-4 — readiness ignores whether a decision can be made

`14_operations/TECHNICAL_SPEC.md`: *"A healthy HTTP server with stale telemetry
is not a ready decision system."*

`routes/health.py::ready` reads only `app.state.capabilities`, captured once by
`run_doctor` during startup. It never re-probes, and nothing about a session —
its observation age, its degradation findings, its `ready` flag — reaches the
endpoint. A process whose every session is withdrawing advice answers 200.

**Verified**: `test_health_and_metrics.py::test_readiness_reflects_stale_telemetry`
attaches a runtime that is genuinely withdrawing advice and `/health/ready`
still answers 200.

### Patch — `apps/api/afterlap_api/routes/health.py`

```python
MAX_DECISION_OBSERVATION_AGE_S = 2.0
"""Above this, the newest observation a decision could use is too old to use."""


@router.get("/health/ready", response_model=HealthResponse)
async def ready(request: Request, response: Response) -> HealthResponse:
    capabilities: dict[str, CapabilityState] = getattr(request.app.state, "capabilities", {})
    detail = {name: state.value for name, state in capabilities.items()}

    missing = [
        name
        for name in REQUIRED_FOR_READINESS
        if capabilities.get(name, CapabilityState.UNAVAILABLE) is CapabilityState.UNAVAILABLE
    ]

    # A process-level probe is necessary and not sufficient. Readiness means a
    # decision can be made *now*, so an attached session that is not ready, or
    # whose newest usable observation is too old, makes the process not ready.
    registry = getattr(request.app.state, "runtimes", None)
    unready: list[str] = []
    if registry is not None:
        for session_id in registry.active_sessions:
            runtime = registry.get(session_id)
            if getattr(runtime, "ready", True) is False:
                unready.append(f"{session_id}: not re-estimated")
                continue
            estimate = getattr(runtime, "last_estimate", None)
            if estimate is None:
                unready.append(f"{session_id}: no estimate")
                continue
            age_s = runtime.session_time_s - estimate.cutoff_s
            if age_s > MAX_DECISION_OBSERVATION_AGE_S:
                unready.append(f"{session_id}: newest observation {age_s:.1f} s old")
    if unready:
        detail["sessions"] = "; ".join(unready)

    if missing or unready:
        response.status_code = 503
        if missing:
            detail["missing"] = ", ".join(missing)
        return HealthResponse(status="not_ready", detail=detail)

    return HealthResponse(status="ready", detail=detail)
```

Then remove the `xfail` marker from
`tests/operations/test_health_and_metrics.py::test_readiness_reflects_stale_telemetry`.

**Coordinator decision needed on one point.** This makes a container
healthcheck fail while any *paused* session exists, because a paused runtime
reports `ready = False`. Two defensible answers: exclude sessions whose
database row is `paused` or `stopped` (needs a database read in a health
route, which is itself a design question), or report paused sessions in
`detail` without failing readiness. `infra/api.Dockerfile`'s healthcheck uses
`/health/ready`, so whichever is chosen changes container restart behaviour.
The patch above takes neither position; it needs one before it lands.

---

## A14-5 — `POST /experiments` admits a job with the artefact root full

`ARCHITECTURE.md`: *"Disk full -> stop experiment jobs first, preserve
operational evidence, then withdraw if necessary."*

`grep -rn "quota" apps/ packages/ workers/` finds nothing. There is no disk
budget anywhere in the application. `scripts/afterlap_ops/quota.py` implements
it and `scripts/batch_worker_main.py` genuinely refuses to claim work under it
(`test_disk_quota.py`), so the *execution* side is guarded. The *admission*
side is not: the route queues the job and it sits there.

### Patch — `apps/api/afterlap_api/routes/experiments.py`

The guard has to live somewhere importable by the application, so the first
step is to move `afterlap_ops/quota.py` into `packages/core/afterlap_core/` (it
has no dependency beyond `os`, `shutil` and `pathlib`). It is offered as
operations code precisely because A14 may not add a `packages/core/` module.

```python
from afterlap_core.quota import ArtifactQuota, QuotaPolicy   # after the move


@router.post("/experiments", response_model=CreateExperimentResponse, status_code=202)
async def create_experiment(...):
    ...
    # Experiment output yields before operational evidence does: a benchmark
    # trajectory is recomputable from a frozen scenario and seed, a decision
    # record is not.
    paths = Paths.default(request.app.state.settings.artifact_root)
    reading = ArtifactQuota(paths.artifacts, QuotaPolicy.from_environment()).read()
    if not reading.accepts_experiment_jobs:
        raise LifecycleError(
            ErrorCode.CAPABILITY_UNAVAILABLE,
            reading.detail,
            verdict=reading.verdict.value,
            used_bytes=reading.used_bytes,
            reclaimable_bytes=reading.reclaimable_bytes,
        )
```

The route already has `request`. `AFTERLAP_EXPERIMENT_QUOTA_BYTES` and
`AFTERLAP_OPERATIONAL_RESERVE_BYTES` are already passed to the `batch` service
by `infra/docker-compose.yml`; add them to `api` too when this lands.

**Also unimplemented, and a separate decision:** the third stage, *"then
withdraw if necessary"*, has no consumer. `QuotaVerdict.WITHDRAW` is produced
and nothing in the session runtime reads it. The natural home is a new
`DegradationRow.DISK_FULL` in `session/degradation.py` whose finding sets
`halts_recommendations=True`, evaluated in `assess()` from a
`QuotaReading` added to `DegradationInputs`. That is a session-runtime change
and belongs to A08.

---

## A14-9 — the simulator source cannot report stale telemetry

`InProcessSessionRuntime.initialise`:

```python
            capability = simulator_session_capability(
                ...
                rate_hz=self._config.observation_rate_hz,
```

The declared rate and the delivered rate are the same number, so however
slowly the simulator is sampled its channels always sit inside one declared
period and always classify `valid`. A08 §9.10 flagged the risk; the
consequence for operations is that "a healthy HTTP server with stale
telemetry" is not a reachable state with this source, so that acceptance case
cannot be demonstrated end-to-end.

The freshness machinery itself is correct: with a 20 Hz expectation and no
delivery, `QualityTracker` classifies `degraded → stale → missing` at 3, 10 and
100 periods of age (asserted in
`test_health_and_metrics.py::test_a_source_that_stops_delivering_is_classified_stale_then_missing`).

### Proposal — `apps/api/afterlap_api/session/runtime.py`

Separate the declaration from the cadence, so a source can be *made* to
under-deliver against what it promised:

```python
@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    ...
    observation_rate_hz: float = 20.0
    declared_observation_rate_hz: float | None = None
    """What the source *promises*. Defaults to `observation_rate_hz`. Setting
    it higher than the delivery rate is how a stale feed is reproduced."""
```

and in `initialise`, `rate_hz=self._config.declared_observation_rate_hz or
self._config.observation_rate_hz`.

With that, an operations drill can declare 20 Hz, deliver 0.05 Hz, and assert
the full chain: channels classified stale → estimate quality degraded →
advice withdrawn → readiness 503 (with A14-4). A08 should confirm the shape.

---

## A14-10 — a spawned session worker persists nothing, and owns a different session id

`workers/session_worker.py::_build_runtime`:

```python
def _build_runtime(config: WorkerConfig) -> Any:
    factory = SessionFactory()
    _, runtime = factory.create(CreateSessionRequest(...))
    return runtime
```

Two consequences, both observed in `test_worker_restart.py`:

1. **No recorder.** `SessionFactory()` has no `recorder_factory`, so an
   out-of-process session writes no decision, no execution event and no
   outcome record. If that process dies, everything it decided is gone. The
   drill has to persist the dead worker's advice itself, rebuilt from its
   snapshot, to have anything to invalidate — and it says so.
2. **A different session id.** The runtime's manifest id is freshly minted by
   the factory, so `snapshot["session_id"]` is `ses-...` while
   `WorkerConfig.session_id` is whatever the control plane passed. Commands
   route by the config id; durable records would carry the manifest id. The
   drill asserts the *observed* inequality with a note to tighten it to
   equality once fixed.

Both are consistent with A08 §9.5 (the `SessionRuntimePort` proxy over the
command queue is not written), so this is documentation of a known incomplete
seam rather than a new finding — but the second one will silently split a
session's records in two the moment the proxy lands, so it is worth fixing
first. `WorkerConfig` would need the manifest, or `CreateSessionRequest` a way
to pin the id; that is A08's and the coordinator's call.

---

## A14-11 — the instructed profile is not on the wire

`Recommendation` carries `display_text`, `trigger`, `end_condition` and
`constraint_result`, but not the profile the instruction asks for: the plan's
`ProfileSegment`s are not published anywhere. `SessionSnapshot` exposes the
estimate, the rule context and the recommendation and nothing else, and
`GET /decisions/{id}` returns the recommendation plus operator and execution
events.

So a client that needs the instructed profile has two options, and the shipped
code uses both: `apps/web`'s driver display offers every profile from
`rule_context.admissible_profiles` and lets the human choose, and
`scripts/demo.py` parses the first token of `display_text` — which works only
because `runtime._display_text` happens to format the profile verb first.
Parsing a human-readable string to recover a machine value is the wrong
mechanism and the demo script says so in a comment.

**Proposal (contract change, coordinator only):** add to `Recommendation`

```python
    instructed_profile_id: DeploymentProfile | None = Field(
        default=None,
        description=(
            "The profile the leading plan segment asks for. None on a "
            "withdrawal. Additive and optional, so this is a minor version "
            "bump under the existing negotiation rules."
        ),
    )
```

populated in `runtime._recommendation_for` from
`plan.profile_segments[0].profile_id`. Then `demo.py`'s `_instructed_profile`
helper and its comment can both be deleted.

---

## Not a patch — the SQLite write contention seen in the drills

Several drills log `sqlalchemy.exc.OperationalError: (sqlite3.OperationalError)
database is locked` from `afterlap.session.publisher` while a session is
stepping. It is handled (the publisher logs and retries on its next pass) and
no evidence is lost, because the outbox row stays unpublished until a drain
succeeds. It is recorded here only so a reviewer seeing it in the logs knows it
is understood: SQLite has one writer, the session recorder and the outbox
publisher are two, and A08 §9.6 already notes that nothing has been run against
PostgreSQL. On PostgreSQL this contention does not arise. It is a reason to run
the compose stack for anything longer than a drill, not a code defect.
