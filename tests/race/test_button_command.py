from __future__ import annotations

import signal
import subprocess

import pytest

from button_command import CommandRunner, parse_pressed


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("17: ip pu | hi // GPIO17 = input", False),
        ("17: ip pu | lo // GPIO17 = input", True),
    ],
)
def test_parse_pressed(output, expected):
    assert parse_pressed(output) is expected


def test_parse_pressed_rejects_unknown_output():
    with pytest.raises(ValueError, match="could not read GPIO level"):
        parse_pressed("GPIO17 unavailable")


def test_command_runs_once_and_receives_sigint_on_release(monkeypatch):
    class FakeProcess:
        def __init__(self):
            self.signals = []
            self.waits = []

        def poll(self):
            return None

        def send_signal(self, sent_signal):
            self.signals.append(sent_signal)

        def wait(self, timeout=None):
            self.waits.append(timeout)
            return 0

    process = FakeProcess()
    launches = []

    def launch(command):
        launches.append(tuple(command))
        return process

    monkeypatch.setattr(subprocess, "Popen", launch)
    runner = CommandRunner(("curl", "https://example.com"))
    runner.start()
    runner.start()
    runner.stop()
    assert launches == [("curl", "https://example.com")]
    assert process.signals == [signal.SIGINT]
    assert process.waits == [3]
