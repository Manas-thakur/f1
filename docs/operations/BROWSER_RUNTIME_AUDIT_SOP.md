# Browser runtime audit and remediation SOP

## 1. Purpose

This procedure defines how the AFTERLAP team audits the complete product in a
real browser, repairs verified defects, validates the result on every supported
platform, measures demo readiness, and integrates the work without disturbing
another team member's checkout.

Use it before a hackathon demonstration, after a large integration pull request,
or whenever the API, session runtime and web application may have stopped
working as one system. The procedure tests the simulated product. It does not
connect to a real Formula 1 car, driver or race-control system.

The detailed audit that established this procedure is
[CLAUDE_BROWSER_AUDIT.md](../handoffs/CLAUDE_BROWSER_AUDIT.md). The presentation
sequence remains in [DEMO_RUNBOOK.md](../demo/DEMO_RUNBOOK.md).

## 2. Required outcome

At completion:

1. A clean checkout of the intended revision runs the API, process-backed
   session runtime, batch worker and web application together.
2. Every product route renders against that live API.
3. A browser can create a simulation session and complete the connected
   engineer-to-driver workflow.
4. Every defect claimed as fixed has a reproduction, a regression check and a
   successful runtime verification.
5. Python, web, browser and portability gates pass without weakening an
   invariant.
6. The audit report distinguishes working capabilities, explicit unavailable
   states and unimplemented capabilities.
7. The demo-readiness score is calculated from evidence and names every
   deduction.
8. The reviewed branch is integrated through a pull request while unrelated
   local work remains untouched.

## 3. Product invariants

Read the repository-root `AGENTS.md` before starting. During audit and repair:

- Keep SI units inside the system. Convert only at the UI boundary.
- Represent an unknown value as `null` with provenance and quality. Never turn
  it into zero.
- Never expose simulator truth through controller or UI contracts.
- Return an explicit unavailable result for an unimplemented capability.
- Keep hard constraints outside RL and independent of operator selection.
- Do not add live RL exploration or silently replace a model.
- Keep the visible illustrative-data notice on browser prototypes.
- Do not invent performance, telemetry, benchmark, training or certification
  claims.
- Do not weaken or delete an invariant test to make a gate pass.
- Do not add source comments; use names, types and existing docstring
  conventions.

## 4. Roles and records

One person is the audit owner. That person owns the clean worktree, runtime
ports, evidence log, final score and pull request. Other agents may inspect or
implement isolated findings, but the audit owner reviews every diff and runs
the final gates.

Record these values at the beginning:

| Record | Required value |
|---|---|
| Base revision | Full commit hash from `origin/main` or the requested branch |
| Audit branch | A dedicated branch, normally `codex/<audit-name>` |
| Worktree | Absolute path outside the team's active checkout |
| Operating system | Name and version |
| Python, uv and Bun | Exact versions |
| Browser | Browser and automation mechanism |
| Database | SQLite or PostgreSQL and its configured location |
| Session backend | `process`, `in_process` or an explicit unavailable state |
| API and web ports | Ports reserved for this audit |

Never record credentials, access tokens, environment-file contents or database
secrets.

## 5. Protect active team work

Inspect the active checkout before doing anything:

```powershell
git status --short --branch
git diff --name-only
git diff --stat
git fetch origin --prune
```

If it contains changes, leave it untouched. Create a dedicated worktree from
the remote revision:

```powershell
git worktree add -b codex/browser-runtime-audit C:\path\to\audit-worktree origin/main
```

POSIX shells use the same Git operation with a POSIX path:

```bash
git worktree add -b codex/browser-runtime-audit /path/to/audit-worktree origin/main
```

Do not copy files from the dirty checkout, reset it, switch its branch or use it
to run the audit. Confirm the new worktree is clean and points at the recorded
base revision:

```bash
git status --short --branch
git rev-parse HEAD
```

## 6. Install and diagnose

Run from the repository root:

```bash
uv sync --frozen --all-packages --group solver --group data --group track-ingestion
bun install --frozen-lockfile
uv run python -m afterlap_core.cli doctor
```

`doctor` must identify the active numerical solver, storage and database state.
Optional `acados`, Torch or learning dependencies may be absent if the audit
does not claim those capabilities. Record them as absent; do not describe an
excluded learning suite as passing.

## 7. Isolate the runtime

Use dedicated loopback ports. The established audit ports are:

| Service | Address |
|---|---|
| Python runtime | `http://127.0.0.1:8125` |
| Next.js public origin | `http://127.0.0.1:5205` |
| Readiness through Next.js | `http://127.0.0.1:5205/api/v1/health/ready` |

