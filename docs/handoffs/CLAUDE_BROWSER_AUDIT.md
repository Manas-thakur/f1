# Browser runtime audit

Agent: Claude Opus 5, driving the shipped product in Chrome against a locally
running control plane. Branch `codex/browser-runtime-audit`, from `fa841e6`
("refactor: modular monolith layering and an out-of-process session runtime").
Performed 10 September 2026.

Nothing in this report is taken from an existing status document. Every claim
below is either a runtime observation with the request counts, sequence numbers
or hashes that produced it, a line of source, or a test that fails without a
fix and passes with it. Where a previous document's claim did not reproduce,
the discrepancy is recorded rather than the claim repeated.

---

## 1. Environment

| Item | Value |
|---|---|
| Machine | Windows 11 Home Single Language 10.0.26200, Intel64 Family 6 Model 183 Stepping 1, 24 logical CPUs |
| Working tree | `C:\Users\manas\.codex\worktrees\chrome-audit\f1` (git worktree) |
| Base commit | `fa841e60a922dd29e3b60b0476b31a6ec38e67a5` |
| Python | CPython 3.12.14 via `uv 0.12.10` |
| Bun | 1.3.14 |
| Browser | Google Chrome, driven through the Claude in Chrome extension |
| Store | default local SQLite at `artifacts/afterlap.sqlite3`; no `AFTERLAP_DATABASE_URL` |
| Session runtime | `AFTERLAP_SESSION_RUNTIME` unset, so the `process` backend (out-of-process) |
| Docker | 29.6.2 available; **not used for this audit**, see §1.2 |

### 1.1 Exact commands

Install. The first is the command `README.md` and `CLAUDE.md` document; the
second is what CI actually installs, and the difference matters (§5, F-13):

```
uv sync --frozen --all-packages
uv sync --frozen --all-packages --group solver --group data --group track-ingestion
bun install --frozen-lockfile
```

Run, on isolated ports so nothing collides with another checkout on the same
machine:

```
uv run python -m afterlap_core.cli doctor

AFTERLAP_ENV=development uv run python -m uvicorn afterlap_api.main:app \
    --host 127.0.0.1 --port 8125

uv run python scripts/batch_worker_main.py --poll-interval 2.0

cd apps/web && AFTERLAP_API_ORIGIN=http://127.0.0.1:8125 bunx vite --port 5205 --strictPort
```

`AFTERLAP_API_ORIGIN` did not exist before this audit; the dev server's proxy
target was hard-coded to `127.0.0.1:8000` (F-12). The web app was opened at
`http://localhost:5205` rather than `127.0.0.1:5205`, because Vite binds
`localhost`, which resolves to `::1` first on this host.

Verification commands (all run, all results in §6):

```
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run python scripts/check_no_comments.py
uv run python docs/tools/validate_package.py
uv run python -m afterlap_contracts.schema_export --check
uv run python -m afterlap_core.cli doctor
uv run pytest -m "not slow and not torch" --ignore=tests/learning -q
bun run lint
bun run typecheck
bun run test
bun run build
bun run test:e2e
uv run python scripts/demo.py --base-url http://127.0.0.1:8125
```

### 1.2 Why Docker Compose was not the audit runtime

`infra/docker-compose.yml` uses a fixed project name (`afterlap`), volume
names with explicit `name:` keys, and fixed loopback publishes. A stack from
another checkout was already running on this machine under that name. Bringing
up the compose project from this worktree recreated *those* containers rather
than a separate stack, so the compose path cannot be used to audit one branch
in isolation while another is running. The audit therefore ran the natively
supported path, which `README.md` lists as supported for development, API and
web. The pre-existing stack was left with its volumes intact; its `migrate` job
had exited non-zero after the recreate, and it can be restored with the quick
start in `infra/README.md`.

This is recorded as a portability finding (F-14), not as a compose defect.

### 1.3 Limits of the browser harness

Two environment artefacts affected observation and neither is a product defect.
Both are stated so the evidence below can be read correctly.

* The Chrome window this session drove reported `document.visibilityState:
  "hidden"` throughout, and periodically collapsed to `innerWidth: 0`. At zero
  width `matchMedia('(max-width: 768px)')` matches, so the engineer console
  correctly entered its mobile read-only mode and disabled the operator
  controls. Where that happened, a fresh window was opened (measured
  `innerWidth: 1707`, `devicePixelRatio: 1.5`) and the step repeated.
* A hidden window suspends TanStack Query's `refetchInterval`, so poll-driven
  panels (the experiment job queue, 5 s) did not refresh on their own. Those
  panels were verified by reload instead. Synthetic pointer coordinates were
  also offset by the 1.5 device-pixel ratio in the replacement window;
  interactions were driven through the elements' own click handlers where that
  mattered, which still exercises the real React handler, the real command
  path and the real network request.

---

## 2. Routes and flows actually exercised

