# Simulator working agreement

This repository tree contains only the standalone race simulator. Develop on feature branches from `simulator`, make checkpoint commits, and open pull requests targeting `simulator`. Keep CI green. Do not merge simulator work into `main`.

- Python 3.12 with uv, Bun 1.3 with Next.js.
- SI units internally, display conversions at the UI boundary.
- Simulator truth never crosses into controller or UI observations.
- Unknown measurements stay unavailable.
- Preserve physical invariants and deterministic checkpoint replay.
- No code comments except functional lint and type directives.
- No fabricated measurements, trained performance claims, or calibrated-vehicle claims.
