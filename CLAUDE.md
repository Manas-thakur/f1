# AFTERLAP: project working agreement

Working directory is this repository. Product code lives at the repository root.
Specifications live under `docs/` and are read-only reference material.

See [AGENTS.md](AGENTS.md) for engineering rules and [docs/README.md](docs/README.md) for the specification index.

## Repository and commit policy

This repository is `Manas-thakur/f1` on GitHub.

- Conventional-commit prefixes. One logical change per commit. Subject in imperative mood, 72 characters or fewer.
- Branch from `main`, open a PR, squash-merge after checks pass.
- Never push directly to `main`.

## Commands

```
uv sync --frozen --all-packages
uv run python -m afterlap_core.cli doctor
uv run python -m afterlap_api.cli serve
bun run --filter @afterlap/web dev
uv run pytest tests/contracts tests/numerics
bun run typecheck
bun run test
```

- SI units internally; display conversions only at the UI edge.
- Unknown values are `null` plus provenance and quality, never `0`.
- Simulator truth (`WorldState`) never crosses into controller or UI payloads.
- No mocked success: an unimplemented capability returns an explicit unavailable result.
- Never weaken or delete an invariant test to make a build pass.