Every route in `apps/web/src/app/routes.tsx` was opened against the live
control plane, not a mock.

| Route | Opened | What was confirmed |
|---|---|---|
| `/` | yes | Landing page renders; "Illustrative specimen … authored fixture, not a simulator or model output" is present above every specimen figure; the evidence-boundary section is present |
| `/simulation-lab` | yes | Product page renders; validation-capability table ends with "On-track performance — not established" |
| `/sessions` | yes | Live session list from `GET /sessions` with mode, status, source, scenario, revision, created-at |
| `/lab` | yes | **New in this branch.** The session-less laboratory; scenario panel present, run control correctly absent |
| `/sessions/:id/engineer` | yes | Full decision panel, energy/speed/gap panels, battle view, rival beliefs, decision timeline, circuit identity, corridor, sources and per-channel quality |
| `/sessions/:id/lab` | yes | Circuit catalogue (23 circuits, all `discovered`, all refused for the simulator), run control, snapshot, branch, experiment queue, scenario creation |
| `/sessions/:id/replay` | yes | Alignment control, reference-trace selector, four aligned panels, seek explicitly unavailable |
| `/sessions/:id/driver` | yes | Instruction, energy target, four vehicle channels, corridor notice, simulator profile input |
| `/experiments/:id/report` | yes | Job identity, manifest hash, report hash; report body explicitly unavailable |
| `/rulesets/:id` | yes | Applicable limits, unsupported conditions, 12-row coverage matrix with sources and test ids, pack sources |
| `/models` | yes | Empty with "No model bundle has been registered", promotion explicitly not offered |
| `/settings` | yes | Density and motion preferences, live primitive preview, held for the browser session only |
| `/does-not-exist` | yes | "No such route", names the requested address |

### 2.1 The connected flow, end to end, in the browser

Run on session `ses-e068f7f1a1db4e27`, created **from the browser** at `/lab`:

1. `/lab` → scenario `two-straight-counterattack`, pack `synthetic-pack-v1`,
   seed 42. The panel refused to enable its button until the synthetic and
   unreviewed inputs were acknowledged, and named them: "Rule pack
   synthetic-pack-v1 declares reviewed: false" and "The pack declares
   unresolved conditions (`event_supporting_document_referenced_but_not_resolved`)".
2. Server answered 201 and the panel reported back what the *server* resolved,
   not what it asked for: "The control plane resolved circuit test-loop at
   readiness unavailable, package hash unavailable, conditions none".
3. Lease, start and 26 × step (driven over the API for pacing; the same
   commands were also exercised from the lab's own Run control — pause moved
   the session to `paused` at revision 30, a step while paused advanced to
   revision 31 without resuming, resume returned it to `running`).
4. Engineer console: `NEUTRAL 0.18 MJ to 2019 m`, trigger `begin at 1719 m,
   within 1.5 s`, end condition `hold to 2319 m or until withdrawn`, validity
   `4.0 s remaining (at 30.0 s)`, observation cutoff `25.84 s · 160 ms ago`,
   reasons `baseline_fallback, rival_energy_unknown`, ruleset
   `sha256:0dba4023bba24…` and objective `objective-v1`.
5. **Select** → `POST …/recommendations/rec-d821e70ac89941f9/actions` 200,
   status `selected`, "Server acknowledged select". Execution still
   "not observed" — selection is visibly not actuation.
6. **Mark communicated** → 200, status `communicated`.
7. Decision timeline populated: sequence 49 `select` → `selected`, sequence 50
   `mark_communicated` → `communicated`, each with `console-operator` and the
   idempotency key the command was submitted under. This panel was empty
   before this audit (F-3).
8. Driver display: instruction shown with `Engineer communicated.`, live
   `SPEED 289 km/h`, `STORED ENERGY 0.35 MJ`, `LAP DISTANCE 1622 m`, and
   `BUS POWER not available` / `LATERAL POSITION unavailable` with the
   corridor reason.
9. **Driver profile `neutral`** → execution `exe-drv-afdfb4ede1f2414c`,
   `observed_profile_id: neutral`, `match_status: matched`, `source: simulated`,
   `start_time_s: 26.35`, `delay_from_communication_s: 0.35`, recommendation
   `executing`.
10. Snapshot from the lab → `snap-50cffdb9b82646df · 26.35 s`, hash
    `sha256:0074fad016bb3a37…`.
11. Paired experiment queued from that snapshot → `exp-8de4f70fc0494281`,
    claimed and completed by the batch worker, report hash
    `sha256:cb91cddfa1190f12…` matching `artifacts/reports/exp-8de4f70fc0494281.hash`.
12. Rail → Rules resolved to
    `/rulesets/sha256:0dba4023bba24d47a39f3e383d09e4882df9f16d60bfe408c0c629f19c95d75b`
    — the pack this session pinned — with its full coverage matrix. This link
    was permanently broken before this audit (F-4, F-11).

