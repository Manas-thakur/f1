"""Runtime capability probing used by ``cli doctor`` and ``/health/ready``.

A check reports what it actually found. A missing numerical solver is reported
as unavailable and the affected capability is disabled; it is never replaced by
a stub that lets startup succeed.

Two different findings used to share one word. :class:`CapabilityState` is the
wire answer the browser and :class:`~afterlap_contracts.RuntimeCapabilities`
read: whether a capability can be used right now. :class:`CapabilityKind` is
the local reason, and it never crosses a contract boundary. An optional package
that was simply never installed is ``ABSENT``, which is a deployment choice and
not a fault. A capability that is present and answers wrongly -- an unwritable
artefact root, drifted contracts, a solve that deviates from its known answer
-- is ``FAILED``. ``cli doctor`` fails its gate on the second and merely prints
the first, so a default install without the optional dependency groups is a
passing install.
"""

from __future__ import annotations

import importlib
import os
import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from afterlap_contracts import CapabilityState

from .paths import Paths


class CapabilityKind(StrEnum):
    """Why a capability reports the state it reports.

    Core-only and deliberately not part of ``afterlap_contracts``: the wire
    enumeration answers *can this be used*, which an absent optional package
    and a broken installed one answer identically.
    """

    PRESENT = "present"
    ABSENT = "absent"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    state: CapabilityState
    detail: str
    version: str | None = None
    kind: CapabilityKind = CapabilityKind.PRESENT

    @property
    def ok(self) -> bool:
        return self.state is CapabilityState.AVAILABLE


_STATE_MARKERS: dict[CapabilityState, str] = {
    CapabilityState.AVAILABLE: "ok      ",
    CapabilityState.DEGRADED: "degraded",
    CapabilityState.UNAVAILABLE: "MISSING ",
}
_ABSENT_MARKER = "absent  "


@dataclass(slots=True)
class DoctorReport:
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.checks.append(result)

    @property
    def unavailable(self) -> list[CheckResult]:
        return [c for c in self.checks if c.state is CapabilityState.UNAVAILABLE]

    @property
    def degraded(self) -> list[CheckResult]:
        return [c for c in self.checks if c.state is CapabilityState.DEGRADED]

    @property
    def absent(self) -> list[CheckResult]:
        """Optional capabilities nobody installed. Reported, never a gate failure."""
        return [c for c in self.checks if c.kind is CapabilityKind.ABSENT]

    @property
    def failed(self) -> list[CheckResult]:
        """Capabilities that are installed and wrong, or that genuinely errored."""
        return [c for c in self.checks if c.kind is CapabilityKind.FAILED]

    def capability_map(self) -> dict[str, CapabilityState]:
        return {c.name: c.state for c in self.checks}

    def render(self) -> str:
        width = max((len(c.name) for c in self.checks), default=10)
        lines = []
        for check in self.checks:
            marker = _ABSENT_MARKER if check.kind is CapabilityKind.ABSENT else _STATE_MARKERS[check.state]
            version = f" ({check.version})" if check.version else ""
            lines.append(f"{marker}  {check.name:<{width}}  {check.detail}{version}")
        return "\n".join(lines)


def _module_check(
    name: str,
    module: str,
    *,
    required: bool,
    version_attr: str = "__version__",
    detail: str = "",
) -> CheckResult:
    try:
        loaded = importlib.import_module(module)
    except Exception as exc:
        return CheckResult(
            name=name,
            state=CapabilityState.UNAVAILABLE if required else CapabilityState.DEGRADED,
            detail=f"import failed: {type(exc).__name__}: {exc}",
            kind=CapabilityKind.FAILED if required else CapabilityKind.ABSENT,
        )
    version = str(getattr(loaded, version_attr, "") or "") or None
    return CheckResult(
        name=name, state=CapabilityState.AVAILABLE, detail=detail or "importable", version=version
    )


def check_python() -> CheckResult:
    major, minor = sys.version_info[:2]
    supported = (major, minor) == (3, 12)
    return CheckResult(
        name="python",
        state=CapabilityState.AVAILABLE if supported else CapabilityState.DEGRADED,
        detail=f"{platform.python_implementation()} on {platform.system()} {platform.machine()}"
        + ("" if supported else "; the pinned runtime is CPython 3.12"),
        version=platform.python_version(),
    )


def check_contracts() -> CheckResult:
    try:
        from afterlap_contracts.schema_export import check_drift

        problems = check_drift()
    except Exception as exc:
        return CheckResult(
            "contracts",
            CapabilityState.UNAVAILABLE,
            f"schema check failed: {exc}",
            kind=CapabilityKind.FAILED,
        )
    if problems:
        return CheckResult(
            "contracts",
            CapabilityState.DEGRADED,
            "generated artefacts are stale: " + "; ".join(problems),
            kind=CapabilityKind.FAILED,
        )
    from afterlap_contracts import CONTRACT_REVISION, SCHEMA_VERSION

    return CheckResult(
        "contracts",
        CapabilityState.AVAILABLE,
        f"schema {SCHEMA_VERSION}, contract revision {CONTRACT_REVISION}, generated files current",
    )


