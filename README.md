# Race simulator

A standalone circuit race simulator with up to 20 cars, 23 Crowdflow layouts, battery controls, live telemetry, and a Gymnasium environment for reinforcement learning.

This project lives only on the `simulator` branch, with independent Git history. Push checkpoint commits directly to this branch. Do not open pull requests or merge it into `main`.

## Start

```sh
git switch simulator
make install
make race
```

`make dev` also starts the simulator. Keep the terminal running and open [the circuit view](http://127.0.0.1:18760/race) or [race controls](http://127.0.0.1:18760/race/control). When working remotely, forward port **18760** only. Ctrl+C stops both processes. No database is required.

For Docker, use `make race-up`. Run `make race-down` before switching to native startup because both modes use the same ports.

## Generate and train

```sh
make race-generate CIRCUIT=monza CARS=20 LAPS=3
make race-train CIRCUIT=monza CARS=20 STEPS=10000
```

See [RACE_SIMULATOR.md](RACE_SIMULATOR.md) for the physics model, observation/action contract, reward, datasets, training steps, and evaluation guidance. Training uses CPU PyTorch and Stable-Baselines3 PPO.

## Project layout

| Path | Purpose |
| --- | --- |
| `packages/core` | Race engine, physics, sensors, and Gymnasium environment |
| `packages/contracts` | Simulator enums |
| `apps/api` | Standalone WebSocket race server |
| `apps/web` | Next.js circuit view and controls |
| `configs` | Circuit artwork, vehicle assumptions, and numerical fixtures |
| `scripts` | Generator, trainer, and local launcher |
| `tests` | Race, physics, energy balance, and convergence checks |
| `infra` | Docker simulator stack |

## Checks

```sh
make race-check
make race-browser-check
bun run build
```

CI runs Python tests on Linux, macOS, and Windows, builds and tests the dashboard, and smoke-tests dataset generation and PPO training on every push to `simulator`.

The included physics and sensor modules are the dependencies needed by this simulator. Circuit geometry and vehicle parameters are synthetic and uncalibrated. The numerical checks establish implementation invariants, not real-car accuracy.