### 2.2 States, layouts and reconnect

* **Disconnect.** The API was stopped under a live console. Within 8 s the
  stream badge read `reconnecting`, the callout said the stream had dropped and
  that the values shown were the last the server sent, and Select, Mark
  communicated and Reject were all disabled with a reason. No time-sensitive
  advice remained actionable.
* **Reconnect.** The API was restarted. The console returned to `open` with
  `rejected envelopes 0`, `resyncs 0`, `last sequence 54`, and Select
  re-enabled. This is the exact case that produced an unbounded request storm
  before the fix (F-1).
* **Watchdog.** With the session idle between steps the driver display cleared
  its instruction on its own: "STALE / NO LIVE DATA — No stream update inside
  the watchdog window. The instruction was cleared locally", with the vehicle
  context retained and explicitly aged. This is the behaviour
  `driver-display/TECHNICAL_SPEC.md` asks for.
* **Refusals.** Stepping a session whose runtime is gone renders the typed
  error with its request id in the run-control panel rather than failing
  silently. Attempting the same over HTTP returns 503 `capability_unavailable`.
* **Empty states.** Every unpopulated panel named its missing artefact:
  `missing artefact: battery_energy_j telemetry view`, `… operator or execution
  event`, `… rule pack manifest`, `… session manifest`, `… benchmark report
  body`, `… model manifest`. No panel substituted a zero or a placeholder
  trace.
* **Responsive, keyboard and contrast** were exercised through the repository's
  own Playwright suite against the built bundle: 166 tests, all passing —
  overflow at 320/375/414/768/1024/1440/1920 px across 11 routes, axe-core
  with no serious or critical violations, full keyboard traversal of the
  workspace shell, the skip link as first tab stop, visible focus indicators,
  dialog focus trap with Escape and focus restore, and a keyboard chart cursor.
* **Console.** No JavaScript error or unhandled rejection was recorded on any
  route.

---

## 3. Findings, with the evidence that produced them

### F-1 — The engineer console never worked, and hammered the control plane (fixed)

**Severity: demo-breaking.** Opening `/sessions/:id/engineer` left the console
in "Stream connecting" permanently. Select, Mark communicated and Reject stayed
disabled with "The stream is still resynchronising with the server". Every
chart stayed empty. One browser tab produced, in nine minutes:

```
"/api/v1/sessions/ses-81282665023e4000/snapshot 200": 10947
"websocket_resyncs": 10939
```

Two server-side causes, both proven from the store.

*Cause 1 — commands burned stream sequence numbers.*
`POST /sessions/{id}/commands` incremented `Session.last_sequence` without
publishing an envelope at that number. That column is the sequence *allocator*
claimed by `append_event` for every envelope a client can receive. After a
20-step session the published set was

```
1, 3, 5, 7, 9, 11, 13, 14, 16, 17, 19, 20, 22, 23, 25, 26, 28, 29, 31, ...
```

— 54 published events with 29 holes, while `GET /snapshot` advertised
`last_sequence: 84` against a highest published sequence of 83. The frontend
reducer answers a hole by pausing deltas and demanding a snapshot; the snapshot
handed back the same unreachable cursor, so the loop could not terminate.

*Cause 2 — an empty reconnect buffer refused every cursor.*
`StreamChannel.can_replay` returned `after_sequence == 0` when the buffer was
empty, which is the state of every session after a control-plane restart. A raw
WebSocket probe at the cursor the snapshot had just given:

```
REST snapshot last_sequence: 83
frame: resync_required  reason: "cursor older than the retained buffer"
```

**Fix.** A command no longer claims a sequence; the revision advances and the
sequence belongs to the events. The subscription now carries the store's
durable cursor, and an empty channel accepts exactly that cursor — a cursor
below it or above it still resyncs, and both converge because the snapshot that
follows carries that sequence. The client defers its reconnect by the reconnect
delay when a resync returns the cursor it already had, so any future stall
degrades into slow retries instead of a storm.

**After.** Same flow, same session shape: `websocket_resyncs: 0`, 10 snapshot
reads for the whole session, select and mark-communicated both round-trip, zero
requests in an 8 s idle window.

**Tests.** `tests/operations/test_stream_cursor.py` — commands leave no holes;
a client resuming from the advertised cursor is not told to resync and receives
`cursor + 1`; an empty channel accepts the durable cursor and refuses 0, 4,
4096 and 11 against a durable 10; a cursor 500 past the store gets
`resync_required` with reason `cursor ahead of the published stream` over a real
subscription. `apps/web/src/api/stream.test.ts` — a second resync at the same
cursor does not reopen the socket.

The ahead-cursor case matters and is covered deliberately: accepting it would
make the reducer discard every later sequence as already applied, so the client
would go silent with no resync and no error — worse than the loop.

### F-2 — Operator actions punched their own holes (fixed)

