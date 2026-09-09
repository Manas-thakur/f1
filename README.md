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

Python 3.12 and Bun 1.3. Install with frozen locks:

```
uv sync --frozen --all-packages
bun install --frozen-lockfile
```

```
uv run python -m afterlap_core.cli doctor
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest tests/contracts tests/numerics
uv run python docs/tools/validate_package.py
bun run lint
bun run typecheck
bun run test
bun run build
```

CI runs the same gates. There is no local-only check.

## Windows, Linux and macOS

Run repository commands through `uv run` and `bun run`; do not call `.venv/bin/python` or
`.venv/Scripts/python.exe` from shared scripts or instructions. The commands above are identical in
PowerShell, bash and zsh. Paths stored in contracts and API payloads use `/` as the portable separator,
while filesystem access goes through `pathlib.Path`.

GitHub Actions runs the complete suite on Linux and a portability gate on Windows and macOS. Docker
Desktop with Linux containers is the canonical numerical runtime on Windows; native Windows remains
supported for development, contracts, API, web and lightweight simulation tests.

## Docs

Start at [docs/README.md](docs/README.md). Preview design mockups with:

```
python -m http.server 8765 --bind 127.0.0.1 --directory docs/design/mockups
```
