"""An optional dependency nobody installed is not a fault, and the gate says so.

``pyarrow``, ``scipy`` and ``pypdf`` moved into optional dependency groups.
While the doctor had one word for both findings, a default install reported
``numerics`` as unavailable: ``cli doctor`` exited 1 and ``/health/ready``
answered 503, because ``numerics`` is one of the three capabilities in
``REQUIRED_FOR_READINESS``. These claims pin the separation. An optional
package that was never installed is ``ABSENT`` and passes the gate; a
capability that is installed and answers wrongly, or a probe that errored, is
``FAILED`` and does not.

Nothing here uninstalls anything: the virtual environment is shared. Absence is
simulated by refusing the import in ``sys.meta_path`` for the duration of one
claim, and the evicted modules are put back afterwards.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

from afterlap_contracts import CapabilityState
from afterlap_core import diagnostics
from afterlap_core.cli import app
from afterlap_core.diagnostics import (
    CapabilityKind,
    CheckResult,
    DoctorReport,
    check_columnar_recording,
    check_numerics,
    check_solver,
    check_track_ingestion,
    run_doctor,
)

OPTIONAL_PACKAGES = ("casadi", "pyarrow", "scipy", "pypdf")


class _ImportBlocker:
    """Refuse named top-level packages so a probe sees a real ImportError."""

    def __init__(self, names: Sequence[str]) -> None:
        self.names = frozenset(names)

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in self.names:
            raise ModuleNotFoundError(f"No module named {fullname!r} (blocked by this test)")


@contextmanager
def blocked(*names: str) -> Iterator[None]:
    """Make ``names`` unimportable, then restore exactly what was evicted."""
    blocker = _ImportBlocker(names)
    loaded = list(sys.modules.items())
    evicted = {name: module for name, module in loaded if name.split(".", 1)[0] in blocker.names}
    for name in evicted:
        del sys.modules[name]
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.update(evicted)


def test_an_optional_dependency_that_is_not_installed_is_absent_not_failed():
    with blocked(*OPTIONAL_PACKAGES):
        solver = check_solver()
        recording = check_columnar_recording()
        ingestion = check_track_ingestion()

    for result in (solver, recording, ingestion):
        print(f"\n{result.name}: {result.state.value}/{result.kind.value} — {result.detail}")
        assert result.kind is CapabilityKind.ABSENT

    assert solver.state is CapabilityState.UNAVAILABLE
    assert recording.state is CapabilityState.DEGRADED
    assert ingestion.state is CapabilityState.DEGRADED
    assert "`data`" in recording.detail
    assert "`track-ingestion`" in ingestion.detail
    assert "scipy" in ingestion.detail
    assert "pypdf" in ingestion.detail


def test_check_numerics_proves_float64_linear_algebra_without_scipy():
    """numpy alone answers the question, so an absent scipy cannot block readiness."""
    with blocked("scipy"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("scipy.linalg")
        result = check_numerics()

    print(f"\nnumerics without scipy: {result.state.value}/{result.kind.value} — {result.detail}")
    assert result.state is CapabilityState.AVAILABLE
    assert result.kind is CapabilityKind.PRESENT
    assert result.detail == "float64 linear solve verified"


def test_the_three_readiness_capabilities_survive_a_default_install(tmp_path: Path, monkeypatch):
    """contracts, numerics and storage stay available with every optional group absent."""
    monkeypatch.setenv("AFTERLAP_ROOT", str(tmp_path))
    with blocked(*OPTIONAL_PACKAGES):
        report = run_doctor()

    mapped = report.capability_map()
    print("\n" + report.render())
    for required in ("contracts", "numerics", "storage"):
        assert mapped[required] is CapabilityState.AVAILABLE
    assert report.failed == []


def test_the_wire_state_of_an_absent_capability_is_still_unavailable():
    """``RuntimeCapabilities.solver`` keeps declaring 'unavailable'; only the reason is new."""
    report = DoctorReport()
    with blocked("casadi"):
        report.add(check_solver())

    assert report.capability_map() == {"solver": CapabilityState.UNAVAILABLE}
    assert [c.name for c in report.unavailable] == ["solver"]
    assert [c.name for c in report.absent] == ["solver"]
    assert report.failed == []


def test_the_rendered_report_distinguishes_an_absence_from_a_failure():
    report = DoctorReport()
    report.add(
        CheckResult("optional", CapabilityState.UNAVAILABLE, "not installed", kind=CapabilityKind.ABSENT)
    )
    report.add(
        CheckResult("broken", CapabilityState.UNAVAILABLE, "answered wrongly", kind=CapabilityKind.FAILED)
    )

    lines = report.render().splitlines()
    print("\n" + report.render())
    assert lines[0].startswith("absent  ")
    assert lines[1].startswith("MISSING ")


def test_doctor_exits_zero_when_every_optional_capability_is_merely_absent(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AFTERLAP_ROOT", str(tmp_path))
    with blocked(*OPTIONAL_PACKAGES):
        result = CliRunner().invoke(app, ["doctor"])

    print("\n" + result.output)
    assert result.exit_code == 0, result.output
    assert "absent optional capabilities" in result.output
    assert "solver" in result.output
    assert "failed capabilities" not in result.output


def test_doctor_exits_one_when_a_capability_genuinely_failed(tmp_path: Path, monkeypatch):
    """An artefact root that cannot be written is a fault, and absence never masks it."""
    blocker = tmp_path / "root"
    blocker.write_text("this is a file, not a directory", encoding="utf-8")
    monkeypatch.setenv("AFTERLAP_ROOT", str(blocker))

    with blocked(*OPTIONAL_PACKAGES):
        result = CliRunner().invoke(app, ["doctor"])

    print("\n" + result.output)
    assert result.exit_code == 1, result.output
    assert "failed capabilities: storage" in result.output
    assert "absent optional capabilities" in result.output


def test_a_probe_that_raises_is_a_failure_rather_than_an_absence(tmp_path: Path, monkeypatch):
    def _exploding_probe() -> CheckResult:
        raise RuntimeError("the probe itself broke")

    monkeypatch.setenv("AFTERLAP_ROOT", str(tmp_path))
    monkeypatch.setattr(diagnostics, "DEFAULT_CHECKS", (_exploding_probe,))
    report = run_doctor()

    failed = {c.name: c for c in report.failed}
    print(f"\nfailed: {[(c.name, c.detail) for c in report.failed]}")
    assert "_exploding_probe" in failed
    assert failed["_exploding_probe"].state is CapabilityState.UNAVAILABLE
    assert report.absent == []


def test_strict_still_refuses_an_install_with_an_absent_capability(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AFTERLAP_ROOT", str(tmp_path))
    with blocked(*OPTIONAL_PACKAGES):
        result = CliRunner().invoke(app, ["doctor", "--strict"])

    assert result.exit_code == 2, result.output


def test_the_json_report_names_the_kind_of_every_check(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AFTERLAP_ROOT", str(tmp_path))
    with blocked("casadi"):
        result = CliRunner().invoke(app, ["doctor", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    checks = {check["name"]: check for check in payload["checks"]}
    print(f"\nsolver: {checks['solver']}")
    assert set(checks["numerics"]) == {"name", "state", "kind", "detail", "version"}
    assert checks["solver"]["state"] == "unavailable"
    assert checks["solver"]["kind"] == "absent"
    assert checks["numerics"]["kind"] == "present"