`apply_operator_action` records an `operator_action` session event that is
deliberately never published (an invariant test asserts it produces no outbox
row) and it claimed a sequence of its own. Measured after one select and one
mark-communicated: published set complete to 51 with **50 missing**, and
`session.last_sequence` at 52. With F-1's fix alone the console still resynced
about twice a second for the rest of the session.

**Fix.** The audited event shares the sequence of the lifecycle transition it
caused — the same ordered moment — and costs the stream nothing.

**Test.** `tests/operations/test_stream_cursor.py::test_operator_actions_do_not_punch_holes_either`.

### F-3 — The decision timeline was never served (fixed)

`DecisionEvidenceResponse.operator_events` is declared on the response and
`GET /decisions/{id}` never populated it — the route read execution events
only. So the one panel that shows selection and execution as separate human
acts read "No decision timeline records yet" while the store held both:

```
$ curl .../api/v1/decisions/rec-59020347cd1d425a
operator_events: []
```

**Fix.** The route joins the audited session event (what was done, why,
resulting status) with the operator command row (idempotency key, the revision
the operator acted on), which is where `apply_operator_action` deliberately
splits the record.

**Test.** `tests/operations/test_decision_evidence.py`, verified to fail
against the unfixed route with `assert [] == ['select', 'mark_communicated']`.

### F-4 — No session could be created from the browser (fixed)

`GET /rulesets/{id}` answered 404 for every id on a real runtime, because
**nothing in the product ever inserted a `rule_manifest` row** — the only
writer is a test fixture:

```
$ curl .../api/v1/rulesets/synthetic-pack-v1
404 {"code":"not_found","message":"ruleset synthetic-pack-v1 is not loaded"}
$ sqlite3 artifacts/afterlap.sqlite3 "select * from rule_manifest"   →  0 rows
```

The laboratory validates the rule pack id before enabling its create button,
so with the only shipped pack unreadable the button never enabled: "The rule
pack could not be read: the control plane returned an error for this rule pack
id". Combined with F-5 there was no path from a clean install to a first
session in the browser at all.

**Fix.** A session pins the pack it was checked against, stored under the hash
it ran and only when the file still hashes to that value. A pack no session has
used is served from `configs/rules`, which is what the route's contract
describes.

**Also closed: a path traversal.** `load_rule_pack` builds
`configs/rules/<id>.yaml` by concatenation and the id arrives from a URL. Before
the guard, `GET /api/v1/rulesets/..%5Crules%5Csynthetic-pack-v1` returned 200
with the pack read back through the traversal. The id is now resolved only
against the packs `list_rule_packs` enumerates.

**Tests.** `tests/operations/test_ruleset_reads.py` — a shipped pack reads
before any session exists; an unknown id still 404s and names what does
resolve; a session's pinned hash resolves; nine traversal shapes are refused,
three of which return 200 without the guard.

### F-5 — A clean install had no way to reach the panel that creates sessions (fixed)

`/sessions` on an empty store said the simulation lab page describes the
workflow; that page's only call to action linked back to `/sessions`. The panel
that creates a session lives at `/sessions/:id/lab`, which needs a session to
reach.

**Fix.** `SimulationLab` already guarded its session-dependent panels, so it is
mounted at `/lab` as well; the empty state and the product page point there and
the rail offers it while no session is selected. Verified by creating
`ses-e068f7f1a1db4e27` from `/lab` with no session open.

**Tests.** `apps/web/src/app/routes.test.tsx` (route renders; the empty state
links to `/lab`), `apps/web/e2e/accessibility.spec.ts`, and `/lab` added to the
feature-route sweep so it is checked for overflow at seven widths and by axe.

### F-6 — Two states described themselves inaccurately (fixed)

* A session whose runtime is gone refused with "start the session before
  requesting live state". No such action exists: start, pause, resume, step and
  stop all resolve a runtime before dispatching, so the advice sends an
  operator into the same wall. Reproduced by restarting the API under a live
  session and pressing Step.
* The console's reconnect banner said "Waiting for the first snapshot from the
  control plane" while a snapshot was on screen, so a dropped stream looked
  identical to a session that had never loaded.

**Fix.** The refusal says what happened and what does work. The banner
distinguishes a reconnect from a first load.

**Tests.** `tests/api/test_control_plane.py` asserts the refusal does not
advise starting the session and does mention a restart;
`apps/web/src/features/engineer/lifecycle.test.ts` asserts a reconnect does not
claim to be waiting for a first snapshot.

### F-7 — Each disabled button was described by the first one on the page (fixed)

`Button` derived its note id from `rest.id ?? 'button'`, so every button
without an explicit id rendered `id="button-note"`. The decision panel renders
three, so `aria-describedby` on Reject resolved to Select's reason. Observed
directly:

```
[...document.querySelectorAll('[id^="button-note"]')].map(e => e.textContent)
→ ["The stream is still resynchronising with the server.",
   "Communicated is a separate action taken after the server records the selection.",
   "The stream is still resynchronising with the server."]
```

