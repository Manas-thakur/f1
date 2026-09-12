# Race simulator

Standalone circuit race simulator with battery deployment controls and a Gymnasium environment for reinforcement learning.

This project is maintained only on the `simulator` branch. It has independent Git history and is not merged into `main`.

```sh
uv sync --frozen --all-packages
uv run python scripts/race.py generate --circuit monza --cars 2 --laps 1 --duration 5 --output /tmp/race.jsonl
```

The engine, configurations, circuit artwork, observation model, and numerical tests included here are the dependencies required to run the simulator. Circuit geometry and vehicle parameters are synthetic and uncalibrated.