def check_storage(paths: Paths) -> CheckResult:
    try:
        paths.ensure()
        probe = paths.artifacts / ".doctor-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return CheckResult(
            "storage",
            CapabilityState.UNAVAILABLE,
            f"artefact root not writable: {exc}",
            kind=CapabilityKind.FAILED,
        )
    return CheckResult("storage", CapabilityState.AVAILABLE, f"writable at {paths.artifacts}")


def check_numerics() -> CheckResult:
    """Verify float64 numerics actually compute, not merely that NumPy imports.

    NumPy alone answers this. SciPy is an optional dependency group now, and a
    check that imported it would have reported the whole numerical stack -- a
    readiness requirement in ``/health/ready`` -- as unavailable on a default
    install that never needed track ingestion.
    """
    try:
        import numpy as np

        matrix = np.array([[4.0, 1.0], [1.0, 3.0]], dtype=np.float64)
        target = np.array([1.0, 2.0], dtype=np.float64)
        solution = np.linalg.solve(matrix, target)
        residual = float(np.max(np.abs(matrix @ solution - target)))
        if residual > 1e-12:
            return CheckResult(
                "numerics",
                CapabilityState.DEGRADED,
                f"solve residual {residual:.2e}",
                kind=CapabilityKind.FAILED,
            )
    except Exception as exc:
        return CheckResult(
            "numerics",
            CapabilityState.UNAVAILABLE,
            f"numerical stack failed: {exc}",
            kind=CapabilityKind.FAILED,
        )
    return CheckResult("numerics", CapabilityState.AVAILABLE, "float64 linear solve verified", np.__version__)


def check_solver() -> CheckResult:
    """Solve a small constrained OCP-shaped problem with a known answer.

    This is the G0 numerical spike. If CasADi is missing or its IPOPT plugin is
    unavailable, the planner reports a solver-unavailable status rather than
    silently substituting an unconstrained heuristic.

    A CasADi that was never installed is absent: the wire state stays
    ``UNAVAILABLE`` so no session claims a solver it does not have, but it is
    an install choice rather than a fault. A CasADi that is installed and
    returns the wrong answer is a failure.
    """
    try:
        ca = importlib.import_module("casadi")
    except Exception as exc:
        return CheckResult(
            "solver",
            CapabilityState.UNAVAILABLE,
            f"casadi unavailable: {exc}",
            kind=CapabilityKind.ABSENT,
        )

    try:
        x = ca.SX.sym("x")
        y = ca.SX.sym("y")
        variables = ca.vertcat(x, y)
        objective = (x - 3) ** 2 + (y - 2) ** 2
        constraint = x + y
        problem = {"x": variables, "f": objective, "g": constraint}
        solver = ca.nlpsol("spike", "ipopt", problem, {"ipopt.print_level": 0, "print_time": False})
        result = solver(x0=[0.0, 0.0], lbx=[0.0, 0.0], ubx=[10.0, 10.0], lbg=4.0, ubg=4.0)
        found = [float(v) for v in result["x"].full().ravel()]
    except Exception as exc:
        return CheckResult(
            "solver",
            CapabilityState.UNAVAILABLE,
            f"constrained solve failed: {exc}",
            kind=CapabilityKind.FAILED,
        )

    error = max(abs(found[0] - 2.5), abs(found[1] - 1.5))
    if error > 1e-6:
        return CheckResult(
            "solver",
            CapabilityState.DEGRADED,
            f"spike solved but deviates from the known answer by {error:.2e}",
            ca.__version__,
            kind=CapabilityKind.FAILED,
        )
    return CheckResult(
        "solver",
        CapabilityState.AVAILABLE,
        "constrained OCP spike matches its analytic solution (x=2.5, y=1.5)",
        ca.__version__,
    )


def check_acados() -> CheckResult:
    """acados is optional on Windows; the canonical target is the Linux image."""
    try:
        import acados_template  # noqa: F401
    except Exception:
        return CheckResult(
            "acados",
            CapabilityState.DEGRADED,
            "not installed; CasADi/IPOPT is the active continuous solver on this platform",
            kind=CapabilityKind.ABSENT,
        )
    return CheckResult("acados", CapabilityState.AVAILABLE, "acados template package importable")


def check_columnar_recording() -> CheckResult:
    """Parquet session recording, from the optional ``data`` dependency group."""
    try:
        import pyarrow as pa
    except Exception:
        return CheckResult(
            "recording",
            CapabilityState.DEGRADED,
            "pyarrow is not installed; sessions record to JSONL only and Parquet export is refused. "
            "The `data` dependency group installs it",
            kind=CapabilityKind.ABSENT,
        )
    return CheckResult(
        "recording",
        CapabilityState.AVAILABLE,
        "pyarrow importable; columnar session recording and Parquet export available",
        str(pa.__version__),
    )