**Fix.** `useId` supplies the fallback. **Test.**
`apps/web/src/components/primitives.test.tsx` renders two disabled buttons and
checks each resolves to its own text.

### F-8 — Replay's only control was unstyled (fixed)

`Restore snapshot` was a bare `<button>` with `class=""`, the only unclassed
control in the workspace, so it fell back to the browser default while every
neighbour used the primitive. It now uses `Button` and carries the reason the
control cannot be offered.

### F-9 — The live planner is the fixed-schedule baseline, not the scenario MPC (not fixed, by choice)

Every recommendation the console displays comes from
`apps/api/afterlap_api/session/baseline_planner.py`, whose own docstring says
"This is deliberately *not* an MPC … the real tactical planner is A06's and the
runtime prefers it when it is available (see `default_planner`)."

`default_planner()` exists, resolves correctly, and **is never called**:

```
$ grep -rn "default_planner()" apps packages workers scripts | grep -v test
apps/api/afterlap_api/session/runtime.py:1516:def default_planner() -> ...

$ uv run python -c "from afterlap_api.session.runtime import default_planner; print(default_planner()[1])"
A06 planner (afterlap_core.planning.plan)
```

`composition.py:108` builds `SessionFactory(recorder_factory=...)` with no
planner, so `planner or BaselinePlanner()` selects the baseline in both the
in-process and out-of-process backends. The consequence is visible in every
published recommendation: `probabilities: []` and `outcomes: []`, so the
inspector's alternative plans, scenario outcomes and predicted-versus-observed
comparison are empty by construction, not by data.

**Not fixed deliberately.** Wiring `default_planner()` in is a one-line change
that would alter every decision the product makes, and the brief for this audit
is to keep existing behaviour. `RELEASE_REPORT.md` records the planner p95 at
827 ms against a 200 ms target, so the change also needs latency evidence
against the runtime's decision deadline before it is safe. It is recorded here
as the highest-value next action, with the exact call site.

**Reading the label honestly.** The console says "Learned contribution:
baseline only (afterlap-baseline-fixed-schedule-1)" and the reason codes carry
`baseline_fallback`. In `planning/scoring.py` that reason means the *learned*
terminal-value model is absent, which is true and separate. Neither the badge
nor the reason says that the *tactical planner* is a heuristic schedule rather
than the MPC of ADR-03. A viewer can reasonably read the badge as being only
about the learned model.

### F-10 — No live telemetry, estimate, execution or rule-context event is ever published (not fixed)

The only envelope types the running product publishes are `snapshot` and
`recommendation_updated`. Measured over a full session:

```
sqlite> select event_type, count(*) from outbox where session_id=? group by event_type;
recommendation_updated | 53
snapshot               |  1
```

and no producer exists in source:

```
$ grep -rn "TELEMETRY_VIEW\|telemetry_view" --include=*.py apps packages workers scripts | grep -v test
(contracts and the hub's lossless set only — no emitter)
```

So the engineer console's energy, speed and gap panels, the replay traces and
the rival-belief history can never populate from the stream. The console's
estimate comes from the REST snapshot instead, which is why the battle view and
channel-quality table *do* show live values. Every affected panel says exactly
this — "The stream publishes this series in a `telemetry_view` event. Nothing
is drawn until one arrives; no placeholder trace is substituted" — so the
product is honest about it; it is an unbuilt capability, not a lie. Not fixed:
emitting downsampled telemetry views with provenance and preserved extrema is a
feature, not a repair.

### F-11 — The rail's Rules entry was permanently dead (fixed)

It linked `/rulesets/current`; no pack is called `current`, so it always landed
on "ruleset current is not loaded". The first fix resolved `current` from the
session in the store, and **that was still wrong**: leaving a session route
calls `detachSession`, which wipes the manifest before the ruleset view renders.
Verified in Chrome — clicking Rules inside a live session still landed on an
empty state. The rail now builds `/rulesets/<ruleset hash>` while the manifest
is still there, which is also a URL that stays meaningful when shared.

### F-12 — The dev server's API target was not configurable (fixed)

`vite.config.ts` hard-coded `http://127.0.0.1:8000` for `/api` and `/ws`, so a
control plane anywhere else could not be driven from the dev server without
editing tracked source. `AFTERLAP_API_ORIGIN` now overrides it; the default is
unchanged.

### F-13 — The documented install leaves the solver absent (not fixed)

`README.md` and `CLAUDE.md` document `uv sync --frozen --all-packages`. CI
installs three more groups. After the documented command:

```
absent    solver           casadi unavailable: No module named 'casadi'
absent    recording        pyarrow is not installed; ... Parquet export is refused
absent    track_ingestion  scipy, pypdf not installed; ...
```

