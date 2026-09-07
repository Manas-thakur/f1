"""Runtime capability probing used by ``cli doctor`` and ``/health/ready``.

A check reports what it actually found. A missing numerical solver is reported
as unavailable and the affected capability is disabled; it is never replaced by
a stub that lets startup succeed.
"""

from __future__ import annotations

import importlib
import os
import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from afterlap_contracts import CapabilityState

from .paths import Paths


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    state: CapabilityState
    detail: str
    version: str | None = None

    @property
    def ok(self) -> bool:
        return self.state is CapabilityState.AVAILABLE


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

    def capability_map(self) -> dict[str, CapabilityState]:
        return {c.name: c.state for c in self.checks}

    def render(self) -> str:
        width = max((len(c.name) for c in self.checks), default=10)
        lines = []
        for check in self.checks:
            marker = {
                CapabilityState.AVAILABLE: "ok      ",
                CapabilityState.DEGRADED: "degraded",
                CapabilityState.UNAVAILABLE: "MISSING ",
            }[check.state]
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
        return CheckResult("contracts", CapabilityState.UNAVAILABLE, f"schema check failed: {exc}")
    if problems:
        return CheckResult(
            "contracts",
            CapabilityState.DEGRADED,
            "generated artefacts are stale: " + "; ".join(problems),
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
        return CheckResult("storage", CapabilityState.UNAVAILABLE, f"artefact root not writable: {exc}")
    return CheckResult("storage", CapabilityState.AVAILABLE, f"writable at {paths.artifacts}")


def check_numerics() -> CheckResult:
    """Verify float64 numerics actually compute, not merely that NumPy imports."""
    try:
        import numpy as np
        import scipy.linalg as sla

        matrix = np.array([[4.0, 1.0], [1.0, 3.0]], dtype=np.float64)
        solution = sla.solve(matrix, np.array([1.0, 2.0], dtype=np.float64))
        residual = float(np.max(np.abs(matrix @ solution - np.array([1.0, 2.0]))))
        if residual > 1e-12:
            return CheckResult("numerics", CapabilityState.DEGRADED, f"solve residual {residual:.2e}")
    except Exception as exc:
        return CheckResult("numerics", CapabilityState.UNAVAILABLE, f"numerical stack failed: {exc}")
    return CheckResult("numerics", CapabilityState.AVAILABLE, "float64 linear solve verified", np.__version__)


def check_solver() -> CheckResult:
    """Solve a small constrained OCP-shaped problem with a known answer.

    This is the G0 numerical spike. If CasADi is missing or its IPOPT plugin is
    unavailable, the planner reports a solver-unavailable status rather than
    silently substituting an unconstrained heuristic.
    """
    try:
        import casadi as ca
    except Exception as exc:
        return CheckResult("solver", CapabilityState.UNAVAILABLE, f"casadi unavailable: {exc}")

    try:
        # minimise (x-3)^2 + (y-2)^2 subject to x + y == 4, x >= 0, y >= 0.
        # Known analytic solution: x = 2.5, y = 1.5.
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
        return CheckResult("solver", CapabilityState.UNAVAILABLE, f"constrained solve failed: {exc}")

    error = max(abs(found[0] - 2.5), abs(found[1] - 1.5))
    if error > 1e-6:
        return CheckResult(
            "solver",
            CapabilityState.DEGRADED,
            f"spike solved but deviates from the known answer by {error:.2e}",
            ca.__version__,
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
        )
    return CheckResult("acados", CapabilityState.AVAILABLE, "acados template package importable")


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
            return CheckResult("learning", CapabilityState.DEGRADED, f"{label} unavailable: {result.detail}")
    import gymnasium
    import stable_baselines3

    return CheckResult(
        "learning",
        CapabilityState.AVAILABLE,
        f"gymnasium {gymnasium.__version__}",
        stable_baselines3.__version__,
    )


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
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(configured, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("select 1"))
        engine.dispose()
    except Exception as exc:
        return CheckResult(
            "database",
            CapabilityState.UNAVAILABLE,
            f"{scheme} backend unreachable: {type(exc).__name__}",
        )
    return CheckResult("database", CapabilityState.AVAILABLE, f"{scheme} backend reachable")


DEFAULT_CHECKS: tuple[Callable[[], CheckResult], ...] = (
    check_python,
    check_contracts,
    check_numerics,
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
            report.add(CheckResult(check.__name__, CapabilityState.UNAVAILABLE, f"probe error: {exc}"))
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
    "CheckResult",
    "DoctorReport",
    "check_acados",
    "check_contracts",
    "check_database",
    "check_learning_stack",
    "check_numerics",
    "check_python",
    "check_solver",
    "check_storage",
    "check_torch",
    "redact",
    "run_doctor",
]