def check_track_ingestion() -> CheckResult:
    """Real-circuit compilation, from the optional ``track-ingestion`` group."""
    versions: dict[str, str] = {}
    missing: list[str] = []
    for module in ("scipy", "pypdf"):
        try:
            loaded = importlib.import_module(module)
        except Exception:
            missing.append(module)
        else:
            versions[module] = str(getattr(loaded, "__version__", "") or "unknown")
    if missing:
        return CheckResult(
            "track_ingestion",
            CapabilityState.DEGRADED,
            f"{', '.join(missing)} not installed; centreline compilation and FIA overlay parsing are "
            "unavailable, while already compiled track packages still load. The `track-ingestion` "
            "dependency group installs them",
            kind=CapabilityKind.ABSENT,
        )
    return CheckResult(
        "track_ingestion",
        CapabilityState.AVAILABLE,
        "scipy and pypdf importable; centreline compilation and FIA overlay parsing available",
        f"scipy {versions['scipy']}, pypdf {versions['pypdf']}",
    )


def check_torch() -> CheckResult:
    result = _module_check("torch", "torch", required=False)
    if not result.ok:
        return result
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    return CheckResult("torch", CapabilityState.AVAILABLE, f"inference device {device}", torch.__version__)


def check_learning_stack() -> CheckResult:
    for module, label in (("gymnasium", "gymnasium"), ("stable_baselines3", "stable-baselines3")):
        result = _module_check(label, module, required=False)
        if not result.ok:
            return CheckResult(
                "learning",
                CapabilityState.DEGRADED,
                f"{label} unavailable: {result.detail}",
                kind=result.kind,
            )
    import gymnasium
    import stable_baselines3

    return CheckResult(
        "learning",
        CapabilityState.AVAILABLE,
        f"gymnasium {gymnasium.__version__}",
        stable_baselines3.__version__,
    )


DatabaseProbe = Callable[[str], None]

_database_probe: DatabaseProbe | None = None


def register_database_probe(probe: DatabaseProbe | None) -> DatabaseProbe | None:
    """Install the adapter that measures real database connectivity.

    The domain core owns no persistence driver, so it cannot open a connection
    itself. The infrastructure layer registers its adapter at import time; a
    core-only install leaves this unset and :func:`check_database` reports the
    backend as unprobed instead of inventing a verdict.

    A probe takes the configured URL, returns ``None`` when the backend
    answered, and raises otherwise. Returns the probe registered before this
    call so a caller can restore it.
    """
    global _database_probe
    previous = _database_probe
    _database_probe = probe
    return previous


def check_database(url: str | None = None) -> CheckResult:
    """Report the configured persistence backend without printing credentials."""
    configured = url or os.environ.get("AFTERLAP_DATABASE_URL", "")
    if not configured:
        return CheckResult(
            "database",
            CapabilityState.DEGRADED,
            "no AFTERLAP_DATABASE_URL configured; the runtime will use its local SQLite store",
        )
    scheme = configured.split("://", 1)[0]
    probe = _database_probe
    if probe is None:
        return CheckResult(
            "database",
            CapabilityState.DEGRADED,
            f"{scheme} backend was not probed; no database adapter is registered",
            kind=CapabilityKind.ABSENT,
        )
    try:
        probe(configured)
    except Exception as exc:
        return CheckResult(
            "database",
            CapabilityState.UNAVAILABLE,
            f"{scheme} backend unreachable: {type(exc).__name__}",
            kind=CapabilityKind.FAILED,
        )
    return CheckResult("database", CapabilityState.AVAILABLE, f"{scheme} backend reachable")


DEFAULT_CHECKS: tuple[Callable[[], CheckResult], ...] = (
    check_python,
    check_contracts,
    check_numerics,
    check_columnar_recording,
    check_track_ingestion,
    check_solver,
    check_acados,
    check_torch,
    check_learning_stack,
    check_database,
)


def run_doctor(paths: Paths | None = None) -> DoctorReport:
    """Run every capability probe. Never raises; a failure is a reported state."""
    resolved = paths or Paths.default()
    report = DoctorReport()
    for check in DEFAULT_CHECKS:
        try:
            report.add(check())
        except Exception as exc:
            report.add(
                CheckResult(
                    check.__name__,
                    CapabilityState.UNAVAILABLE,
                    f"probe error: {exc}",
                    kind=CapabilityKind.FAILED,
                )
            )
    report.add(check_storage(resolved))
    return report


def redact(text: str) -> str:
    """Strip anything that looks like a credential before logging."""
    if "://" not in text:
        return text
    scheme, rest = text.split("://", 1)
    if "@" in rest:
        rest = rest.split("@", 1)[1]
    return f"{scheme}://{rest}"


__all__ = [
    "DEFAULT_CHECKS",
    "CapabilityKind",
    "CheckResult",
    "DatabaseProbe",
    "DoctorReport",
    "check_acados",
    "check_columnar_recording",
    "check_contracts",
    "check_database",
    "check_learning_stack",
    "check_numerics",
    "check_python",
    "check_solver",
    "check_storage",
    "check_torch",
    "check_track_ingestion",
    "redact",
    "register_database_probe",
    "run_doctor",
]