Before starting, check whether those ports are already in use.

PowerShell:

```powershell
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object { $_.LocalPort -in 8125, 5205 }
```

POSIX:

```bash
lsof -nP -iTCP:8125 -sTCP:LISTEN
lsof -nP -iTCP:5205 -sTCP:LISTEN
```

Do not stop a process until its owner and checkout are known. Choose different
ports when another team member owns the existing service.

The Compose configuration has fixed project, volume and published-port names.
Do not run it from a second checkout while another AFTERLAP Compose stack is
active. A second invocation can recreate the first checkout's containers. Use
the native runtime below for an isolated audit.

## 8. Start the complete native runtime

Use three terminals from the audit worktree.

### 8.1 PowerShell

Terminal 1, Python runtime and process-backed session:

```powershell
$env:AFTERLAP_ENV = 'development'
uv run python -m afterlap_api.cli serve --host 127.0.0.1 --port 8125
```

Terminal 2, batch worker:

```powershell
uv run python scripts/batch_worker_main.py --poll-interval 2.0
```

Terminal 3, Next.js public origin:

```powershell
$env:AFTERLAP_RUNTIME_URL = 'http://127.0.0.1:8125'
$env:AFTERLAP_AUTOSTART_RUNTIME = '0'
Set-Location apps/web
bunx next dev --hostname 127.0.0.1 --port 5205
```

### 8.2 Bash, zsh or another POSIX shell

Terminal 1:

```bash
AFTERLAP_ENV=development uv run python -m afterlap_api.cli serve \
  --host 127.0.0.1 --port 8125
```

Terminal 2:

```bash
uv run python scripts/batch_worker_main.py --poll-interval 2.0
```

Terminal 3:

```bash
cd apps/web
AFTERLAP_RUNTIME_URL=http://127.0.0.1:8125 AFTERLAP_AUTOSTART_RUNTIME=0 \
  bunx next dev --hostname 127.0.0.1 --port 5205
```

Wait for application startup and verify readiness. A live HTTP process is not
enough; inspect the returned capability states. Browser traffic goes to Next.js
on port 5205. Next.js invokes Python through `python -m afterlap_api.cli`.
Do not point the browser at the Python runtime port.

## 9. Configure the browser audit agent

Start the browser-capable audit agent from the clean worktree. Give it the base
revision, runtime ports, route list, invariants, validation commands and report
path. Require it to verify every claim from runtime evidence and source rather
than trusting status documents.

Monitor a background run without assuming it completed successfully. Steer a
stuck or unsafe approach. Inspect the process before terminating a child
command; stop only the process that belongs to the audit.

Run elevated browser permissions only in a dedicated, reviewed worktree when
the operator has explicitly authorised it. It does not remove the requirement
to protect other checkouts, processes, containers and secrets.

The agent instruction must require these behaviours:

- Use the live API and browser, not fixture-only screenshots.
- Inspect browser console, network traffic and server logs.
- Exercise all routes, responsive states, keyboard navigation and reconnect.
- Reproduce defects before changing code.
- Add meaningful regression checks for behavioural fixes.
- Preserve all repository invariants.
- Run the exact CI commands from `.github/workflows/ci.yml`.
- Write `docs/handoffs/BROWSER_RUNTIME_AUDIT.md` with measured evidence.
- Commit in reviewable units without pushing or merging until reviewed.

If an external session manager such as Herdr is used, control it only from the
environment that owns that session. Otherwise use a dedicated background agent
and record its session identifier.

## 10. Establish the baseline

Before making changes:

1. Record the base commit and clean status.
2. Run the scripted demonstration.
3. Open the engineer console and measure stream behaviour for at least one
   active session.
4. Record request counts, SSE resync count, highest published sequence,
   snapshot `last_sequence`, console errors and unavailable panels.
5. Calculate the baseline readiness score with section 16.

Run the API demonstration through the Next.js origin:

```bash
uv run python scripts/demo.py --base-url http://127.0.0.1:5205
```

An exit code of zero means all 13 scripted steps occurred. It does not prove the
browser workflow, visual layout, reconnection behaviour or accessibility.

## 11. Route coverage

Open every route against the live API. Record whether it renders, what request
it makes, what data or unavailable reason it displays, and any console error.

