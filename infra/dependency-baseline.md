# Dependency baseline and G0 installation spike

Frozen on 8 September 2026. Versions below are what `uv sync --frozen` actually
installed and what the tests in this repository were run against. They are not
claims about the newest release of each project.

## Measured hardware and runtime

| Property | Value |
|---|---|
| Operating system | Windows 11 Home Single Language 10.0.26200 |
| Python | CPython 3.12.14 (uv-managed) |
| Package manager | uv 0.12.10 |
| Bun | 1.3.14 |

## Installed Python versions

| Package | Installed version |
|---|---|
| pydantic | 2.13.5 |
| numpy | 2.5.3 |
| scipy | 1.18.1 (`track-ingestion` group) |
| casadi | 3.8.0 (`solver` group) |
| torch | 2.14.0+cpu (`learning` group) |
| gymnasium | 1.3.0 (`learning` group) |
| stable-baselines3 | 2.9.0 (`learning` group) |
| sqlalchemy | 2.0.52 |
| alembic | 1.19.2 |
| psycopg | 3.3.5 |
| pyarrow | 25.0.1 (`data` group) |
| pypdf | 6.18.0 (`track-ingestion` group) |
| typer | 0.27.2 |
| pyyaml | 6.0.3 |
| tensorboard | 2.21.0 (`learning` group) |
| pytest | 9.1.1 |
| hypothesis | 6.167.1 |
| ruff | 0.16.6 |
| mypy | 2.3.1 |

The authoritative record is `uv.lock`; this table is the human-readable summary.

## G0 numerical spike

`afterlap_core.diagnostics.check_solver` solves a small constrained problem with a
known analytic answer inside the packaged runtime:

```
minimise (x-3)^2 + (y-2)^2   subject to   x + y = 4,  0 <= x,y <= 10
analytic optimum: x = 2.5, y = 1.5
```

Result on this machine: **solved to within 1e-6 of the analytic optimum** using
CasADi 3.8.0 with the bundled IPOPT plugin. Command:

```
uv run python -m afterlap_core.cli doctor
```

## Solver decision (deviation from the stack document, recorded)

`program/TECH_STACK.md` names acados as the compiled continuous-OCP solver and
notes that the canonical numerical runtime is a Linux image under Docker Desktop.

**Observed:** acados does not ship a Windows wheel; `acados_template` is not
installed in this environment. Building acados from a pinned commit requires a
Linux toolchain that is not present on the development machine used here.

**Decision:** CasADi + IPOPT is the active continuous solver for this release.
It is the same symbolic front end the stack document already selects, and it
solves the same fixed-discrete-profile subproblems; only the compiled QP/SQP
backend differs. `doctor` reports acados as *degraded, not installed* rather
than pretending it is present, and the planner's solver identity is recorded in
every decision record so a later acados build is a visible change, not a silent
one.

**Consequence:** solver latency figures in the release report are CasADi/IPOPT
figures on the hardware above. They must not be quoted as acados figures. The
acados path remains the documented upgrade and is listed as remaining work.

## Command contracts

```
uv sync --frozen --all-packages --all-extras
uv run python -m afterlap_core.cli doctor
uv run python -m afterlap_core.cli generate-contracts --check
uv run python -m afterlap_api.cli serve
uv run python -m pytest tests/contracts tests/numerics
bun install --frozen-lockfile
bun run --filter @afterlap/web dev

bun run typecheck
bun run test
bun run build
bun run test:e2e
```

## Dependency groups

The repository root is a non-published uv workspace coordinator with no
`[project]` of its own. Optional weight is separated into groups, each of which
maps onto an extra of `afterlap-core` (or of `afterlap-api`):

| Group | Installs | What it buys |
|---|---|---|
| `runtime` | `afterlap-api[postgres]` (psycopg) | the PostgreSQL driver |
| `data` | pyarrow | columnar session recording and Parquet export |
| `solver` | casadi | the continuous optimal-control solver |
| `track-ingestion` | scipy, pypdf | centreline compilation and FIA overlay parsing |
| `learning` | torch, gymnasium, stable-baselines3, tensorboard | SAC training and the value estimator |
| `dev` | pytest, ruff, mypy, hypothesis, httpx | the toolchain |

`default-groups = ["runtime", "dev"]`, so a plain `uv sync` installs a working
control plane and nothing heavier. Every group is genuinely optional: the
imports that need these packages are deferred, and `doctor` reports an
uninstalled one as **absent** rather than as a failure, so the default install
passes the start gate. CI installs
`--group data --group solver --group track-ingestion` because the test suite
exercises all three; the cross-platform job deliberately uses the default
install, which is what proves the deferral holds.

`scikit-learn` was removed: it was declared for calibration and imported
nowhere. `tensorboard` stays in `learning` only; it is reachable solely through
the `tensorboard_log` argument of stable-baselines3.

## Notes

- Workspace members are `packages/contracts`, `packages/core`,
  `packages/application`, `packages/infrastructure` and `apps/api`. Each builds
  with a pinned `uv_build` backend; every one is pure Python. Adding a package
  directory means adding it to `[tool.uv.workspace] members`, to
  `[tool.uv.sources]`, and to the manifest layer of `infra/api.Dockerfile`.
- Workspace members install in editable mode. After adding a new package
  directory, run `uv sync ... --reinstall-package <name>` once so the built
  wheel is refreshed.
- No prereleases are installed. No package was pulled from a development branch.
- `AFTERLAP_DATABASE_URL` is unset by default; the runtime uses its local SQLite
  store and `doctor` reports the database check as degraded rather than failing.
