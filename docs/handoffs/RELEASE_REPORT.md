# AFTERLAP release report

Coordinator's assessment, 8 September 2026. Every figure here was produced by a
command run in this repository on the hardware named below. Where something was
not measured, it says so; where a target was missed, it says the measured value.

**Read this first: the product does not meet its current specification.** Two
things are missing, one of which is a whole required module. Both are named in
[§2](#2-what-is-not-built) before anything else.

---

## 1. What the product does

A clean local installation runs a versioned synthetic scenario end to end.
Verified by hand against a live server from an empty artefact root, and by
`scripts/demo.py` through nginx under Compose:

| Step | Observed |
|---|---|
| Session created | real content hashes for track, cars, ruleset and objective |
| Declared capability | `speed_mps`, `progress_m`, `lap_distance_m`, `battery_temperature_k`, `gap_ahead_s`, `battery_energy_j` — and **no `gap_behind_s`**, because nothing is behind the ego car in this scenario |
| Advice while eligibility unknown | **withdrawn**: *"No advice: independent check returned unknown"* |
| Actionable instruction at t = 26 s | `NEUTRAL 0.18 MJ to 2019 m`, trigger *begin at 1719 m within 1.5 s*, end *hold to 2319 m*, **7 independent checks pass** |
| Learned contribution | `false`, baseline `afterlap-baseline-fixed-schedule-1` named |
| Select | status `selected`, **0 execution events** |
| Mark communicated | status `communicated` |
| Simulator driver action | status `executing`, 1 execution event, `profile=neutral`, `match=matched`, `start=26.35 s` |
| Second operator's select | **refused** — lease held elsewhere; the conflict refreshes evidence rather than retrying |
| Snapshot / export | `sha256:eab94853…`, export completed, `synthetic: true` |

Deployment changes physical motion and energy, not text: from one scenario,
`push` reached 908.23 m with 0.294 MJ remaining against `conserve` at 887.01 m
with 2.233 MJ. After a real driver execution, telemetry diverges from a
counterfactual branch restored from a pre-execution snapshot — **1.98 MJ against
2.66 MJ, with a different next recommendation**.

`rival_energy` reads `unavailable` throughout. No screen displays a fabricated
number.

---

## 2. What is not built

### 2.1 A16 — real circuits and race conditions (**required, absent**)

`BUILD_WITH_AGENTS.md` was revised during this build to add boundary 4:

> Read `tracks` and dispatch A16. Real-circuit support
> requires compiled metric geometry, event overlays and condition validation. A
> circuit name or image over synthetic dynamics does not satisfy it.

The dispatch table now names A16 in waves 1, 2 and 3. `docs/tracks/`
holds 397 lines of specification plus a track-package schema, a 2026 season
registry and a Monza example.

**None of it is implemented.** There is no track-package pipeline, no compiled
metric geometry, no event overlay, no condition model and no circuit registry.
The two tracks that exist — `test-loop` and `test-oval` — are synthetic
geometries with `verification: synthetic_assumption` on every parameter.

This is new scope that arrived after the module waves were dispatched, and it is
a genuine gap against the current specification, not a deferral I chose. The
release cannot claim real-circuit support in any form.

### 2.2 Learning is incomplete

The pipeline is complete and reproducible. **No trained policy exists.** The
packaged actor is zero tensors named `UNTRAINED_PLACEHOLDER`, and its model card
says so in its first sentence. No held-out evaluation exists, so no promotion
decision has been made — `promote_bundle` refuses with
`benchmark_report_absent` and names the baseline that stays enabled.

The blocker is not compute. Under the reference controller, decisions withdrawn
per scenario family:

| scenario | withdrawn |
|---|---|
| `oval-low-energy` | **100 %** |
| `loop-no-energy-channel` | **100 %** |
| `oval-defend-hold` | 62 % |
| `two-straight-counterattack` | 19 % |

Only one family gives an actor usable signal; a curriculum across these four
would train mostly on inert ticks. Measured throughput is 4.8–6.2
transitions/s, so one 200k-step seed is about 10 hours and the five-seed study
about 50 — but spending that before fixing coverage would buy nothing.

---

## 3. Gate-by-gate status

| Gate | Status | Evidence |
|---|---|---|
| **G0** locked installation, contracts, generated types, numerical spike | **pass** | `infra/dependency-baseline.md`; `cli doctor`; `tests/contracts` (91). Constrained OCP spike matches its analytic optimum (x=2.5, y=1.5) to 1e-6 under CasADi 3.8.0/IPOPT |
| **G1** convergence, battery bus/ledger, no free energy, reactive opponents | **pass** | `tests/numerics` (46), `tests/simulation` (79). Energy balance closes to 2.2e-8 J (~8e-15 relative) against a frozen 1e-4 J tolerance. dt 0.02→0.01→0.005 moves checkpoint elapsed time 1.34e-6 s then 3.34e-7 s, ratio ≈ 4; branch ranking unchanged. Regen-disabled braking never raises battery energy. Independently reconstructed ledger agrees with the simulator's own to **3.75e-8 J** |
| **G2** rule pass/fail/unknown with independent boundaries | **pass** | `tests/rules` (54). Checker ignores `solver_status`; a plan whose endpoints are legal but whose interior dips to −20 kJ is rejected at margin −20 000 J. CU-K bus separation proven: 600 kJ battery gain at η=0.8 fails at −150 000 J on the correct bus and would have passed at exactly 0 on the wrong one |
| **G3** chronological cutoff, estimator coverage, hidden-truth mutation | **pass with a reported shortfall** | `tests/estimation` (100). Jacobian validated against central differences. A post-cutoff observation yields an estimate *identical* to one where it never arrived. Truth mutation leaves encoded features and beliefs byte-identical. Coverage: speed 0.878, progress 0.865, own energy 0.897 against nominal 0.90 — **rival energy 0.7885**, reported as under-coverage, cause identified as mode-prior bias |
| **G4** finite planner deadlines, constraints, revision invalidation, baseline identity | **pass on behaviour, latency target missed** | `tests/planning` (42). Deadline expiry withdraws advice; solver-converged plans are still rejected by the checker; learned-disabled equals baseline exactly. **p95 827 ms against a 200 ms target** — see §5 |
| **G5** operator lease, idempotency, selection/communication/execution, expiry | **pass** | `tests/persistence` (36), `tests/backend` (76), and the live-server run in §1. Selection records a decision with zero executions; only an observed execution reaches `executing` |
| **G6** deterministic snapshot/branch, responsive rivals, export/replay fidelity | **pass with a stated limitation** | `tests/simulation`, `tests/acceptance` (26). Identical treatments match; different treatments diverge with rivals reacting. **Seeds do not vary physics** — see §6 |
| **G7** trained candidate, continuation estimator, held-out ablations, promotion decision | **not met — learning incomplete** | §2.2. Continuation ensemble genuinely fitted (MAE 0.396, RMSE 0.509, bias −0.004 on 30 episodes / 920 cutoffs). No actor, no held-out study, no promotion decision |
| **G8** restart, dropout, database failure, missing models, solver timeout, bounded spool | **pass with two approximations** | `tests/operations` (47). Drills cause the failure rather than mocking it. Two are approximations and say so in-file — see §7 |
| **G9** browser review at seven widths, keyboard, focus, contrast, units, source labels | **pass** | 322 web unit tests, 157 browser tests. 320/375/414/768/1024/1440/1920 px on all seven routes; **axe-core 0 serious, 0 critical** |
| **G10** clean local installation, executable demo runbook, release evidence | **pass** | Cold start 7.63 s app / 13.41 s Compose from empty volumes; `scripts/demo.py` completes 13/13 steps through nginx; this report |
| **A16** real circuits and conditions | **not built** | §2.1 |

Physics fidelity against a real car, numerical convergence, and real-circuit
validation are **separate statuses**. Convergence passes. Real-car fidelity was
never attempted and cannot be claimed: every car and track parameter carries
`verification: synthetic_assumption`, and a test fails the build if any claims
otherwise.

---

## 4. Test evidence

| Suite | Tests |
|---|---|
| contracts | 91 |
| persistence | 36 |
| api | 18 |
| data | 99 |
| rules | 54 |
| numerics | 46 |
| simulation | 79 |
| estimation | 100 |
| planning | 42 |
| learning | 155 (141 fast, 14 slow) |
| evaluation | 116 |
| acceptance | 26 |
| backend | 76 |
| operations | 47 |
| **Python total** | **985** |
| web unit (Vitest) | 322 |
| browser (Playwright + axe) | 157 |

```
uv sync --frozen --all-packages --all-extras
uv run python -m afterlap_core.cli doctor
uv run python -m pytest tests
bun install --frozen-lockfile
bun run typecheck
bun run test
bun run build
bun run test:e2e
```

`ruff check` and `mypy` are clean across `apps`, `packages`, `workers` and
`tests`.

---

## 5. Measured performance, and the target that was missed

**Hardware.** Windows 11 Home Single Language 10.0.26200, Intel64 Family 6
Model 183 (24 logical CPUs), CPython 3.12.14, Docker 29.6.2 on the WSL2 Linux
backend.

| Quantity | Measured | Target |
|---|---|---|
| Planner p95 | **827 ms** | 200 ms |
| Planner p95, first 10 invocations | 169 ms | 200 ms |
| Planner p50, no re-simulation | 21.6 ms | — |
| Planner p50, with 6 simulator branches | 159.3 ms | — |
| Estimator `update()` mean | 0.834 ms | — |
| Simulator step, two cars at dt 0.02 | 0.46–1.21 ms | — |
| Cold start, app, empty artefact root | 7.63 s | — |
| Cold start, Compose, empty volumes | 13.41 s | — |
| Demo runbook, Compose | 2.81 s | — |
| Demo runbook, native Windows SQLite | 159.44 s | — |

**The 200 ms planner target is not met.** Two contributions were separated
rather than averaged. Re-simulation is 86 % of the planner's own cost. And the
host clock degraded by a factor of 4.2 across the measurement window — an
independent arithmetic reference in the same process went from 42.7 ms to
179.3 ms, and the first ten invocations, taken while that reference still read
43 ms, gave p95 = 169 ms. The latency test therefore *records* percentiles and
prints an explicit target-missed line rather than asserting a ceiling that would
measure the host rather than the planner.

**Nothing should be benchmarked on the native Windows path.** The 77× step gap
(p50 77 ms under Compose against 5905 ms native) is not physics —
`advance(1.0 s)` measures about 56 ms — and is consistent with SQLite
fsync-per-commit on NTFS. It was not isolated further.

All solver figures are **CasADi/IPOPT** figures. acados publishes no Windows
wheel and is not installed; `doctor` reports it *degraded, not installed* rather
than substituting a stub. These must not be quoted as acados figures.

---

## 6. Stated limitations

1. **No exogenous physical disturbance exists.** `KeyedRandom` works and drives
   sensor noise, but nothing perturbs the equations of motion. Observations
   differ across seeds (91.49 against 91.69 m/s at one instant); the physical
   trajectory is **bit-identical to nine decimal places**. A confidence interval
   built by resampling seeds would be falsely tight, so the harness detects the
   condition, records `degenerate_seed_variance`, and refuses to emit that
   interval. Held-out intervals are scenario-resampled only. (D-06)
2. **Rival energy interval under-covers its label** — 0.7885 measured against
   nominal 0.90. Emitted as `kind="quantile"` with `quality=degraded`, and the
   UI must render it as a model quantile, never a confidence bound.
3. **Four comparison rows are unmeasured**: `mpc_plus_actor`, `mpc_plus_value`,
   `full_system` have no trained bundle; `mpc_only` runs functionally but is not
   yet a benchmark row because it needs the real telemetry-to-estimation path.
   All render `unmeasured` with reasons and no placeholder numbers.
4. **Contact is detection-only.** An overlap blocks a pass and is recorded as
   `unsupported_by_reduced_model` rather than being given an invented collision
   probability. There is no wake model.
5. **Rule coverage is partial and says so.** Thermal derating is
   `review_required` because its curve is invented and no article was resolved;
   torque limiting is not modelled. All three packs are `synthetic: true`,
   `reviewed: false`, with no reviewer claimed. A test parses the test files to
   confirm every `implemented_and_tested` claim names a test that exists.
6. **The held-out manifest holds 25 scenarios against a declared target of 500.**
7. **Support thresholds and the probability calibrator are placeholders**
   (`frozen_before_final_test: false`, calibrator `unavailable`) because the
   calibration data does not exist.
8. **No authenticated identity.** The console sends a fixed
   `console-operator`; the control lease is held under that name.
9. **Readiness ignores session health** (A14-4). A healthy HTTP server with
   stale telemetry is *not* currently distinguished from a ready one. The
   operations agent's patch takes no position because it changes container
   restart behaviour either way; the decision is open.
10. **Three metrics have no caller** (A14-2): `observe_planner`,
    `observe_observation_age` and `spool_depth`. `/metrics` reports the required
    shape with `samples: 0`.
11. **A spawned session worker has no recorder** (A14-10) and mints its own
    session id, so an out-of-process session persists nothing.
12. **Plot shape is unverified by machine.** The browser assertions cover tick
    text, magnitude and placement; they compare no pixels, so a wrong series
    colour or an inverted trace would still pass.

---

## 7. Failure drills

Each drill causes the failure rather than asserting a mock.

| Drill | Result |
|---|---|
| Cold start from an empty artefact root | pass; `alembic_version` present, session creatable |
| Database unreachable mid-session | pass; bounded spool absorbs writes, visible warning |
| Spool exhausted | pass; new operational recommendations halt to preserve auditability |
| Worker killed mid-session | pass, **approximated** — a real spawned process is killed, but a spawned worker has no recorder, so the drill persists the dead worker's advice itself |
| Disk quota filled | pass, **approximated** — tests a guard the operations agent wrote; no disk budget exists in the application, and `POST /experiments` does not honour one |
| Wrong model hash | pass; refused before deserialisation, validated baseline named |
| Loopback binding, export path traversal, `live_team` driver action | pass |
| Graceful shutdown | pass after fix; the outbox is now flushed |
| Crash after commit before delivery | pass; the event is still delivered exactly once after dedup |

---

## 8. Defects found by verification, not by module tests

Nineteen defects were found by the coordinator or by a worker's own measurement
after its module suite was green. The pattern is consistent and worth recording:
**every one sat in a seam no single module owned.**

- **Five found only by running the assembled product** (D-07): no schema on a
  clean install; a lost update on the session row that rejected the client's
  next revision after the first step; the WebSocket never proxied; a relational
  gap channel reported as a missing measurement, blocking every recommendation
  for a whole session; and the console sending the session revision where the
  route does concurrency on the recommendation.
- **Two in the driver-execution handler** (D-08): the execution event written
  twice, because the route and the runtime each recorded it and each half was
  correct alone; and the response returning a fresh proposal as the outcome of
  executing an older instruction.
- **One I introduced while fixing another** (D-09): `ensure_schema` reported
  `"schema at migration head"` and created **zero tables** in the engine it was
  handed, because the Alembic environment overrode the URL unconditionally. The
  earlier manual verification passed only because the server's URL *is* the
  default. This is exactly the failure mode this codebase exists to refuse — a
  success report with nothing behind it — and it shipped inside the fix for a
  defect of the same shape.
- **Two compounding model-gate defects** (A14-7, A14-8): approval status ignored,
  and an undeclared feature hash treated as "skip this check" rather than
  "cannot verify". Together, an unapproved bundle trained on the wrong
  observation encoding could report `learned_contribution_enabled: true`.
- **A latent unit error** (D-05): the checker converted the deployment budget
  twice, over-draining the modelled battery by 5.26 % at η=0.95 and 25 % at
  η=0.80. Invisible because every fixture used η=1.0, where the two readings
  coincide exactly.
- **A cross-module unit ambiguity** (D-01): `harvest_target_j` did not state
  whether it meant battery gain or CU-K bus energy — a ~25 % error at η=0.8, in
  the direction that makes an illegal plan look legal, and invisible to either
  module's tests alone.
- **Three capability declarations that promised what no source supplied**,
  the last of which caused own-energy error of 87 kJ mean and 410 kJ max on a
  4 MJ window because the estimator had no power samples to integrate.
- **A chart painting a wall-clock x axis** on a distance plot, with clipped y
  ticks showing raw SI beneath a kW/MJ legend. Unreachable by 202 passing tests
  because uPlot paints ticks with `fillText` and nothing read the canvas.

Workers also corrected their own overclaims: an estimator described `predict()`
as conservative, measured a case where it was narrower (2.384 against
2.415 m/s), and fixed both code note and docstring; an ingestion adapter's
docstring claimed a constructor-level guarantee it did not enforce; a learning
agent's own measurement caught an ensemble fit reporting `unknown` for three of
four required groups.

Two tolerances were **tightened** during development, when a worker found one
had been derived from a whole-run total rather than a per-frame rate. None was
widened.

---

## 9. Reproduction

```
git clone https://github.com/Manas-thakur/f1
cd f1/the repository root
uv sync --frozen --all-packages --all-extras
uv run python -m afterlap_core.cli doctor
uv run python -m pytest tests

bun install --frozen-lockfile
bun run build

# native
uv run python -m uvicorn afterlap_api.main:app --host 127.0.0.1 --port 8000
cd apps/web && bunx vite --port 5200

# packaged
cd infra && cp .env.example .env   # then set AFTERLAP_DB_PASSWORD
docker compose up --build

uv run python scripts/demo.py
uv run python scripts/release_bundle.py
```

### Identity

| Item | Value |
|---|---|
| Schema version | `1.0` |
| Contract revision | `1` |
| Feature manifest `energy-v1` | `sha256:7029827e74a47b25e6fb00965bccd1a39d65e069eaa636d3c91f5bff1b51f817` |
| Objective `objective-v1` | `sha256:4e9fd7ab7b650ad7ec1…` |
| Promotion policy | `sha256:dc344d69576a6b9bfe1…` |
| Alembic head | `c04e287ba46c` |
| Active continuous solver | CasADi 3.8.0 / IPOPT (acados absent — D-02) |
| Model bundle | `candidate-untrained-actor`, `approval_status: unevaluated` |

---

## 10. Claims this release does **not** support

Stated plainly, because the specification requires each of these to have
evidence that does not exist:

- **No** improvement in race outcome. There is no trained model and no held-out
  paired study.
- **No** real-time claim. The planner p95 is 827 ms against a 200 ms target.
- **No** calibrated probability. Probabilities are raw scenario frequencies
  marked `uncalibrated`; the calibrator is `unavailable`.
- **No** real-car or real-circuit fidelity. Every parameter is a labelled
  synthetic assumption, and A16 is not built.
- **No** FIA compliance or certification of any kind. Rule packs are
  `synthetic: true`, `reviewed: false`, with unresolved conditions listed.
- **No** driver-integration claim beyond the simulator. The connected display is
  simulator-only and the server enforces that regardless of the client.
- **No** human-factors or usability claim. No study was run.
- **No** safety argument. Zero observed violations in the declared suite is not
  proof of safety outside it.

The reviewable evidence, the partial-observation honesty and the
retained-position framing are what this build delivers. The learned strategy,
real circuits, and a met latency budget are not.