| Route | Required observation |
|---|---|
| `/` | Landing page and illustrative-data boundary |
| `/simulation-lab` | Product explanation and validation limits |
| `/sessions` | Live list and useful empty state |
| `/lab` | Session-less scenario configuration and session creation |
| `/sessions/:id/engineer` | Recommendation, lifecycle controls and evidence |
| `/sessions/:id/lab` | Run controls, snapshots, branching and jobs |
| `/sessions/:id/replay` | Alignment, panels and explicit seek limitation |
| `/sessions/:id/driver` | Communicated instruction, watchdog and simulator input |
| `/experiments/:id/report` | Report or precise unavailable state |
| `/rulesets/:id` | Manifest, rule coverage and sources by id and hash |
| `/models` | Registered bundles or honest empty state |
| `/settings` | Density and motion preferences |
| Unknown path | Named not-found state |

Test supported widths at 320, 375, 414, 768, 1024, 1440 and 1920 pixels.
Inspect overflow, clipped controls, focus visibility and serious or critical
axe-core findings.

## 12. Connected workflow

Complete this sequence in one browser-created synthetic session:

1. Open `/lab` without an existing session.
2. Select a shipped scenario, ruleset and deterministic seed.
3. Acknowledge synthetic or unresolved inputs when the interface requires it.
4. Create the session and confirm the server-resolved circuit, readiness,
   conditions and hashes.
5. Acquire the control lease.
6. Start the session and step or auto-advance until an actionable
   recommendation appears.
7. Confirm instruction, trigger, end condition, validity window, observation
   cutoff, ruleset, objective, reason codes and admissible profiles.
8. Select the recommendation. Verify that selection creates a decision record
   and does not claim execution.
9. Mark it communicated as a separate operator action.
10. Open the driver display and deliberately execute the displayed profile.
11. Verify the execution event, source, timing, match status and resulting
    recommendation lifecycle.
12. Create a snapshot.
13. Queue a paired experiment from that snapshot and verify the batch worker
    claims and completes it.
14. Open the ruleset through the hash pinned by the session.
15. Create an export through the API and verify returned content, manifest and
    ruleset hashes.

Keep auto-advance running while presenting the driver display. Its watchdog is
supposed to clear an instruction when stream updates stop.

## 13. Fault and recovery checks

Perform these checks without deleting stored evidence:

### Stream disconnect

Stop the API while the engineer console is open. The interface must show
reconnecting, retain only the last server state, and disable time-sensitive
actions with a reason.

### Stream reconnect

Restart the API. A current snapshot cursor must reconnect without an unbounded
snapshot/resync loop. A cursor behind or ahead of the durable store must receive
`resync_required` and converge after a snapshot.

### Runtime restart limitation

Attempting to drive a session created before an API restart currently returns
`503 capability_unavailable`. Record this as an incomplete restoration
capability. Do not relabel the old session as controllable.

### Stale driver data

Stop stepping and verify that the driver watchdog removes the instruction while
retaining aged context with an explicit stale reason.

### Empty and unavailable states

Every missing chart, report, model, telemetry channel or control must name the
missing artefact and reason. It must not show a fabricated trace or zero.

## 14. Defect remediation protocol

For each finding:

1. State the user-visible trigger and impact.
2. Preserve concrete pre-fix evidence: response, request count, sequence set,
   console error or screenshot.
3. Trace the behaviour across UI, API, persistence and runtime boundaries.
4. Identify the invariant that should have prevented it.
5. Add a regression check that fails for the observed behaviour.
6. Implement the smallest complete repair across every affected layer.
7. Run focused tests.
8. Repeat the original browser action against a restarted final runtime.
9. Record before and after evidence.

The September 2026 audit established several patterns that must remain covered:

- Commands that do not publish an envelope must not consume a stream sequence.
- An unpublished operator audit event shares the sequence of its published
  lifecycle transition.
- After restart, an empty in-memory stream buffer compares the client cursor
  with the durable session cursor. It must not accept every cursor.
- Repeated resync at the same cursor is delayed so a future defect cannot create
  a request storm.
- Decision evidence joins operator events with command metadata so the human
  timeline is complete.
- Ruleset identifiers are resolved only from enumerated pack names or their
  hashes. Never concatenate unchecked URL input into a filesystem path.
- Session creation pins the exact rule manifest by hash.
- A clean browser workspace exposes `/lab`, so the first session can be created.
- Long identifiers and route names wrap at narrow widths.

## 15. Verification gates

Run the exact repository gates from the root. Do not substitute a smaller test
selection for the final result.

