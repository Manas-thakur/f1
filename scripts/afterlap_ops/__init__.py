"""Operations support for AFTERLAP: packaging, runbook scripts and drills.

This package holds code that belongs to *deployment and recovery* rather than
to the product's domain modules. It is deliberately outside `packages/` and
`apps/`:

* `quota` implements the disk-budget guard the architecture requires
  ("Disk full -> stop experiment jobs first, preserve operational evidence,
  then withdraw if necessary"). **The application does not yet enforce this.**
  There is no quota check anywhere in `apps/` or `packages/`; this module is
  the working implementation plus the failure drill that exercises it, and
  `handoffs/A14-integration-patch.md` carries the exact hunks that wire it into
  `routes/experiments.py` and the batch worker. Nothing here silently
  substitutes for an application guarantee — the batch worker entrypoint in
  `scripts/batch_worker_main.py` genuinely uses it, and the API route does not
  until the patch lands.
* `apiclient` is a dependency-free HTTP client over `urllib` for the runbook
  scripts, so `scripts/demo.py` can drive a live server from inside the
  packaged image without adding a request library to the runtime graph.

Import it by putting `scripts/` on `sys.path` (`tests/operations/conftest.py`
does exactly that); it is not a workspace member and is not installed.
"""

from __future__ import annotations

__all__ = ["apiclient", "quota"]
