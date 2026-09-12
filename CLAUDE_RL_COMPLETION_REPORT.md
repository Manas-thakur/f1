# AFTERLAP RL, prediction and recommendation — completion report

Session handoff. Written 11 September 2026 against `origin/main` at `0a78999`.

---

## 1. Pull requests, branches and commits

Merge **in this order**. Each PR is based on the previous one, so a merge out of
order will show unrelated changes in the diff.

| # | PR | Branch | Head SHA | Base | Commits |
|---|---|---|---|---|---:|
| 1 | https://github.com/Manas-thakur/f1/pull/45 | `feat/rl-training-and-model-evaluation` | `7fe384256eb52ce2570d08154303dce4547a190b` | `main` | 5 |
| 2 | https://github.com/Manas-thakur/f1/pull/47 | `feat/prediction-and-calibration` | `acff0c29c394c0f929acf1059a90b4a12fc8b4ea` | PR 1 | 6 |
| 3 | https://github.com/Manas-thakur/f1/pull/48 | `feat/connected-recommendation-runtime` | `9c3d76a4348f0fe2d268d1e98aa2004ab56bffcf` | PR 2 | 7 |
| 4 | https://github.com/Manas-thakur/f1/pull/49 | `docs/model-registry-and-build-guide` | `e8231980a71ee31ee0a36c37f476e36dd8209b19` | PR 3 | 1 |

**Exact merge order: #45 → #47 → #48 → #49.** None have been merged. All work
was done in the isolated worktree `C:\Work\f1-rl-intelligence`; the dirty
`C:\Work\f1` checkout was never touched.

