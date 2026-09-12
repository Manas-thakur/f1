# Validation and evaluation

Reference revision: `ee51224` on `origin/simulator`. Experiments ran on the same Linux x86_64 workspace with Python 3.12, float64 RK2 and 0.01 s steps unless noted. Timing is a workstation measurement, not an isolated hardware benchmark. No Numba changes were copied from the UI worktree. There is no compilation stage in this implementation.

## Matched overtaking experiments

`scripts/race_experiments.py` fixes the car document, initial progress/speed/energy, 0.18 s driver execution delay, zero sensor noise and static environment. A leader's physical pedal controller maintains 34 m/s, or requests 60 m/s after two seconds in the abort case. It does not set velocity. The follower uses each revision's actual live automatic controller. The revised controller retains its seeded personality. The original policy has no equivalent traits, so original results repeat across these seeds. These repetitions are not independent evidence for the original controller.

| Scenario, seeds 11/23/37 | Original | Revised |
| --- | --- | --- |
| Steady rival | 0/3 follower passes, oscillating following | 3/3 follower passes |
| Accelerating rival | 0/3 passes, no explicit intent/abort state | 3/3 deliberate attempts aborted, 0 completed passes |
| Third car on one side | No follower pass of the lead car | 3/3 lead-car passes using the available side |
| Wake disabled | 0/3 follower passes | 3/3 follower passes |
| Physical failures, all above | 0/12 | 0/12 |
| Episode result, all above | 12 time-limit truncations | 12 time-limit truncations |

The seed-11 pass takes 4.58 s from recorded commitment to full physical clearance. This is an outcome, not a required universal passing time. Mean follower jerk RMS in the steady-rival cases falls from 102.55 to 2.38 m/s³; in the abort cases it falls from 88.81 to 2.76 m/s³. Samples are 0.1 s apart. Do not interpret lower gap variance as better driving: a successful pass necessarily traverses a large gap range. The old follower remained approximately 25-30 m behind while repeatedly accelerating and braking.

Held-out seeds 101/202/303 each pass the live pass/abort regression tests. Acceptance requires the expected physical event, no unsupported failure, and follower jerk RMS below 10 m/s³ over the ten-second pass test. The latter is a generous regression guard relative to the original roughly 100 m/s³ chatter, not an empirical comfort or realism limit. Finer 0.005 s and coarser 0.02 s runs preserve all six pass/abort outcomes. The maximum difference in minimum gap between those step sizes is below 0.003 m. One longer pass trace has higher jerk near the upcoming artwork corner, so no global jerk claim is made.

## Broader checks and limitations

Twelve terminate-mode two-car cases cross Monza/Silverstone, seeds 101/202/303 and initial wetness 0/0.8 with a 30 s wetting/drying constant and broad training variation. Final runs all reach the 30 s time limit without contact or envelope failure. They are all reported as truncated. An earlier four-case contact failure exposed the leader returning into close rear pressure; a line-holding regression now protects that behavior.

A 20-car Monza field reaches its 10 s limit, recording eight completed passes. This short full-field check does not establish whole-race reliability. A deterministic baseline single-car Monza race finishes one lap in 119.44 simulated seconds without an unsupported failure. That time is a synthetic geometry result, not a calibrated real-circuit lap time.

Unit and numerical tests cover missing observations, pressure, unavailable sides, a third-car blocker, overlap through a corner, aborts, returning, a legitimate repass, retained position, local lapped traffic, shared finish crossing, low energy, wet grip, wind direction, finite configuration, energy limits and checkpoint replay. The cadence test exercises 0.005, 0.007, 0.01 and 0.02 s steps, requiring an exact one-second BMS action interval. The physical invariant suite retains its previous tolerances.

The current default ignores contact entirely. Cars may overlap, and no collision response, damage or safety claim is modeled. Optional terminate mode retains the earlier footprint failure behavior for comparison. Lateral motion remains reduced line tracking, with no yaw/slip dynamics or complete lane-change tyre demand. Circuit curvature can cause sharp acceleration changes even with smooth following. There is no measured tyre, aero or weather calibration.

