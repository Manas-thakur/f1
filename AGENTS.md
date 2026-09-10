# AFTERLAP working agreement

Product code lives at the repository root. Specifications live under `docs/` and are reference material.

## Layout

- Python 3.12 via `uv` at the repository root. Run `uv run ...`. Control-plane work is `python -m afterlap_api.cli`.
- Next.js (Bun 1.3) in `apps/web`: pages and `/api/v1` route handlers that invoke the Python CLI.
- Docs: `docs/program`, `docs/contracts`, module specs, `docs/design`, `docs/deck`, `docs/handoffs`.
- Handoffs: `docs/handoffs/<agent-id>.md`.

## Engineering rules

- SI units internally. Display conversions only at the UI edge.
- Unknown values are `null` plus provenance and quality, never `0`.
- Simulator truth (`WorldState`) never crosses into controller or UI payloads.
- An unimplemented capability returns an explicit unavailable result.
- No fabricated measurements, benchmark wins, trained weights or certification claims.
- Never weaken or delete an invariant test to make a build pass.
- No comments in source files. Allowed: license blocks and tool pragmas (`noqa`, `type: ignore`, `biome-ignore`).
- Public functions have type hints. CI enforces Ruff, mypy, ESLint, tsc, pytest and Vitest.

## Invariants

- Simulation truth is isolated from controller observations and frontend operational views.
- Team-to-car network control is outside real-F1 scope. The connected driver screen is simulation-only.
- Hard modelled constraints are enforced outside RL. Human selection does not bypass them.
- No live RL exploration, silent model replacement or automatic promotion.
- Browser prototypes keep the visible illustrative-data notice.
