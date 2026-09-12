# End-to-end audit

**Scope.** Every gate, every surface and every process AFTERLAP ships, run on
one machine against a real PostgreSQL, a real Python runtime, a real batch
worker and a real browser. Reviewed: 103 specification documents, 61 519 lines
of Python across `apps/api`, `packages`, `workers` and `scripts`, 21 253 lines
of TypeScript across `apps/web`, 31 512 lines of test, the local stack
definition, and the CI workflow.

**Verdict.** The product works end to end. A session created in the browser
runs through observation, estimation, legal planning, engineer selection,
driver execution, snapshot, paired experiment and export, and every artefact it
produces carries provenance. The audit found and fixed twelve defects, none of
which produced a wrong recommendation, and most of which were the same shape:
a value that nothing was checking, because nothing could.

The most consequential were two unauthenticated remote-code-execution
advisories in the pinned Next.js version, a manifest field carrying two
different digest encodings depending on which code path filled it, and a mypy
override that had quietly switched off fifteen error codes across every core
and API module.

Branch: `audit/end-to-end`. Every claim below is reproducible with `make audit`.

---

## 1. What was run

`make audit` is the single command this audit added. It runs every gate in
dependency order, stops at the first failure, then starts the stack on free
ports and drives it. Nothing in it is a mock.

| Gate | Result |
|---|---|
| `uv lock --check`, `bun install --frozen-lockfile` | pass |
| `uv audit`, `bun audit` | pass, 0 advisories (was 34) |
| `zizmor` on `.github/workflows` | pass, 0 findings (was 40) |
| `ruff format --check`, `ruff check` | pass, 51 rule families |
| `mypy` (strict, 354 files) | pass |
| comment policy, docs package, schema drift | pass |
| `afterlap_core.cli doctor` | pass, 1 optional capability absent |
| `pytest` (full suite, no deselection) | pass, 1 779 tests |
| `biome check --error-on-warnings` | pass, 391 rules over 166 files |
| `eslint`, `tsc --noEmit` | pass |
| `vitest` | pass, 359 tests |
| `next build` | pass, no warnings |
| Playwright, fixture-driven | pass, 166 tests |
| `afterlap_core.cli simulate` | pass, 30 s closed loop |
| `afterlap_core.cli evaluate` | pass |
| `afterlap_core.cli train` (SAC smoke, off-gate) | pass, checkpoint written |
| **live** PostgreSQL + runtime + batch worker + production website | |
| `scripts/migrate.py` (alembic, real PostgreSQL) | pass |
| `scripts/demo.py` 13-step runbook | pass, 141 s |
| Playwright against the live stack | pass, 16 tests, 273 s |

The live stack ran against `postgres:17.7` in Docker, the Python runtime over
its loopback IPC socket, the batch worker polling for jobs, and `next start`
serving the production build. The website was driven by a real Chromium, not a
fixture: it created the session, acquired the control lease, started and
stepped the simulation, selected and communicated a recommendation, executed a
driver action, took a snapshot, queued a paired experiment, waited for the
batch worker to finish it, and exported the record.

Evidence lands in `artifacts/audit/<timestamp>/`: one log per check,
`summary.json` with the ordered result of each, `runbook.json` with every
observation the 13 steps made, ten full-page screenshots under `screens/`, and
sixteen video recordings under `recordings/` including a 3.6-minute capture of
the complete lifecycle.

### Measured, on this machine, on synthetic data

These are observations from one run on one machine. They are not performance
claims and the product does not present them as such.

| Quantity | Value |
|---|---|
| Planner duration, p50 / p95 / p99 | 0.311 / 0.358 / 0.362 ms over 26 decisions |
| Observation age, p50 / p95 | 0.160 / 0.160 s |
| Stream resyncs during the runbook | 0 |
| Spool depth | 0 |
| Runbook wall time | 141 s |
| Standalone benchmark latency p95 | 0.041 ms over 30 decisions |

The planner's own p95 is three orders of magnitude inside the 200 ms budget
`ARCHITECTURE.md` sets, on a synthetic two-car scenario with a fixed schedule.
Neither number transfers to a real circuit or a real solve.

---

## 2. Defects found and fixed

### 2.1 Two critical remote-code-execution advisories in the shipped tree

