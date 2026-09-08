# AFTERLAP

Electrical energy and overtake decision support. Simulator-only, synthetic fixtures unless a document says otherwise.

Product code lives at the repository root. Specifications, plans, design mockups, the presentation deck and handoffs live in [`docs/`](docs/README.md).

## Layout

| Path | Role |
|---|---|
| `apps/api` | FastAPI control plane |
| `apps/web` | Engineer console, lab, driver display |
| `packages/contracts` | Authoritative Pydantic models and generated schemas |
| `packages/core` | Simulation, rules, estimation, planning, learning, tracks |
| `workers` | Session and batch process launchers |
| `configs` | Cars, tracks, rules, scenarios, planning, learning |
| `scripts` | Doctor, migrate, demo, release, CI helpers |
| `tests` | pytest suites |
| `infra` | Compose, images, nginx |
| `docs` | Specs, design, deck, handoffs |

## Commands

Python 3.12 and Node 24. Install with frozen locks:

```
uv sync --frozen --all-packages
pnpm install --frozen-lockfile
```

```
uv run python -m afterlap_core.cli doctor
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest tests/contracts tests/numerics
uv run python docs/tools/validate_package.py
pnpm --filter @afterlap/web lint
pnpm --filter @afterlap/web typecheck
pnpm --filter @afterlap/web test
pnpm --filter @afterlap/web build
```

CI runs the same gates. There is no local-only check.

## Docs

Start at [docs/README.md](docs/README.md). Preview design mockups with:

```
python -m http.server 8765 --bind 127.0.0.1 --directory docs/design/mockups
```
