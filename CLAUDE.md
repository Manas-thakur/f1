# AFTERLAP — project working agreement

Working directory: `C:\Work\f1`. Product code lives **only** under `new_plan/implementation/`.
Specifications live under `new_plan/` and are read-only reference material.

## Repository and commit policy

This repository is `Manas-thakur/f1` on GitHub, created and maintained through `gh`.

**Authorship rules (mandatory):**

- All commits use author and committer `manas-thakur <manas@ocally.co>`.
- Never set an AI assistant as the commit author or committer.
- Never add `Co-Authored-By:` trailers naming an AI assistant.
- Never mention Claude, Anthropic, or any AI tool in commit messages, PR titles,
  PR bodies, branch names, or release notes.
- Never add "Generated with ..." footers to commits or pull requests.

Local enforcement:

```
git config user.name  "manas-thakur"
git config user.email "manas@ocally.co"
```

**Commit style:** small, organised, conventional-commit prefixed
(`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`, `perf:`, `build:`).
One logical change per commit. Subject in imperative mood, <= 72 characters.

**Branch and PR flow (mandatory for every feature):**

1. Branch from `main`: `git switch -c <type>/<short-topic>`.
2. Commit organised changes on that branch.
3. `git push -u origin <branch>`.
4. `gh pr create --base main --title "..." --body "..."` — describe scope, tests run
   and results. No AI attribution anywhere in the PR.
5. `gh pr merge <n> --squash --delete-branch` once checks/review pass.

Never push directly to `main` after the initial repository bootstrap.

## Engineering rules

- Python 3.12 via `uv` workspace at `new_plan/implementation/`.
  Run commands with `uv run --project new_plan/implementation ...` or the venv directly.
- SI units internally; display conversions only at the UI edge.
- Unknown values are `null` plus provenance and quality — never `0`.
- Simulator truth (`WorldState`) never crosses into controller or UI payloads.
- No mocked success: an unimplemented capability returns an explicit unavailable result.
- No fabricated measurements, benchmark wins, trained weights or certification claims.
- Never weaken or delete an invariant test to make a build pass.
