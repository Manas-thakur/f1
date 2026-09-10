#!/usr/bin/env python
"""Thin wrapper over ``afterlap_core.cli doctor``.

The capability probes belong to the core package and stay there — this file
adds nothing to them and deliberately does not re-implement any check. What it
adds is a stable *operational* entry point:

* it works without an installed console script, so the compose image and a
  bare checkout invoke the same command;
* it forwards ``--json`` and ``--strict`` untouched;
* it exits non-zero when a capability has *failed*, which is what makes it
  usable as a container start gate. An optional external or native capability
  that is simply not installed is reported as absent and does not fail the
  gate; only `--strict` treats absence as a failure.

    python scripts/doctor.py
    python scripts/doctor.py --json
    python scripts/doctor.py --strict      # also non-zero on absent or degraded

`doctor` prints no secrets: `check_database` reports only the URL scheme and
`afterlap_core.diagnostics.redact` strips any userinfo before anything is
logged. `tests/operations/test_security.py` asserts that on real output.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_workspace_on_path() -> None:
    """Allow `python scripts/doctor.py` from a checkout without an install."""
    root = Path(__file__).resolve().parents[1]
    for candidate in (
        root / "packages" / "core",
        root / "packages" / "contracts",
        root / "packages" / "infrastructure",
        root / "packages" / "application",
        root / "apps" / "api",
    ):
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


def main(argv: list[str] | None = None) -> int:
    try:
        from afterlap_core.cli import app
    except ModuleNotFoundError:
        _ensure_workspace_on_path()
        from afterlap_core.cli import app

    args = list(sys.argv[1:] if argv is None else argv)
    try:
        result = app(["doctor", *args], standalone_mode=False)
    except SystemExit as exit_code:  # pragma: no cover - argument errors only
        return int(exit_code.code or 0)
    except Exception as exc:
        code = getattr(exc, "exit_code", None)
        if code is None:
            raise
        return int(code)
    return int(result) if isinstance(result, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