### Python

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run python scripts/check_no_comments.py
uv run python docs/tools/validate_package.py
uv run python -m afterlap_contracts.schema_export --check
uv run python -m afterlap_core.cli doctor
uv run pytest -q -m "not slow and not torch" --ignore=tests/learning
```

### Web

```bash
bun run lint
bun run typecheck
bun run test
bun run build
bun run test:e2e
```

### Live workflow

```bash
uv run python scripts/demo.py --base-url http://127.0.0.1:5205
```

The build currently warns that the main JavaScript chunk exceeds 500 kB after
minification. Record the warning; a successful build does not remove that
performance concern.

If a browser test fails intermittently, reproduce it in isolation and then run
the full suite again. The completed audit found a pending-state route string
overflowing at 320 px even though an earlier full run passed; the repair made
monospaced identifiers wrap and was followed by all 166 browser tests.

## 16. Demo-readiness score

Score the tested revision out of 100. Do not carry a previous score forward.

| Category | Weight | Full-credit requirement |
|---|---:|---|
| Connected loop in a browser | 25 | Browser-created session completes engineer, driver, snapshot and experiment flow |
| Route and state coverage | 15 | All routes, widths, keyboard and required accessibility states pass |
| Evidence and provenance honesty | 20 | Every claim is traceable and every unavailable value is explicit |
| Runtime robustness | 15 | Reconnect, restart and persistence behaviour are bounded and recoverable |
| Runbook capability completeness | 15 | Planner, telemetry, report, export and replay capabilities required by the runbook are usable |
| Portability and reproducibility | 10 | Supported installation and gates pass on Linux, Windows and macOS |

For each deduction, provide a finding identifier, observed impact and evidence.
The audit of base revision `fa841e6` scored 29/100. The repaired revision merged
through pull request 42 scored 64/100. These values are historical evidence,
not permanent project claims.

## 17. Pull request and integration

Before pushing:

```bash
git status --short --branch
git diff --check
git diff --stat origin/main...HEAD
git log --oneline origin/main..HEAD
```

Review every agent-created commit and remove temporary port or fixture changes
that were used only to conduct the audit. Push the audit branch and create a
pull request whose description includes:

- the user-visible failures and resulting behaviour;
- the live browser flow exercised;
- the exact validation commands and results;
- the readiness score and material remaining limitations;
- a link to the audit report.

Wait for Python, web, Windows portability and macOS portability checks. Merge
only after they all pass and the pull request is mergeable. Merge through the
remote service when the local `main` checkout contains unrelated work; do not
switch, reset or pull that checkout merely to perform the merge.

After merging, verify the pull request state and `origin/main` merge commit.

## 18. Runtime handoff and shutdown

For a live handoff, provide:

- web URL;
- API readiness URL;
- audit worktree and revision;
- current session identifier if one should be reused;
- batch-worker status;
- the known demo choreography risks.

Stop the three native services with `Ctrl+C` in their owning terminals. Confirm
that the reserved ports are no longer listening. Do not delete the SQLite
store, reports, exports or Compose volumes as routine cleanup; they are audit
evidence.

## 19. Current known limitations

As of pull request 42, these remain incomplete and must be stated during a demo:

1. Scenario MPC exists in the codebase but is not wired into live session
   recommendations. The visible recommendation is the fixed-schedule baseline.
2. The stream has no producer for the telemetry and estimate events required to
   populate engineer and replay charts.
3. A session runtime is not restored after an API restart.
4. Experiment report bodies and exports are not usable from the browser.
5. Replay seek and snapshot restore are unavailable.
6. There is no session-wide decision-list route.
7. Authentication and operator roles are not implemented.
8. No trained model bundle is registered or promoted.
9. All 23 circuits are catalogued at `discovered` readiness, but none has the
   compiled geometry required for selection by the simulator.

## 20. Completion checklist

- [ ] Base revision and environment recorded.
- [ ] Active team checkout inspected and left untouched.
- [ ] Clean audit worktree created.
- [ ] Full dependency groups installed.
- [ ] `doctor` output recorded.
- [ ] Isolated API, web and batch worker started.
- [ ] Baseline demo and stream metrics recorded.
- [ ] Every route opened against the live API.
- [ ] All supported widths and keyboard flows checked.
- [ ] Connected engineer-to-driver workflow completed.
- [ ] Disconnect, reconnect, stale and unavailable states checked.
- [ ] Every fixed defect has pre-fix evidence and a regression check.
- [ ] Exact Python gates passed.
- [ ] Exact web and browser gates passed.
- [ ] Live 13-step runbook passed.
- [ ] Readiness score calculated with named deductions.
- [ ] Audit report updated.
- [ ] Pull request reviewed and cross-platform CI passed.
- [ ] Merge verified on `origin/main`.
- [ ] Runtime handoff or controlled shutdown completed.
