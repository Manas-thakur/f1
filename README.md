# Race simulator

A standalone circuit race simulator with up to 20 cars, 23 Crowdflow layouts, battery controls, live telemetry, and a Gymnasium environment for reinforcement learning.

This project lives only on the `simulator` branch, with independent Git history. Develop changes in feature branches and open pull requests targeting `simulator`. Keep checkpoint commits and do not merge simulator work into `main`.

## Start

```sh
git switch simulator
make install
make race
```

`make dev` also starts the simulator. Keep the terminal running and open [the race view](http://127.0.0.1:18760/race). When working remotely, forward port **18760** only. Ctrl+C stops both processes. No database is required.

For Docker, use `make race-up`. Run `make race-down` before switching to native startup because both modes use the same ports.

## 3D race view

The circuit view opens with a chase camera. Start the race to receive car observations. Until sensors report a position, the scene shows the track without inventing car locations.

| Control | Action |
| --- | --- |
| Chase / 1 | Follow the selected car from behind |
| First person / 2 | Look forward from the selected car at driver eye level |
| Car orbit / 3 | Inspect the selected car from any angle |
| Full circuit / 4 or F | Fit the whole circuit |
| Left drag | Orbit; releases chase or cockpit camera |
| Right drag or Shift + drag | Pan |
| Wheel / trackpad pinch | Zoom |
| One finger / two fingers | Orbit / pan and pinch to zoom |
| + and −, including Command or Ctrl | Zoom while the scene has keyboard focus |
| Click a car or classification row | Select a car |
| Double-click the scene | Center an orbit around the selected car |
| Reset view | Resume the chase camera |
| ↑ / ↓ | Watch the car ahead / behind in current race order; wrap from first to last |
| Minimap / M | Toggle the circuit overview and selected-car marker |
| Fullscreen | Expand the scene, overlays and race controls |
| Hamburger | Open race settings in a docked sidebar |
| Float / Dock | Float the settings over the world or reserve space beside it |
| Drag settings header / edges | Move or resize the settings panel |
| Arrow keys on settings handle | Move the floating panel; Shift moves it farther |

The renderer uses local procedural car models, physically based materials, sunlight, shadows, and illustrative trackside scenery. Car motion interpolates a short buffer of received observations continuously without predicting future telemetry. The minimap uses the same rendered positions. The camera follows the selected car through overtakes and keeps its view when switching cars. Circuit artwork remains flat and scaled, not a surveyed recreation of the venue. High graphics includes shadows and full resolution; Performance reduces resolution and omits shadows. Software graphics devices select Performance automatically. Graphics require WebGL 2; the race controls remain accessible if graphics are unavailable.

### Animation speed and simulation pace

The speedometer reports speed in simulation time. PACE in the scene reports simulation seconds per real second, measured from received frames. For example, a 0.25× pace makes a car reporting 120 km/h cover about 30 km per real hour of viewing. The playback selector requests a target; it cannot make the physics engine compute faster than the available CPU. Twenty cars at 100 Hz can run below real time. Fewer cars reduce the physics workload; Performance graphics reduces browser rendering cost. Neither changes the physical speed measurement.

Rendering uses a short adaptive observation buffer to avoid accelerating and stopping at every packet. Pausing and restoring checkpoints update the view immediately. A network interruption holds the last known position rather than inventing future movement.

All playback buttons, classification, minimap and telemetry stay inside the scene. Classification has its own scroll area. Opening docked settings shrinks the desktop scene; on small screens settings overlay it. The old `/race/control` URL redirects to the single race page.

The landscape includes [local CC0 assets](apps/web/public/race-assets/ATTRIBUTION.md), detailed nearby trees, covered grandstands with animated spectators, catch fencing, circuit-specific surroundings and rotating wheel spokes. See [circuit research and rendering notes](docs/CIRCUIT_SCENERY.md) for all 23 references and interpretation limits. CPU braking preview and track sampling use cached Numba kernels; the first start may take longer while they compile.

For browser tests against a separately started worktree, set `RACE_TEST_URL=http://127.0.0.1:<port>` when running `make race-browser-check`.

## Generate and train

```sh
make race-generate CIRCUIT=monza CARS=20
make race-generate CIRCUIT=monza CARS=20 LAPS=3
make race-train CIRCUIT=monza CARS=20 STEPS=10000
uv run python scripts/race.py catalogue
uv run python scripts/race.py schema
```

When `LAPS` is omitted, each circuit uses its sourced Grand Prix distance. Set `LAPS` for a custom distance. The catalogue and schema commands expose every circuit preset, race setting, direct driver control, and normalized RL action field to scripts. See [RACE_SIMULATOR.md](RACE_SIMULATOR.md) for the physics model, observation/action contract, reward, datasets, training steps, and evaluation guidance. Training uses CPU PyTorch and Stable-Baselines3 PPO.

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

CI runs Python tests on Linux, macOS, and Windows, builds and tests the dashboard, and smoke-tests dataset generation and PPO training on every push and pull request to `simulator`.

The included physics and sensor modules are the dependencies needed by this simulator. Circuit geometry and vehicle parameters are synthetic and uncalibrated. The numerical checks establish implementation invariants, not real-car accuracy.