`/health/ready` still answers `200 ready`, correctly — readiness requires
contracts, numerics and storage, and the capability map is published in the
same body. The loop still closes: the demo runbook completed 13/13 with the
solver unavailable. Not fixed because changing the documented install line is a
decision about what the supported baseline install is, not a repair; it is
flagged because a reader following the documented command gets a runtime whose
continuous solver is missing and will not know unless they read `doctor`.

### F-14 — The compose project cannot isolate one checkout (not fixed)

Fixed project name, fixed volume names with explicit `name:` keys, fixed
loopback ports. Two worktrees on one machine cannot each run the stack; the
second recreates the first's containers. See §1.2 for what this cost this audit.
Not fixed: changing the packaging's identity scheme is a packaging decision.

### F-15 — Four places broke the repository's own portability rule (fixed)

`README.md` says not to call `.venv/Scripts/python.exe` from shared scripts or
instructions. The one that mattered is `evaluation/harness.py`, which wrote
that Windows path into the `rerun_command` field of **every benchmark report** —
an evidence artefact whose purpose is that someone else can run it again. Also
`scripts/demo.py`'s docstring, `infra/README.md`'s quick start and a fixture
builder. All now use `uv run python`, and
`tests/operations/test_platform_portability.py` fails on a new one.

### F-16 — Two documented limitations no longer existed, and a performance conclusion no longer reproduced (fixed)

`infra/README.md` listed "the `batch` service's healthcheck is disabled" —
compose probes the worker's own heartbeat, and
`scripts/batch_worker_main.py --healthcheck` answers `batch worker live` — and
"`api.Dockerfile` runs the session runtime in the API process", which `fa841e6`
changed by making `process` the default backend. Both were replaced with the
limitation this audit found instead (F-17).

The same file told readers not to benchmark on the native Windows path, on the
strength of a 77× gap. Re-measured on the same machine on this branch:

| Measurement | Recorded | Re-measured |
|---|---|---|
| Demo runbook, 13 steps | 159.44 s | **4.28 s** and 4.17 s |
| `step` command p50 | 5 905 ms | **61.7 ms** (min 56.7, p95 69.5, max 91.1, n=30) |

The advice is withdrawn, the new numbers sit beside the old rather than
replacing them, the compose column is labelled as no longer contemporaneous,
and no cause is attributed — the out-of-process runtime is the plausible
explanation and was not isolated.

### F-17 — A session runtime is never restored after a restart (not fixed)

A runtime is attached at `POST /sessions` and by nothing else
(`grep -rn "\.attach(" apps packages` → one call site). After any control-plane
restart every existing session is readable and undrivable: `GET /snapshot`
answers 200 with a full recommendation, `POST /commands` answers 503
`capability_unavailable`, and the sessions list still shows `running`.
`backend/TECHNICAL_SPEC.md` asks for restoration "from a consistent
snapshot/log offset". The refusal is now accurate (F-6) and the limitation is
documented in `infra/README.md`; restoring the runtime is unbuilt.

### F-18 — Export is unreachable from the browser (not fixed)

`POST /exports` works — the demo runbook produces
`artifacts/exports/exp-….json` with content, manifest and ruleset hashes — and
`apps/web/src/api/controlPlane.ts:123` has a `createExport` method. **No
component calls it.** `simulation-lab/TECHNICAL_SPEC.md` requires
"Download/export produces a manifest and trajectories, not just a screenshot".
Unlike every other gap, no surface says export is unavailable; the control is
simply absent. Not fixed: adding the panel is feature work, and neither
`POST /exports` nor `GET /exports/{id}` serves the file body, so a button could
only report a server-side path and its hashes.

### F-19 — The experiment report body is unreachable, and the two artefacts do not match (not fixed)

`GET /api/v1/experiments/{id}/report` is not implemented, which the report page
states precisely. Beyond the missing route there is a shape mismatch the page's
own suggested fix would not resolve: the page parses
`{report: BenchmarkReport, report_hash, detail}`, while what the batch worker
writes for these jobs is

```
kind: "afterlap.experiment.branch_comparison/1"
keys: benchmark, completed_units, experiment_manifest_hash, job_id, limitations, ...
```

with no `BenchmarkReport.id`. Serving that file would move the page from "no
route serves the report JSON" to "the body is not a benchmark report bundle
this view can read" — accurate either way, and no better. Converting one
artefact into the other would be inventing a benchmark report from a branch
comparison, which `AGENTS.md` forbids. Recorded as an integration decision, not
repaired. The worker's own bundle is honest about itself, listing
`split=tuning: this is an operator-requested comparison, not a held-out
benchmark` among its limitations.

### F-20 — Minor observations, not fixed

* After an execution the console follows the newest proposal, so the decision
  just executed leaves the screen and there is no route to it. The panel says
  so: "The control plane exposes no session-wide decision list."
* A snapshot read that races the outbox drain can still cost one extra resync,
  because the store's cursor advances when the event row is written and the hub
  learns of it when the publisher drains. It converges on the next drain, and
  the client's backoff bounds it.
