from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_ports(ports: tuple[int, ...] = (18760, 18761)) -> None:
    for port in ports:
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind(("127.0.0.1", port))
            except OSError:
                raise SystemExit(
                    f"Port {port} is unavailable. If the Docker race stack is running, "
                    "run make race-down before make race. Otherwise stop the process using this port."
                ) from None


def main() -> None:
    children: list[subprocess.Popen[bytes]] = []
    bun = shutil.which("bun")
    if bun is None:
        raise RuntimeError("Bun is required")
    check_ports()

    def stop(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        children.append(
            subprocess.Popen(
                [sys.executable, "scripts/race.py", "serve"],
                cwd=ROOT,
                start_new_session=True,
            )
        )
        children.append(
            subprocess.Popen(  # noqa: S603
                [bun, "x", "next", "dev", "--hostname", "127.0.0.1", "--port", "18760"],
                cwd=ROOT / "apps/web",
                start_new_session=True,
            )
        )
        print(
            "race view: http://127.0.0.1:18760/race\nrace control: http://127.0.0.1:18760/race/control",
            flush=True,
        )
        while all(child.poll() is None for child in children):
            time.sleep(0.2)
        raise RuntimeError("a race service stopped; see its output above")
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        for child in children:
            if child.poll() is None:
                if os.name == "posix":
                    os.killpg(child.pid, signal.SIGTERM)
                else:
                    child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(child.pid, signal.SIGKILL)
                else:
                    child.kill()
                child.wait()


if __name__ == "__main__":
    main()