`bun audit` reported 34 advisories against `bun.lock`: 2 critical, 16 high, 14
moderate, 2 low. The two critical ones are unauthenticated RCE in Next.js —
GHSA-p293-qw3h-jr36 on Windows hosts and GHSA-2xp9-vwfh-vxw4 in the image
optimisation API when AVIF is used. Both were fixed in 15.5.24; the tree pinned
15.5.9.

Fixed by moving Next to 15.5.25 inside the same minor line and adding
`overrides` that lift `postcss` and `sharp` past their advisories. `bun audit`
now reports none. `uv audit` reported none before or after.

**Why nothing caught it:** there was no dependency-advisory gate. There is one
now, in `make audit` and in a CI job.

### 2.2 One manifest field carried two digest encodings

`SessionManifest.track_hash` is documented as a content hash. For a
YAML-configured track it held `sha256:<64 hex>`. For a session on a compiled
circuit package it held bare hex with no algorithm prefix, because
`TrackPackage` writes its own digest into its own file unprefixed and
`CompiledTrackSource.config_hash` passed that value straight through.

A consumer that strips `sha256:` before comparing, or that recomputes
`content_hash()` and compares, gets a false mismatch for every package-backed
session — and a false mismatch on a track digest is the signal that the
geometry changed under the session.

Fixed by prefixing at the package-backed source, so one field has one encoding.
The genuinely different encoding — a digest a file writes into itself — is now
its own type, `HexDigest`, so the difference is visible in the schema and in
the generated TypeScript instead of being discovered from a failed comparison.

### 2.3 A placeholder string in a digest field

`packages/core/afterlap_core/planning/planner.py` built the plan record handed
to the independent checker with `ruleset_hash="pending"`. The record is
deliberately unchecked at that point, but the pack it was built against is a
known fact, and `"pending"` is a value no digest comparison can ever match. It
also violates the repository's own rule that unknown is `null` plus a reason,
never a placeholder.

Fixed by passing `rule_context.ruleset_hash`, which is in scope at the call
site.

### 2.4 Every digest on the wire was an unconstrained string

Thirty-eight fields across nine contract modules were typed
`str = Field(min_length=1)` or plain `str`. That accepts `"sha256:"`, a
truncated digest, an uppercase digest, a digest from a different algorithm and
a megabyte of text. Defects 2.2 and 2.3 both hid behind this.

Fixed with two annotated types — `ContentHash` for `sha256:<64 lowercase hex>`
and `HexDigest` for the bare form — plus a regression test that walks the
generated JSON Schema and fails when any `*_hash`, `*_hashes` or `*sha256`
field declares neither pattern. A field added later inherits the rule instead
of escaping it.

### 2.5 The batch worker resolved controllers by the wrong identifier

`ExperimentManifest` carried `treatment_ids` but not the controller each
treatment named — `TreatmentSpec.controller` lived only in the request body.
The worker therefore matched the *treatment id* against the controller
registry, so a treatment labelled `candidate` resolved to an
`UnavailableController` and produced an explicitly unmeasured row. The console
offers exactly that labelling.

Fixed by carrying `controller_ids` on the manifest, validated one-to-one
against `treatment_ids`, and zipping them in the worker. The live browser test
now asserts the report names both controllers and that all four
`(treatment, seed)` runs completed with positive progress.

### 2.6 The batch worker wrote reports into a different tree from the one the API reads

The worker built its `Paths` from the process default and ignored
`AFTERLAP_ARTIFACT_ROOT`, so under any deployment that sets it — the audit
runner, the container image — reports were published where the API would never
look for them. The healthcheck had the same bug, so it reported healthy while
looking at an empty directory.

Fixed in both. A regression test asserts the heartbeat lands under the
configured root and not under the default one.

### 2.7 Learned model bundles were accepted and then ignored