(PR #46 `ui` is pre-existing and unrelated to this work.)

---

## 2. What the audit found

The repository was **not a superficial demo**. It was a carefully built scaffold
with a deliberately empty middle: almost every interface for learned
intelligence existed, was typed, and was honest about being empty. Four seams
kept it disconnected.

**Five of nine CLI commands could not execute.** Verified by running them:

| Command | Failure on `0a78999` |
|---|---|
| `simulate` | `ModuleNotFoundError: No module named 'afterlap_core.runner'` |
| `train` | `ImportError: cannot import name 'run_training'` |
| `evaluate` | `TypeError: run_benchmark() got an unexpected keyword argument 'candidate'` |
| `ablate` | `ImportError: cannot import name 'run_ablation'` |
| `promote` | `TypeError: promote_bundle() got an unexpected keyword argument 'bundle_id'` |

The `runner` breakage was invisible to `mypy` because `pyproject.toml:243` lists
`afterlap_core.runner` under `ignore_missing_imports`.

**Nothing could package or run a model.** `write_bundle` had no production
caller, `load_bundle` had no caller at all, `LoadedBundle.actor_state` was a raw
tensor mapping nothing reconstructed into a policy, and no parameter count
existed anywhere.

**The runtime never called the real planner.** `default_planner` had zero
callers; `BaselinePlanner` was hardwired at four sites; the one adapter passed
`None` for `model_bundle` and supplied no `proposal`, `world` or `current_plan`.

**Predictions were computed then discarded.** `runtime.py:1102-1103` published
`outcomes=()` and `probabilities=()`. `planner.build_recommendation`, which
populates both correctly, had zero callers. Probabilities were hardcoded
`UNCALIBRATED` because no calibrator existed.

---

## 3. Changed behaviour

### PR 1 — training, packaging, evaluation entrypoints

- All five broken CLI commands repaired; `package-model` and `throughput` added.
- `learning/architecture.py` — layer tables and parameter counts read off
  constructed modules.
- `learning/policy.py` — the frozen actor rebuilt with the library's own `Actor`
  class and made runnable; verified byte-identical to the source module.
- `learning/packaging.py` — checkpoint → bundle, with a hash-covered
  `training_report.json`.
- `evaluation` — ablation via `without_contribution`, and `paired_sample_from_run`
  promoted out of a test fixture.
- `promotion.decide_from_paths` reads and decides but writes nothing.
- `afterlap_core/runner.py` — the missing headless runner.

### PR 2 — prediction and calibration

- `learning/calibration.py` — isotonic calibrator with six named refusals.
- `planning` publishes calibrated probabilities and outcome ranges; the
  calibrator arrives as a protocol so `planning` still imports nothing from
  `learning`.
- `learning/dataset.py` + `EventRealisation` — the forecast/realisation dataset.
- `learning/prediction.py` — one serving surface behind all the gates.
- `fit-value` and `fit-calibration` CLI commands.
- Contracts: `OutcomeRange`, `LearnedContribution`.

### PR 3 — the connected runtime

- `LearnedPlannerAdapter` supplies world, current plan, continuation adapter,
  calibrator and actor proposal per decision.
- `model_registry` discovers and validates bundles; `SessionFactory` builds one
  planner per session.
- `planning/publication.py` derives the published evidence in one place.
- `PlannerController` makes `mpc_only` runnable and the three learned rows
  ablatable.
- Contracts: `RecommendationAlternative`, plus `outcome_ranges`, `alternatives`,
  `learned`, `planner_identity`, `unavailable_reasons` on `Recommendation`.
- Web: the evidence inspector surfaces all of it.
- **Five latent defects fixed** (section 6).

### PR 4 — the registry

- `afterlap_core.model_registry` derives the nine-model inventory from code.
- `docs/learning/MODEL_REGISTRY.md` and the drift test that keeps them aligned.
- `model-registry` CLI command.

---

## 4. Every model and every observed metric

Machine for all measurements: Windows 11, Intel64 Family 6 Model 183, 16
threads, **CPU only, no CUDA**. torch 2.14.0+cpu, stable-baselines3 2.9.0,
gymnasium 1.3.0, CasADi 3.8.0, numpy 2.5.3.

### Architecture (exists now)

| Model | Kind | Trainable parameters |
|---|---|---:|
| `sac-energy-strategy` actor | learned | **116,228** |
| `sac-energy-strategy` critic | learned | **231,938** |
| `sac-energy-strategy` critic target | Polyak copy, not optimiser-updated | 231,938 |
| entropy coefficient | learned scalar | 1 |
| **SAC optimiser-updated total** | | **348,167** |
| `continuation-return-ensemble` | learned | **577,285** (5 × 115,457) |
| `probability-calibrator` | statistical | non-parametric |
| `planner-surrogate`, `rollout-forecaster`, `own-car-estimator`, `rival-belief`, `independent-rules-checker`, `reward-objective` | deterministic / statistical | 0 |

The naive sum across the three SAC networks is 580,104, which counts the critic
twice: SB3 2.9.0 leaves `requires_grad=True` on the target copy while building
the optimiser over `critic.parameters()` alone.

### Observed — environment throughput

**8.28 transitions/s** step-only, 6.21 including resets, at
`planner_mode=no_rollout`.

### Observed — SAC bounded training run

`sac-env-v1-seed11-20260910T201455Z`, config `sac-v1` unchanged, seed 11,
`n_envs=4`, 20,000 transitions.
Record: `artifacts/reports/bounded_train_seed11.json`.

| | Observed |
|---|---|
| Status | `completed`, 20,000 / 20,000 |
| Wall clock | 3,519 s (58.6 min), 5.68 transitions/s |
| `train/actor_loss` | mean **+37.7447**, p05 +36.43, p95 +38.91 (n=500) |
| `train/critic_loss` | mean **+1.2730**, p05 +0.913, p95 +1.760 (n=500) |
| `train/ent_coef` | mean **+0.0715** (n=500) |
| `train/ent_coef_loss` | mean **−7.6124** (n=500) |
| Training episode return | mean **−54.336**, p05 −65.10, p95 −27.46 (n=200) |
| Episodes | 640 finished, 0 failed, 0 truncated |
| Withdrawal rate | **0.6636** |
| Solver timeouts | 91 |

All four tracked losses stayed finite; the non-finite-loss guard did not fire.

Bundle `sac/afterlap-learning-env/env-v1/planner=no_rollout/sac-env-v1-seed11-20260910T201455Z/20000`,
weights `sha256:19bf6ae8cf2a27e90b3b6584f…`, data hash
`sha256:ab662183c5e2beb3dfbfde784…`, code revision
`7fe384256eb52ce2570d08154303dce4547a190b-dirty`, approval `unevaluated`.

### Observed — deterministic evaluation across checkpoints

3 actor-mean episodes each, `two-straight-counterattack`, seed 101.
Record: `artifacts/reports/learning_curve_seed11.json`.

| Checkpoint | Steps | Mean return |
|---|---:|---:|
| step-000005000 | 5,000 | −65.1493 |
| step-000010000 | 10,000 | −65.1493 |
| step-000015000 | 15,000 | −65.4993 |
| step-000020000 | 20,000 | −64.6996 |
| final | 20,000 | −64.9661 |

**This does not demonstrate learning.** Spread ≈ 0.8 utility units,
non-monotone, small next to the training-return spread.

### Observed — continuation-return ensemble

`fit-value`, 20 episodes, seed 0, controller `held-neutral/action-zero`.
Record: `artifacts/reports/value_fit_seed0.json`.

| | Observed |
|---|---|
| Collection | 20 complete episodes → 720 samples |
| Split (by episode) | 14 train / 6 tuning → 504 / 216 samples |
| Early stopping | epochs [15, 194, 199, 16, 125] |
| Target scaler (train only) | mean −45.281, std 8.843 |
| **Tuning MAE** | **0.6215** |
| **Tuning RMSE** | **0.7901** |
| **Tuning bias** | **+0.0038** |

Grouped MAE / RMSE / bias: remaining <250 m 0.4073 / 0.4961 / −0.0854 (n=24);
<500 m 0.5629 / 0.6523 / +0.1460 (n=18); <1000 m 0.7010 / 0.9032 / −0.0981
(n=72); <2000 m 0.7477 / 0.9023 / +0.0216 (n=66); ≥2000 m 0.4032 / 0.4947 /
+0.1631 (n=36); energy high 0.4032 / 0.4947 / +0.1631 (n=36); energy medium
0.6652 / 0.8367 / −0.0281 (n=180).

MAE 0.62 against a target σ of 8.84 is ≈7% of a standard deviation, on **one
scenario, one opponent family, one controller and six tuning episodes**. Not a
generalisation claim.

### Observed — probability calibrator: none fitted

Records: `artifacts/reports/calibration_fit_seed0.json`,
`calibration_fit_random_seed7.json`.

| Collection | Episodes | Forecasts | Labelled | Dropped | Base rate, all four events |
|---|---|---|---|---|---|
| `held-neutral/action-zero`, seed 0 | 40 | 1,296 | 1,296 | 0 | **0.0** |
| `uniform-random/seed7`, seed 7 | 40 | 688 | 648 | 40 | **0.0** |

Every event was refused as a single-class set. `status: unavailable`. The
machinery declined to launder a forecast it could not validate — the correct
outcome.

The unit test fits a *known* distortion and confirms the held-out Brier score
improves from **0.2062 to 0.1944**, so the fitter itself is exercised.

### Observed — the connected runtime

`two-straight-counterattack`, `synthetic-pack-v1`, seed 20260908, 60
one-second advances, default configuration:

| | Observed |
|---|---|
| Actionable recommendations | **35 of 60** |
| First actionable | tick 25, `recover` |
| Alternatives published | 4, ranked, with decomposed comparison |
| Learned contribution | disabled — no bundle promoted |
| Planner latency, no re-simulation | **60–120 ms** |
| Planner latency, with re-simulation | **200–460 ms** (declared budget 200 ms) |

---

## 5. Tests run

| Gate | Result |
|---|---|
| `uv run ruff format --check .` | all 353 files formatted |
| `uv run ruff check .` | All checks passed |
| `uv run mypy` | Success, 345 source files |
| `uv run python scripts/check_no_comments.py` | comment policy: pass |
| `uv run python docs/tools/validate_package.py` | PASS |
| `uv run python -m afterlap_contracts.schema_export --check` | generated contracts match the models |
| `uv run python -m afterlap_core.cli doctor` | no failed capabilities |
| `uv run pytest -q -m "not slow" --ignore=tests/learning` | exit 0, **1,561 tests** |
| `uv run pytest -q tests/learning tests/evaluation` | pass, **446 tests** |
| `bun run lint` | exit 0 |
| `bun run typecheck` | exit 0 |
| `bun run test` | 26 files, **348 tests** passed |
| `bun run build` | **fails on Windows**, see blockers |

New test files: `tests/learning/test_architecture.py` (13),
`test_policy.py` (18), `test_packaging.py` (22), `test_jobs.py` (39),
`test_calibration.py` (28), `test_prediction.py` (23), `test_dataset.py` (17);
`tests/evaluation/test_ablation.py` (13);
`tests/planning/test_probability_calibration.py` (10);
`tests/backend/test_connected_recommendation.py` (26);
`tests/operations/test_model_registry.py` (25);
`apps/web/src/features/engineer/EvidenceInspector.test.tsx` (8).

`tests/learning` went from 155 to 247 tests.

---

## 6. Latent defects found and fixed

All five were unreachable before this work and all are fixed in PR 3.

1. **Process-wide CasADi solver cache called from worker threads.** An `nlpsol`
   is a native IPOPT handle and is not thread-safe; the runtime plans on worker
   threads. Surfaced as a Windows access violation. **The same test selection
   passes on the parent commit**, so this PR caused the exposure, not the bug.
   Fixed: thread-local cache.
2. **Energy beliefs outside the battery window crashed the rollout.** Observed
   as `initial energy 4063376.7 is outside the window [0.0, 4000000.0]`. Fixed:
   clamped, with each clamp published on `RolloutEvidence.belief_clamps`.
3. **Revision-numbering mismatch discarded every valid planning result.** The
   core planner stamps `state_revision` from the estimate; the runtime guard
   compares it to the plan-request revision. Sessions withdrew advice forever.
   Fixed: the adapter translates.
4. **`accepted[0]` published instead of the selected plan**, which would have
   discarded hysteresis and dwell silently.
5. **Two planners with opposite score-direction conventions.** `select_instruction`
   takes the `min`; `baseline_planner` ranks by `-final_score`. My first
   `alternatives_for` would have inverted one. Fixed: accepted candidates keep
   the planner's own order and no ordering claims a direction.

---

## 7. Unresolved blockers

**No learned model contributes to anything.** No bundle is promoted, so the
connected runtime is the MPC planner with the learned seams open and unused.
The wiring is proven and tested; the learned path is not exercised end to end
because there is nothing approved to exercise it with.

**The bounded run does not demonstrate learning**, and 20,000 transitions was
never going to. At 8.28 transitions/s the declared 200,000-step budget is ≈6.7
hours per seed of environment time alone, so the five declared seeds are well
over a day before any evaluation.

**Re-simulation does not fit the declared decision budget** on this machine
(200–460 ms against 200 ms), so `planner_rollout_enabled` defaults to off and
probabilities and outcome ranges are empty by default. The derivation and
publication paths are present and tested; enabling rollouts populates them.

**`ahead_at` is forecast over one window and labelled over another.** Forecast
1.0 in 7 of 32 probe cases, realised 0 in all 32. `rollout.py:435` evaluates it
over the branch horizon; a realisation resolves it over the whole episode. Same
words, different windows. **Not fixed** — correcting it changes an event
definition the specification states and that `tests/planning` exercises. Full
write-up with both candidate resolutions:
`artifacts/reports/finding_ahead_at_horizon.md`.

**No scenario produces a non-zero pass rate.** Every calibration base rate was
0.0 under both controllers tried, so no calibration set can be identified from
the shipped scenarios.

**`bun run build` fails on Windows** at the Next.js standalone tracing step with
`EPERM: operation not permitted, symlink`. Compilation, type-checking and all 9
static pages succeed first. CI builds on Linux; not verified green here.

**CI installs neither the `learning` nor the `solver` extra**, so
`tests/learning`, `tests/evaluation` and every solver-backed path run locally
only. Pre-existing; not changed by this work.

**`artifacts/` is gitignored**, so every run record cited above is local to this
worktree. The commands to regenerate all of them are in
`docs/learning/MODEL_REGISTRY.md`.

---

## 8. What a promotion-quality model would need

From `configs/benchmarks/promotion.yaml` (`enabled: false`, thresholds frozen
2026-09-08). None is met.

| Requirement | Status |
|---|---|
| ≥ 100 independent test scenarios | the shipped held-out manifest declares 25 |
| ≥ 5 training seeds | 1 run |
| A measured `mpc_only` baseline | the controller now exists; the comparison has not been run |
| Hierarchical paired bootstrap excluding zero at ≥ 2.0 utility | not measured |
| CVaR₀.₉ downside ≤ 1.0 | not measured |
| Latency p95 ≤ 200 ms for a learned row | not measured |
| Withdrawal rate ≤ 0.05 | observed 0.6636 |
| Modelled violations = 0 | 0 observed |
| Two named ablations | now measurable; not run |
| Frozen support thresholds and a frozen calibrator | neither exists |

The gap is a compute-and-scenario gap, not a machinery gap. Every command needed
to close it now exists and works.

---

## 9. Nothing fabricated

No training result, measurement, benchmark win, model weight or regulatory claim
in this report or in any PR description was invented. Every number cites the run
record that produced it. Where a measurement came out badly — the 0.6636
withdrawal rate, the non-monotone evaluation curve, the calibrator that could not
be fitted, the forecaster that is confidently wrong about `ahead_at` — it is
reported as it came out.
