from __future__ import annotations

import json
import sys
from contextlib import ExitStack

import pytest

import audit


def test_a_failed_gate_stops_the_ordered_audit(tmp_path, monkeypatch):
    runner = audit.Audit(tmp_path / "audit")
    checked = []

    def run(name, command, timeout=1800):
        checked.append(name)
        if name == "python-lint":
            raise RuntimeError("lint failed")

    monkeypatch.setattr(runner, "run", run)
    with pytest.raises(RuntimeError, match="lint failed"):
        runner.checks()
    assert checked[:2] == ["python-install", "web-install"]
    assert checked[-1] == "python-lint"
    assert "python-vulnerabilities" in checked
    assert "web-vulnerabilities" in checked
    assert "workflow-security" in checked
    assert "python-types" not in checked


def test_failed_command_records_exit_code_and_diagnostic(tmp_path):
    runner = audit.Audit(tmp_path / "audit")
    with pytest.raises(RuntimeError, match="broken failed"):
        runner.run("broken", [sys.executable, "-c", 'print("diagnostic"); raise SystemExit(7)'])
    assert runner.results[0]["exit_code"] == 7
    assert (runner.output / "broken.log").read_text().strip() == "diagnostic"


def test_live_process_is_stopped_when_a_later_check_fails(tmp_path):
    runner = audit.Audit(tmp_path / "audit")
    with pytest.raises(RuntimeError, match="later gate"), ExitStack() as stack:
        process = runner.start(stack, "service", [sys.executable, "-c", "import time; time.sleep(300)"])
        raise RuntimeError("later gate")
    assert process.poll() is not None


def test_interrupt_is_never_reported_as_a_pass(tmp_path, monkeypatch):
    output = tmp_path / "audit"
    monkeypatch.setattr(sys, "argv", ["audit.py", "--live-only", "--output", str(output)])

    def interrupted(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(audit.Audit, "live", interrupted)
    assert audit.main() == 130
    report = json.loads((output / "summary.json").read_text())
    assert report["passed"] is False
    assert report["scope"] == "live-only"
    assert report["failure"] == "audit interrupted"
