import runpy
import socket
from pathlib import Path

import pytest


def test_occupied_port_reports_recovery_without_stopping_listener():
    launcher = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/race_stack.py"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(SystemExit, match="make race-down before make race"):
            launcher["check_ports"]((port,))
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            assert listener.fileno() >= 0
