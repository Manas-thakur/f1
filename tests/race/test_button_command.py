import subprocess

import pytest

import button_command
from button_command import BoostClient, boost_command, configure_logging, monitor, parse_pressed


def test_boost_commands_use_dynamic_host_and_synchronized_api_paths():
    activation = boost_command("http://10.1.27.93:18760/", True)
    release = boost_command("http://10.1.27.93:18760/", False)
    assert activation[-1] == "http://10.1.27.93:18760/race/boost"
    assert release[-1] == "http://10.1.27.93:18760/race/boost/off"
    assert activation[activation.index("--request") + 1] == "POST"
    assert release[release.index("--request") + 1] == "POST"


@pytest.mark.parametrize("host", ["10.1.27.93:18760", "file:///tmp/socket", "http://host/path"])
def test_boost_command_rejects_non_origin_hosts(host):
    with pytest.raises(ValueError, match="HTTP origin"):
        boost_command(host, True)


def test_gpio_level_parser_reads_pull_up_button_state():
    assert parse_pressed("17: ip pu | lo // GPIO") is True
    assert parse_pressed("17: ip pu | hi //") is False


def test_client_logs_successful_api_response(monkeypatch, tmp_path):
    log_path = tmp_path / "button.log"
    configure_logging(log_path, False)
    result = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout='{"operation":"boost","car_id":"car-01","status":"accepted"}\n200',
        stderr="",
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result)
    assert BoostClient("http://race.local:18760").send(True) is True
    contents = log_path.read_text()
    assert '"event":"boost_request_started"' in contents
    assert '"event":"boost_request_succeeded"' in contents
    assert '"http_status":"200"' in contents


def test_client_logs_failed_api_response(monkeypatch, tmp_path):
    log_path = tmp_path / "button.log"
    configure_logging(log_path, False)
    result = subprocess.CompletedProcess(
        args=[],
        returncode=22,
        stdout='{"error":"boost unavailable: battery energy depleted"}\n409',
        stderr="curl: (22) The requested URL returned error: 409",
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result)
    assert BoostClient("http://race.local:18760").send(True) is False
    contents = log_path.read_text()
    assert '"event":"boost_request_failed"' in contents
    assert '"http_status":"409"' in contents
    assert "battery energy depleted" in contents


def test_debounced_press_activates_and_release_deactivates(monkeypatch):
    readings = iter([False, True, True, False, False])
    times = iter([0.0, 0.1, 0.2, 0.3, 0.4])
    calls = []

    class RecordingClient:
        def send(self, enabled):
            calls.append(enabled)
            return True

    monkeypatch.setattr(button_command, "configure_gpio", lambda gpio: None)
    monkeypatch.setattr(button_command, "read_pressed", lambda gpio: next(readings))
    monkeypatch.setattr(button_command.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(button_command.time, "sleep", lambda duration: None)
    with pytest.raises(StopIteration):
        monitor(17, RecordingClient())
    assert calls == [True, False]
