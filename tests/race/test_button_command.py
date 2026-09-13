import signal
import subprocess

import pytest

from button_command import CommandRunner, boost_command, parse_pressed


class FakeProcess:
    def __init__(self) -> None:
        self.signals = []
        self.waits = []

    def poll(self):
        return None

    def send_signal(self, value):
        self.signals.append(value)

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return 0

    def terminate(self):
        raise AssertionError("terminate should not be needed")

    def kill(self):
        raise AssertionError("kill should not be needed")


def test_boost_command_uses_dynamic_host_and_api_path():
    assert boost_command("http://10.1.27.93:18760/") == (
        "curl",
        "--fail-with-body",
        "--request",
        "POST",
        "--connect-timeout",
        "5",
        "--max-time",
        "10",
        "http://10.1.27.93:18760/race/boost",
    )


@pytest.mark.parametrize("host", ["10.1.27.93:18760", "file:///tmp/socket", "http://host/path"])
def test_boost_command_rejects_non_origin_hosts(host):
    with pytest.raises(ValueError, match="HTTP origin"):
        boost_command(host)


def test_gpio_level_parser_reads_pull_up_button_state():
    assert parse_pressed("17: ip pu | lo // GPIO") is True
    assert parse_pressed("17: ip pu | hi //") is False


def test_runner_launches_once_and_stops_the_request(monkeypatch):
    process = FakeProcess()
    launches = []

    def launch(command):
        launches.append(tuple(command))
        return process

    monkeypatch.setattr(subprocess, "Popen", launch)
    runner = CommandRunner(("curl", "http://example.com/race/boost"))
    runner.start()
    runner.start()
    runner.stop()
    assert launches == [("curl", "http://example.com/race/boost")]
    assert process.signals == [signal.SIGINT]
    assert process.waits == [3]