* The driver display's watchdog clears the instruction within about two seconds
  of the last step, so a demonstration has to keep auto-advance running or the
  display goes stale while the presenter is talking. Correct behaviour;
  choreography risk.
* `POST /commands` can answer 409 `stale_revision` spontaneously, because a
  guard inside the command transaction can bump the revision between a client's
  snapshot read and its next command. Observed once in 26 steps. The client
  handles it by resyncing; a scripted driver has to retry on
  `details.current_revision`.
* `GET /experiments` omits `report_path` while `GET /experiments/{id}`
  populates it, so the queue table shows "not available" for a report the
  detail route can locate.

---

## 4. What was fixed, and the tests that hold it

| Commit | Fix | Tests |
|---|---|---|
| `5ce0b30` | F-1: commands stop claiming stream sequences; an empty channel stops looping; client backs off | `tests/operations/test_stream_cursor.py`, `apps/web/src/api/stream.test.ts` |
| `182a3fe` | F-2 and the ahead-cursor hazard: operator actions share the transition's sequence; the subscription carries the durable cursor | `tests/operations/test_stream_cursor.py` (8 cases) |
| `49025e9` | F-3: `GET /decisions/{id}` serves the operator actions it already stores | `tests/operations/test_decision_evidence.py` |
| `39dadca` | F-4: rule packs read by id or hash, pinned at session creation, resolved only from the enumerated packs | `tests/operations/test_ruleset_reads.py` (12 cases) |
| `612bf29` | F-5: `/lab` reachable without a session | `routes.test.tsx`, `accessibility.spec.ts`, `featureRoutes.spec.ts` |
| `c3f298c` | F-12: `AFTERLAP_API_ORIGIN` | — (config) |
| `8e2d857`, `3e3cf62` | F-11: Rules resolves to the session's pack hash | `routes.test.tsx` (2 cases) |
| `bac56a7` | F-6: two inaccurate state descriptions | `test_control_plane.py`, `lifecycle.test.ts` |
| `c7befb4` | F-15, F-16: portability rule honoured; two stale limitations replaced | `test_platform_portability.py` |
| `01ea0d9` | F-16: performance conclusion withdrawn with re-measured numbers | — (docs) |
| `f046f6d` | F-7, F-8: unique described-by ids; Replay's control uses the primitive | `primitives.test.tsx` |

No test was weakened. Two existing assertions were updated because the copy
they asserted changed deliberately: the sessions empty-state link text in
`accessibility.spec.ts`, and the reconnect detail in `lifecycle.test.ts` gained
a case rather than losing one. Every new regression test was checked to fail
against the unfixed code where the fix is behavioural (F-3 and F-4's traversal
guard were verified by reverting the fix and observing the failure).

No `WorldState` reaches the API or the UI; the snapshot contract was not
touched. No measurement, benchmark, trained weight or certification claim was
added anywhere. No source comments were added; explanation lives in docstrings,
which is this repository's existing convention.

---

## 5. Gate results

Run on the final tree, in the order CI runs them.

| Gate | Command | Result |
|---|---|---|
| Format | `uv run ruff format --check .` | 319 files already formatted |
| Lint | `uv run ruff check .` | All checks passed |
| Types | `uv run mypy` | no issues in 311 source files |
| Comments | `uv run python scripts/check_no_comments.py` | comment policy: pass |
| Docs package | `uv run python docs/tools/validate_package.py` | PASS |
| Schema drift | `uv run python -m afterlap_contracts.schema_export --check` | generated contracts match the models |
| Doctor | `uv run python -m afterlap_core.cli doctor` | ok for python, contracts, numerics, recording, track_ingestion, solver, storage; absent acados/torch/learning; degraded database (no PostgreSQL configured) |
| Python tests | `uv run pytest -m "not slow and not torch" --ignore=tests/learning -q` | exit 0, ~1198 outcomes, no failures |
| Web lint | `bun run lint` | exit 0 |
| Web types | `bun run typecheck` | exit 0 |
| Web unit | `bun run test` | 25 files, 340 tests passed |
| Web build | `bun run build` | exit 0 |
| Browser | `bun run test:e2e` | 166 passed |
| Demo runbook | `uv run python scripts/demo.py --base-url http://127.0.0.1:8125` | 13/13 steps, exit 0, 4.28 s and 4.17 s |

The `learning` group is excluded exactly as CI excludes it; torch is not
installed here, so no learning test ran and no learning claim is made.

---

## 6. Remaining limitations

### 6.1 Bugs still present

| Id | Bug | Impact |
|---|---|---|
| F-20b | A snapshot read racing the outbox drain costs one extra resync | one extra snapshot fetch; self-correcting |
| F-20d | `POST /commands` can answer 409 `stale_revision` with no operator action in between | a scripted driver must retry on `details.current_revision`; the console resyncs |
| F-20e | `GET /experiments` omits `report_path` that `GET /experiments/{id}` populates | the queue table shows "not available" for a locatable report |

