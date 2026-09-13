from __future__ import annotations

import argparse
import re
import signal
import subprocess
import time
from collections.abc import Sequence

DEFAULT_COMMAND = (
    "curl",
    "--limit-rate",
    "1B",
    "--max-time",
    "600",
    "--output",
    "/dev/null",
    "https://example.com",
)
LEVEL_PATTERN = re.compile(r"\b(hi|lo)\b")


def parse_pressed(output: str) -> bool:
    match = LEVEL_PATTERN.search(output.lower())
    if match is None:
        raise ValueError(f"could not read GPIO level from: {output.strip()}")
    return match.group(1) == "lo"


def read_pressed(gpio: int) -> bool:
    result = subprocess.run(
        ["pinctrl", "get", str(gpio)],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_pressed(result.stdout)


def configure_gpio(gpio: int) -> None:
    subprocess.run(["pinctrl", "set", str(gpio), "ip", "pu"], check=True)


class CommandRunner:
    def __init__(self, command: Sequence[str]) -> None:
        self.command = tuple(command)
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        if self.process is not None:
            return
        print(f"BUTTON ON: starting {' '.join(self.command)}", flush=True)
        self.process = subprocess.Popen(self.command)

    def stop(self) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            print("BUTTON OFF: sending Ctrl+C to command", flush=True)
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        self.process = None


def monitor(gpio: int, command: Sequence[str], debounce_s: float = 0.05) -> None:
    configure_gpio(gpio)
    runner = CommandRunner(command)
    active = False
    candidate = read_pressed(gpio)
    candidate_since = time.monotonic()
    print(f"READY: watching BCM GPIO {gpio}", flush=True)
    try:
        while True:
            pressed = read_pressed(gpio)
            now = time.monotonic()
            if pressed != candidate:
                candidate = pressed
                candidate_since = now
            elif candidate != active and now - candidate_since >= debounce_s:
                active = candidate
                if active:
                    runner.start()
                else:
                    runner.stop()
            time.sleep(0.02)
    finally:
        runner.stop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a command while a pull-up GPIO button is held",
    )
    parser.add_argument("--gpio", type=int, default=17)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not 0 <= args.gpio <= 27:
        parser.error("--gpio must be a BCM number between 0 and 27")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    monitor(args.gpio, command or DEFAULT_COMMAND)


if __name__ == "__main__":
    main()
