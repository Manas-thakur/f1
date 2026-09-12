# AFTERLAP

Electrical energy and overtake decision support. Simulator-only, synthetic fixtures unless a document says otherwise.

Product code lives at the repository root. Specifications, plans, design mockups, the presentation deck and handoffs live in [`docs/`](docs/README.md).

## Layout

| Path | Role |
|---|---|
| `apps/api` | Python control-plane CLI and session runtime |
| `apps/web` | Next.js engineer console, lab, driver display, and `/api/v1` |
| `packages/application` | Session runtime ports and out-of-process spawn |
| `packages/infrastructure` | Persistence adapters |
| `packages/contracts` | Authoritative Pydantic models and generated schemas |
| `packages/core` | Simulation, rules, estimation, planning, learning, tracks |
| `workers` | Session and batch process launchers |
| `configs` | Cars, tracks, rules, scenarios, planning, learning |
| `scripts` | Doctor, migrate, demo, release, CI helpers |
| `tests` | pytest suites |
| `infra` | Compose catalog, Linux images, unique host ports |
| `Makefile` | Local stack orchestration (`make up`) |
| `docs` | Specs, design, deck, handoffs |
| `AFTERLAP_CONTEXT.md` | End-to-end context dump of the product |

## Commands

Python 3.12 and Bun 1.3. Install with frozen locks, or start the packaged
stack with Make:

```
make env
make up
make demo
make down
```

Host ports are 18473 (web), 19284 (runtime), 17539 (postgres). They are
pinned in `infra/ports.env` so they do not collide with 3000, 8000, 8080 or
5432. See [docs/operations/LOCAL_STACK.md](docs/operations/LOCAL_STACK.md).

Install and check without containers:

```
uv sync --frozen --all-packages
bun install --frozen-lockfile
```

```
uv run python -m afterlap_core.cli doctor
uv run python -m afterlap_api.cli --help
uv run python -m afterlap_api.cli serve
bun run --filter @afterlap/web dev

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

GitHub Actions runs the complete suite on Linux and a portability gate on Windows and macOS. The local packaged stack on macOS is `make up` (Apple container via `ac`). `infra/docker-compose.yml` is the Linux compose catalog. Native Windows remains supported for development, contracts, API, web and lightweight simulation tests.


## Docs

Start at [docs/README.md](docs/README.md). The whole-tree context dump is [AFTERLAP_CONTEXT.md](AFTERLAP_CONTEXT.md). Preview design mockups with:

```
python -m http.server 8765 --bind 127.0.0.1 --directory docs/design/mockups
```