### 6.2 Incomplete capabilities

| Id | Capability | State |
|---|---|---|
| F-9 | Scenario MPC in a live session | implemented in `afterlap_core.planning`, resolvable via `default_planner()`, never wired; every console recommendation is the fixed-schedule baseline, with `probabilities: []` and `outcomes: []` |
| F-10 | `telemetry_view`, `estimate_updated`, `execution_observed`, `rule_context_changed` on the stream | no producer; energy, speed, gap and replay panels cannot populate |
| F-17 | Session-runtime restore after a restart | unbuilt; every pre-restart session is readable and undrivable |
| F-18 | Export from the browser | client method exists, no UI calls it, no route serves the body |
| F-19 | Experiment report body, and one artefact shape | route unimplemented; the written bundle is a branch comparison, not a `BenchmarkReport` |
| — | Replay seek / snapshot restore | no `seek` command and no route lists or restores a snapshot; the UI states this |
| — | Session-wide decision list | no route; the timeline is per-decision and says so |
| — | Authentication and roles | none; commands are sent as `console-operator`, stated in the console footer |
| — | Trained model bundle | none registered; `/models` says so and offers no promotion |
| — | Real circuit geometry for the simulator | all 23 circuits sit at `discovered`, none selectable, each refused with its reason |

### 6.3 Demo risks

1. **The recommendation on screen is a heuristic schedule (F-9).** If anyone
   asks "is that the MPC?", the answer is no, and the UI does not say so
   plainly. Decide the wording before the room asks.
2. **Every chart in the engineer console and replay is empty (F-10).** The
   panels explain why, honestly, but a decision-support demo whose energy and
   gap plots are blank will read as broken unless it is framed first.
3. **Restarting the API kills every open session (F-17).** Do not restart
   anything mid-demo; if it happens, create a new session rather than trying to
   recover the old one.
4. **The driver display goes stale about two seconds after the last step
   (F-20c).** Keep auto-advance running while narrating, or the screen clears
   itself mid-sentence.
5. **The benchmark report cannot be opened in the browser (F-19).** Runbook
   step 8 has to be done from the file on disk.
6. **Export has no button (F-18).** Runbook step 12 has to be shown through
   `scripts/demo.py`.
7. **The compose stack cannot be isolated (F-14).** If another checkout's stack
   is running on the demo machine, bringing this one up will recreate theirs.
8. **The documented install omits the solver (F-13).** Install with the CI
   groups on the demo machine and check `doctor` before the room fills.
9. **Two shipped scenarios exercise degraded observation
   (`loop-no-energy-channel`, `loop-regen-disabled`), but nothing in the UI
   injects staleness on a running session.** Runbook step 7 needs a
   pre-planned scenario switch, not a live toggle.

---

## 7. Demo readiness: 64 / 100

Weighted against what a demonstration of *this* product has to do. Each
deduction names the finding that produced it. The same scoring applied to
`fa841e6` before the fixes gives **29 / 100**; the movement is the fixes in §4,
not a change of method.

| Category | Weight | Score | Deductions |
|---|---|---|---|
| A. Connected loop in a browser | 25 | 19 | −3 driver display self-clears between steps (F-20c); −3 the executed decision leaves the screen with no route back (F-20a) |
| B. Route and state coverage | 15 | 15 | none remaining: 13 routes render, 166 browser tests pass across 7 widths, axe clean, every empty state names its artefact |
| C. Evidence and provenance honesty | 20 | 18 | −2 the report page's suggested fix misdescribes the artefact that exists (F-19) |
| D. Runtime robustness | 15 | 8 | −6 no session-runtime restore (F-17); −1 publisher-lag resync (F-20b) |
| E. Capability completeness against the runbook | 15 | 2 | −6 no telemetry or estimate stream (F-10); −3 no report body (F-19); −2 no export control (F-18); −2 no replay seek |
| F. Portability and reproducibility | 10 | 6 | −3 documented install omits the solver (F-13); −1 compose cannot isolate a checkout (F-14) |
| **Total** | **100** | **64** | |

Before the fixes: A 0 (the console never left "Stream connecting" and no
session could be created from the browser), B 7, C 16, D 1, E 0, F 5 → **29**.

What the score is not saying. It is not a quality judgement on the
architecture, which is unusually careful about provenance — category C is high
because the product refuses to state what it has not measured, everywhere, and
that is the hardest part to retrofit. The two lowest categories are both "built
but not connected": a planner that exists and is not called, and a stream
contract with nine event types of which two are ever published. Neither is a
missing idea; both are wiring, and both are gated on evidence (latency for the
planner, downsampling and provenance for the telemetry views) that this audit
did not have and did not invent.

The single change that would move this score most is F-9 — with a latency
measurement against the decision deadline to justify it.
