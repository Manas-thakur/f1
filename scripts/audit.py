from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ["uv", "run", "--no-sync", "python"]
ZIZMOR = "zizmor@1.30.1"


class Audit:
    def __init__(self, output: Path) -> None:
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
        self.results: list[dict[str, Any]] = []

    def run(self, name: str, command: list[str], timeout: int = 1800) -> None:
        started = time.monotonic()
        print(f"running {name}", flush=True)
        with (self.output / f"{name}.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(
                command, cwd=ROOT, env=self.env, stdout=log, stderr=log, timeout=timeout, check=False
            )
        self.results.append(
            {
                "check": name,
                "exit_code": result.returncode,
                "duration_s": round(time.monotonic() - started, 3),
            }
        )
        if result.returncode:
            raise RuntimeError(f"{name} failed; see {self.output / f'{name}.log'}")
        print(f"passed {name}", flush=True)

    def checks(self) -> None:
        commands = [
            ("python-install", ["uv", "sync", "--frozen", "--all-packages", "--all-groups"]),
            ("web-install", ["bun", "install", "--frozen-lockfile"]),
            ("python-lockfile", ["uv", "lock", "--check"]),
            ("python-vulnerabilities", ["uv", "audit", "--preview-features", "audit-command"]),
            ("web-vulnerabilities", ["bun", "audit"]),
            ("workflow-security", ["uvx", ZIZMOR, "--offline", "--persona=regular", ".github/workflows"]),
            ("python-format", ["uv", "run", "--no-sync", "ruff", "format", "--check", "."]),
            ("python-lint", ["uv", "run", "--no-sync", "ruff", "check", "."]),
            ("python-types", ["uv", "run", "--no-sync", "mypy"]),
            ("comment-policy", [*PYTHON, "scripts/check_no_comments.py"]),
            ("docs", [*PYTHON, "docs/tools/validate_package.py"]),
            ("schema", [*PYTHON, "-m", "afterlap_contracts.schema_export", "--check"]),
            ("doctor", [*PYTHON, "-m", "afterlap_core.cli", "doctor"]),
            ("python-tests", ["uv", "run", "--no-sync", "pytest"]),
            ("web-lint", ["bun", "run", "lint"]),
            ("web-types", ["bun", "run", "typecheck"]),
            ("web-tests", ["bun", "run", "test"]),
            ("web-build", ["bun", "run", "build"]),
            ("browser-install", ["bun", "run", "e2e:install"]),
            ("browser-fixtures", ["bun", "run", "test:e2e"]),
            ("simulation", [*PYTHON, "-m", "afterlap_core.cli", "simulate", "--duration-s", "30"]),
            ("benchmark", [*PYTHON, "-m", "afterlap_core.cli", "evaluate"]),
        ]
        for name, command in commands:
            self.run(name, command)

    def live(self) -> None:
        runtime_port, web_port = free_port(), free_port()
        while runtime_port == web_port:
            web_port = free_port()
        database = self.output / "runtime.sqlite3"
        self.env.update(
            {
                "AFTERLAP_ENV": "development",
                "AFTERLAP_DATABASE_URL": self.env.get(
                    "AFTERLAP_AUDIT_DATABASE_URL", f"sqlite+pysqlite:///{database.as_posix()}"
                ),
                "AFTERLAP_ARTIFACT_ROOT": str(self.output),
                "AFTERLAP_RUNTIME_URL": f"http://127.0.0.1:{runtime_port}",
                "AFTERLAP_AUTOSTART_RUNTIME": "0",
                "AFTERLAP_SESSION_RUNTIME": "process",
                "AFTERLAP_LIVE_URL": f"http://127.0.0.1:{web_port}",
                "AFTERLAP_AUDIT_OUTPUT": str(self.output),
            }
        )
        self.run("migrate", [*PYTHON, "scripts/migrate.py", "--wait-for-database", "30"])
        with ExitStack() as stack:
            runtime = self.start(
                stack,
                "runtime",
                [
                    *PYTHON,
                    "-m",
                    "afterlap_api.cli",
                    "serve",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(runtime_port),
                ],
            )
            wait_port(runtime, runtime_port)
            self.start(stack, "batch", [*PYTHON, "scripts/batch_worker_main.py", "--poll-interval", "0.2"])
            web = self.start(
                stack, "web", ["bun", "run", "--cwd", "apps/web", "start", "--port", str(web_port)]
            )
            wait_http(web, self.env["AFTERLAP_LIVE_URL"] + "/api/v1/health/live")
            self.run(
                "live-runbook",
                [
                    *PYTHON,
                    "scripts/demo.py",
                    "--base-url",
                    self.env["AFTERLAP_LIVE_URL"],
                    "--json",
                    str(self.output / "runbook.json"),
                ],
            )
            shutil.rmtree(ROOT / "apps" / "web" / "test-results", ignore_errors=True)
            self.run("live-browser", ["bun", "run", "test:live"], timeout=1800)
        self.collect_recordings()

    def collect_recordings(self) -> None:
        """Move the browser's videos and traces beside the rest of the evidence."""
        source = ROOT / "apps" / "web" / "test-results"
        if not source.is_dir():
            return
        target = self.output / "recordings"
        target.mkdir(parents=True, exist_ok=True)
        moved = 0
        for item in sorted(source.rglob("*")):
            if item.suffix not in {".webm", ".zip", ".png"} or not item.is_file():
                continue
            name = f"{item.parent.name}{item.suffix}" if item.stem == "video" else item.name
            shutil.copy2(item, target / name)
            moved += 1
        self.results.append({"check": "recordings", "exit_code": 0, "files": moved})
        print(f"collected {moved} browser recordings into {target}", flush=True)

    def start(self, stack: ExitStack, name: str, command: list[str]) -> subprocess.Popen[str]:
        log: IO[str] = stack.enter_context((self.output / f"{name}.log").open("w", encoding="utf-8"))
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=self.env,
            stdout=log,
            stderr=log,
            text=True,
            start_new_session=os.name != "nt",
        )
        stack.callback(stop, process)
        return process


def stop(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        if process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False, capture_output=True
            )
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    except ProcessLookupError:
        return


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_port(process: subprocess.Popen[str], port: int) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("runtime exited during startup")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError("runtime did not start within 60 seconds")


def wait_http(process: subprocess.Popen[str], url: str) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("website exited during startup")
        try:
            with urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(0.2)
    raise TimeoutError("website did not become live within 90 seconds")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the complete local audit in strict dependency order.")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "audit" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"),
    )
    parser.add_argument(
        "--live-only",
        action="store_true",
        help="Run integration checks against a prebuilt checkout; does not certify static checks.",
    )
    args = parser.parse_args()
    audit = Audit(args.output)
    failure: str | None = "audit did not complete"
    exit_code = 1
    try:
        if not args.live_only:
            audit.checks()
        audit.live()
        failure = None
        exit_code = 0
    except KeyboardInterrupt:
        failure = "audit interrupted"
        exit_code = 130
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        failure = str(exc)
        print(f"audit failed: {failure}", flush=True)
    finally:
        report = {
            "passed": failure is None,
            "scope": "live-only" if args.live_only else "complete",
            "checks": audit.results,
            "failure": failure,
        }
        (audit.output / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"audit results: {audit.output}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