`POST /experiments` accepted `model_bundle_id` on a treatment. Nothing in the
batch path can load one, so the run silently proceeded without it — a mocked
success, which `AGENTS.md` forbids. The console's own hint invited it
("Optional. Leave empty to run the candidate controller with no learned
bundle").

Fixed: the route refuses with `capability_unavailable`, and the hint says so.

### 2.8 Every workflow persisted its token, and no action was pinned

`zizmor` reported 40 findings on `ci.yml`: 5 `artipacked` (every
`actions/checkout` leaves `GITHUB_TOKEN` in `.git/config`, readable by any
later step or by anything the build executes) and 17 `unpinned-uses` (actions
referenced by mutable tag, so a moved tag runs different code).

Fixed: `persist-credentials: false` on every checkout, every action pinned to a
commit SHA with the tag in a trailing comment. `zizmor` now reports nothing.

### 2.9 Fifteen mypy error codes were disabled across every core and API module

While this branch was open, `main` gained an override disabling `arg-type`,
`attr-defined`, `union-attr`, `no-any-return`, `operator`, `type-arg`,
`comparison-overlap`, `unreachable`, `misc`, `call-arg`, `no-untyped-call`,
`var-annotated`, `index`, `assignment` and `return-value` for
`afterlap_core.*` and `afterlap_api.*` — that is, for the whole product. Strict
mypy was still declared at the top of the file and still passed; it was
checking almost nothing in the two packages that matter.

This branch keeps the strict configuration and fixes the 27 errors it exposes.
Three were real:

- `CircuitIdentity.track_readiness` was typed `str` and fed a contract field
  typed `TrackReadiness`, going through a `.value` round trip on the way. The
  identity now holds the enum, and the one place a string is needed converts
  explicitly.
- `factory.py` imported `Planner` from `session.runtime`, which does not export
  it. With `no_implicit_reexport` on, that is an error; it worked only because
  the code disabling it also disabled `attr-defined`.
- `PredictionController._proposal` called `.propose` and `.applicable_limits`
  on values it had already established could be `None`.

The rest were annotations: an `Any` from a JSON document narrowed nine times by
an `isinstance` mypy could not follow, a `str` where a `Literal` was declared,
and four `dict[str, object]` that should have been `dict[str, Any]`.

### 2.10 The video app ships outside every gate

`apps/video` has a `typecheck` script that nothing runs: the workspace
`typecheck` filtered `@afterlap/web` only, `lint` runs ESLint on `apps/web`
alone, and Biome's file list did not include it. The workspace script now runs
both typechecks. Bringing it under Biome would take 29 mechanical edits to code
this branch does not otherwise touch, so it is left as a recommendation rather
than folded into an audit.

### 2.11 `simulate` accepted any float typer could parse

`afterlap_core.cli simulate` declared `duration_s` and `dt_s` as plain floats
and `seed` as a plain int. Four consequences, all reproducible on `main`:

- `--duration-s inf` integrated without end. It does not stop, and nothing
  bounds it.
- `--duration-s 1e9` is the same in practice.
- `--duration-s nan` printed a **complete, successful-looking energy ledger**
  for a zero-length run and exited 0. A fabricated result from nonsense input
  is the one thing `AGENTS.md` names as forbidden.
- `--seed -1` was accepted although every contract declares the seed as
  `0 <= seed <= 2**32 - 1`.

Fixed with typer bounds plus a finiteness check and a scenario-existence check
before the runner is imported, so a job that cannot run says so and prints
nothing that could be read as a measurement. Eleven malformed inputs are now
regression-tested.

### 2.12 The browser audit's own evidence did not show the feature working

The driver screenshot fired the instant the route loaded, so the saved artefact
showed `NO INSTRUCTION`, `mode unknown` and a connecting stream — the empty
state, not the state under test. The lab screenshot was taken before the queued
experiment reached `completed`.

Fixed: captures wait for the network to settle and for the state the test is
about, and are full-page. Five reference surfaces are captured too, so one run
leaves a complete visual record.

---

## 3. Lint floors raised

### Python: Ruff

51 rule families, up from 40. Added `BLE` (blind except), `EXE`, `FBT`
(boolean trap), `INP`, `INT`, `NPY`, `PGH`, `SLOT`, `T20` (print) and `YTT`.
Twenty rules left the blanket ignore list. Complexity ceilings dropped from
40/24/12/120 to 20/18/10/100.

The global ignore list is 17 entries and every one has a stated reason. Four
are worth naming because a reader would otherwise assume they were laziness:

- **S101 (assert).** All 41 uses are `assert x is not None` narrowing for
  strict mypy on an `Optional` field. They are not input validation — that is
  Pydantic's job at the boundary and an explicit `LifecycleError` inside — so
  their disappearance under `python -O` costs nothing. Converting them would
  add 41 branches to satisfy a linter.
- **TRY004.** Every hit is `isinstance` on a parsed YAML or JSON document. That
  is a malformed-*data* check, and `ValueError` is the right exception;
  `TypeError` describes a wrong argument type and would break callers.
- **PERF401.** Every hit is a loop appending a multi-line constructor. The
  comprehension is slower to read and the gain is unmeasurable here.
- **N818.** The codebase names refusals by condition —
  `CapabilityUnavailable`, `ModeNotPermitted`, `WorkerBusy`. Renaming 21
  classes to end in `Error` would lose that and ripple through every caller.

Forty-four per-file exemptions replace what were blanket ignores, so a new file
inherits the strict floor rather than the historical one.

### Python: mypy

`workers/` was excluded from type checking entirely, and eight script modules
carried `ignore_errors = true`. Both are gone: mypy now covers 329 files
instead of 326, and the eight modules turned out to need two fixes between
them — a `Runbook._current` field that was never declared, and one untyped
SQLAlchemy call that gets a local pragma.

The test-suite exemption list drops from sixteen error codes to seven. Nine
were costing nothing at all; removing them found a fixture annotated
`Iterator[Path]` that returns a `Path`, a `type: ignore` naming the wrong code,
and two missing annotations. The seven that remain — `arg-type`,
`attr-defined`, `union-attr`, `operator`, `var-annotated`, `unreachable`,
`comparison-overlap` — cost 231 errors between them and are the deliberate
looseness of a suite that constructs invalid values on purpose.

### TypeScript: Biome

391 rules enforced, up from the recommended preset plus nine. The 35 that stay
off are listed in one place in `biome.json`. Three groups:

- **Rules for other frameworks.** `noSolidDestructuredProps`,
  `useSolidForComponent`, `useQwikValidLexicalScope`, `noReactSpecificProps`
  (which flags `className` — it is a Solid rule).
- **Rules that contradict the stack.** `useImportExtensions` and
  `noUnresolvedImports` assume extension-based resolution, not a bundler with
  `paths`; `noDefaultExport` contradicts Next's page convention;
  `useNamingConvention` would rename the snake_case wire fields the contracts
  define.
- **One rule that is wrong here.** `noUnnecessaryConditions` reported every
  hit as a false positive: Biome 2.5 infers a mutable class field initialised
  to `false` as the literal type `false`, and reads TanStack Query's
  `isPending` as impossible. It would have deleted live branches of the stream
  reconnect state machine.

`noNodejsModules`, `noProcessGlobal`, `noProcessEnv`, `noAwaitInLoops`,
`useGlobalThis` and `noEmptyBlockStatements` are scoped off for server, test
and end-to-end files, where each is correct, and enforced everywhere else.

Enabling them found seven real problems, all fixed: a `forwardRef` whose inner
function shadowed the exported component (React 19 takes `ref` as a prop), a
module-level `spec()` factory shadowed by a `spec` parameter in four exported
functions, `>> 1` as a binary-search midpoint, an empty string rendered as a
ternary alternate, two re-exported imports, five async route handlers returning
an un-awaited promise so a rejection escaped their frame, and five CSS rules
using the `start`/`end` box-alignment keywords inside flex containers. The
production build is now warning-free.

---

## 4. Tests added

| Suite | What it pins |
|---|---|
| `tests/contracts/test_hash_and_length_bounds.py` | 38 digest fields declare a pattern and a fixed length; 10 malformed digests are refused by four contracts; the two encodings refuse each other; every string a client can send is bounded; the count of unbounded server strings cannot grow |
| `tests/backend/test_workers_and_routes.py` | the worker resolves controllers by name, all four runs complete with positive progress, and a learned bundle is refused |
| `tests/contracts/test_request_boundaries.py` | an experiment manifest refuses a controller list that does not match its treatments |
| `tests/operations/test_worker_heartbeat.py` | the worker heartbeat lands under the configured artefact root, not the default |
| `tests/operations/test_audit_runner.py` | the audit stops at the first failed gate, records the exit code, kills its live processes when a later gate fails, and never reports an interrupt as a pass |
| `apps/web/e2e-live/workflow.spec.ts` | the experiment report names both controllers; replay and the sessions list render for the created session; the stream is open on return to the console; five reference surfaces render without a page error |

The suite is 1 779 Python tests, 359 Vitest tests, 166 fixture-driven browser
tests and 16 live browser tests. Nothing is deselected: CI previously ran
`pytest -m "not slow and not torch" --ignore=tests/learning`, which skipped the
entire learning module. It now runs everything.

---

## 5. CI

Six jobs, and a `gates` job that fails unless all five others succeeded, so
branch protection has one check to require.

| Job | Adds |
|---|---|
| `python` | `uv lock --check`; the full test suite instead of a filtered one; JUnit XML uploaded |
| `web` | unchanged gates; `test-results` uploaded on failure |
| `supply-chain` | **new** — `uv audit`, `bun audit`, `zizmor` |
| `portability` | unchanged, Windows and macOS |
| `integration` | **new** — real PostgreSQL service, production build, live runbook and live browser via `scripts/audit.py --live-only`; logs, screenshots, recordings and `summary.json` uploaded |
| `gates` | **new** — one required check |

Workflow-level: `permissions: contents: read`, `persist-credentials: false` on
every checkout, every action pinned to a SHA.

---

## 6. Observations that are not defects

- **`saturation_events: 924` in a 30-second benchmark.** The legal fixed
  schedule sits on its power ceiling for most of the run and the scenario ends
  in `energy_depletion`. That is the baseline controller behaving as specified,
  not a fault, and the report labels it. It does mean the shipped baseline is a
  weak reference for a comparison, which the promotion protocol already
  accounts for.
- **The SAC smoke run reports 45 % withdrawals and one solver timeout in 64
  decisions.** Run outside the gates to exercise the learning path: it writes a
  checkpoint, resumes, and labels itself `SMOKE RUN … NOT a trained model`. The
  withdrawal rate is the planner refusing to advise on an unconverged solve,
  which is the specified behaviour, and the run reports it rather than hiding
  it. It is not evidence about a trained policy and the manifest says so.
- **`degraded database` from `doctor` with no `AFTERLAP_DATABASE_URL`.** The
  runtime falls back to local SQLite and says so. Correct.
- **`absent acados`.** Optional; CasADi/IPOPT is the active solver and the
  doctor gate passes without it, which is what a default install should do.
- **The console shows `lateral geometry degraded` beside
  `corridor_quality: unknown`.** Two different facts — the control plane's
  capability state and the compiled package's own declaration — and both are
  accurate. The wording could distinguish them more clearly.
- **199 server-generated strings still declare no length or pattern.** None is
  client-supplied, so none is an input-validation hole; they are a rendering
  and storage concern. The count is pinned by a test so it cannot grow while
  nobody is looking.
- **`bun@1.3.14` is pinned in `packageManager` and CI; 1.4.0 was used
  locally.** No difference observed across lint, typecheck, test, build or
  either browser suite.

---

## 7. Recommendations

1. **Normalise the remaining bare digests.** `HexDigest` documents the second
   encoding rather than removing it. Prefixing `TrackPackage.package_hash` at
   rest would leave one encoding everywhere, at the cost of recompiling every
   shipped package.
2. **Bring the 199 unbounded response strings down.** The pinned count stops
   the set growing; nothing yet shrinks it.
3. **Add a coverage floor.** `pytest-cov` is already a dependency and unused by
   any gate.
4. **Bring `apps/video` under Biome and ESLint.** Its typecheck is wired in
   now; its lint is not, and it is 29 findings away.
5. **Reconsider `noUnnecessaryConditions` when Biome's type inference
   matures.** It is the only rule turned off for being wrong rather than
   inapplicable, and it is a valuable rule when it works.
6. **Automate the dependency bumps.** The advisory gate will now fail the build
   the day a new one lands, which is correct but abrupt; Dependabot or Renovate
   would turn that into a pull request instead.

---

## 8. Reproducing this

```
make audit
```

Runs everything above and writes to `artifacts/audit/<timestamp>/`. Roughly 45
minutes on eight cores, most of it the Python suite and the live browser run.

```
uv run --no-sync python scripts/audit.py --live-only --output /tmp/audit
```

Runs only the live half against an already-built checkout, in about eight
minutes. Set `AFTERLAP_AUDIT_DATABASE_URL` to use PostgreSQL instead of the
default SQLite; the CI `integration` job does exactly that.