## Throughput and integration

| Measurement | Reference | Revised |
| --- | --- | --- |
| 2 cars, Monza, seed 42, dt 0.01, 10 simulated s | 2.56-3.04 wall s | 1.82-3.05 wall s |
| 20 cars, same scenario specification, 10 simulated s | 70.09 wall s | 46.38 wall s |
| Cold session reset | 0.07-0.15 s | 0.03-0.16 s |
| PPO, one car, 8 s episodes, 128 transitions | 11 transitions/s | 10-11 transitions/s |

The new reset distributions change actual field trajectories; the throughput comparison uses matching circuit, seed, count, duration and integration step, not identical every-tick forces. Shared host load also varies. Do not infer a guaranteed speedup. The 20-car reference remains CPU intensive and scales poorly. Long runs should measure their own throughput and parallelize independent episodes, without skipping physics.

Generation produced a five-second two-car JSONL dataset with the action mapping, model hash, resolved parameters and masks. A real CPU PPO smoke run collected 128 transitions, optimized, wrote a policy plus sidecar, and successfully reloaded it for evaluation. The evaluation episode was truncated at its eight-second limit. This establishes integration only. It does not establish useful energy strategy or driving skill.

`make race-check` passes 95 tests plus format, lint, strict types, comment checks and frontend checks. `make race-browser-check` passes both live-controls and forwarded-connection tests using isolated ports 18860/18861. The new preset is exercised. `bun run build` passes. Browser rendering logic is unchanged apart from the preset selector; no renderer FPS improvement is claimed or benchmarked. The PR's checks tab is the authoritative remote CI status for its latest commit.

## Reproduce and extend

```sh
uv run python scripts/race_experiments.py --seeds 11 23 37 --output revised.json
uv run python scripts/race_experiments.py --seeds 101 202 303 --cases pass abort --dt 0.005 --output fine.json
uv run python scripts/race_experiments.py --seeds 101 202 303 --cases pass abort --dt 0.02 --output coarse.json
uv run --with matplotlib==3.11.2 python scripts/race_plot.py --before original.json --after revised.json --output comparison.png
```

For the original comparison, export `ee51224` into an isolated directory with `git archive`, then run the same experiment script with `PYTHONPATH` selecting that export's `packages/core`, `packages/contracts` and `apps/api`. This exercises the original code without modifying another worktree. Keep the JSON traces and resolved manifests with the experiment. The plot shows actual force-integrated motion and labelled intention transitions, not an animation script.

For broader BMS evaluation, freeze training circuits and scenario families first. Train on Monza plus low-wetness settings and evaluate on held-out circuit families such as Silverstone plus held-out wetness/driver ranges. Use at least 30 independent episode seeds and several training seeds, comparing conserve, neutral and the automatic driver profile under matched scenarios. `race.py evaluate` supports fixed profiles and saved policies; automatic-profile baselines use `RaceSession` without a BMS override. Treat the three held-out seeds above as smoke/regression coverage only.

Record completion, truncation, physical failure, finish position, race time, energy constraints and actual retained-pass events. Report binomial uncertainty for contacts/completion and bootstrap intervals over independent episodes for continuous metrics. Zero failures in twelve short trials still gives an approximate one-sided 95% upper failure-rate bound of 22%, so it is weak evidence of reliability. Do not bootstrap adjacent frames as independent data. Compare racecraft separately from learned battery management because the learned action has no passing authority.

Ablate driver, vehicle, sensor, surface and wind scales individually at zero, plus wake on/off, while retaining matched seeds. Sweep headway and braking confidence using explicit driver overrides; compare baseline/mild/training/stress presets and alternate timesteps. Report all failed and truncated cases. Calibrate distributions against measured data before making real-car or sim-to-real claims.
