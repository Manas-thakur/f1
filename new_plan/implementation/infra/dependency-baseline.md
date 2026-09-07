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
| Node.js / pnpm | v24.19.0 / 10.34.5 |

## Installed Python versions

| Package | Installed version |
|---|---|
| pydantic | 2.13.5 |
| numpy | 2.5.3 |
| scipy | 1.18.1 |
| casadi | 3.8.0 |
| torch | 2.14.0+cpu |
| gymnasium | 1.3.0 |
| stable-baselines3 | 2.9.0 |
| scikit-learn | 1.9.0 |
| fastapi | 0.141.1 |
| uvicorn | 0.52.4 |
| sqlalchemy | 2.0.52 |
| alembic | 1.19.2 |
| psycopg | 3.3.5 |
| pyarrow | 25.0.1 |
| prometheus-client | 0.26.0 |
| typer | 0.27.2 |
| pyyaml | 6.0.3 |
| websockets | 17.1 |
| tensorboard | 2.21.0 |
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
uv run --project new_plan/implementation python -m afterlap_core.cli doctor
```

## Solver decision (deviation from the stack document, recorded)

`00_program/TECH_STACK.md` names acados as the compiled continuous-OCP solver and
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
uv run python -m pytest tests/contracts tests/numerics
pnpm install --frozen-lockfile
pnpm --filter @afterlap/web typecheck
pnpm --filter @afterlap/web test
pnpm --filter @afterlap/web build
pnpm --filter @afterlap/web test:e2e
```

`--all-extras` is required: `torch`, `stable-baselines3`, `gymnasium`,
`scikit-learn` and `casadi` are declared as the `learning` and `solver` extras so
a contracts-only consumer can install a light dependency set.

## Notes

- Workspace members install in editable mode. After adding a new package
  directory, run `uv sync ... --reinstall-package <name>` once so the built
  wheel is refreshed.
- No prereleases are installed. No package was pulled from a development branch.
- `AFTERLAP_DATABASE_URL` is unset by default; the runtime uses its local SQLite
  store and `doctor` reports the database check as degraded rather than failing.
