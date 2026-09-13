from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


def main() -> None:
    environment = {
        **os.environ,
        "PORT": os.environ.get("PORT", "10000"),
        "HOSTNAME": "0.0.0.0",
    }
    origin = environment.get("RACE_ORIGIN", "https://vmax.pulkit.page")
    simulator = subprocess.Popen(
        [
            sys.executable,
            "scripts/race.py",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "18761",
            "--origin",
            origin,
        ],
        env=environment,
    )
    web = subprocess.Popen(["/usr/local/bin/node", "/web/apps/web/server.js"], cwd="/web", env=environment)
    processes = (simulator, web)

    def stop(_signum: int, _frame: object) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while all(process.poll() is None for process in processes):
        time.sleep(0.2)
    stop(signal.SIGTERM, None)
    return_codes = [process.wait() for process in processes]
    raise SystemExit(next((code for code in return_codes if code != 0), 0))


if __name__ == "__main__":
    main()
