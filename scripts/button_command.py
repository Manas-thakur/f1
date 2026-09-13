from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit

LOGGER = logging.getLogger("afterlap.boost_button")
LEVEL_PATTERN = re.compile(r"\b(hi|lo)\b")


def boost_command(host: str, enabled: bool) -> tuple[str, ...]:
    origin = host.rstrip("/")
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path:
        raise ValueError("host must be an HTTP origin such as http://10.1.27.93:18760")
    path = "race/boost" if enabled else "race/boost/off"
    return (
        "curl",
        "--silent",
        "--show-error",
        "--fail-with-body",
        "--request",
        "POST",
        "--connect-timeout",
        "5",
        "--max-time",
        "10",
        "--write-out",
        "\n%{http_code}",
        f"{origin}/{path}",
    )


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


def log_event(level: int, event: str, **fields: object) -> None:
    LOGGER.log(level, json.dumps({"event": event, **fields}, sort_keys=True, separators=(",", ":")))


def configure_logging(path: Path, verbose: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3)
    file_handler.setFormatter(formatter)
    LOGGER.handlers.clear()
    LOGGER.addHandler(console)
    LOGGER.addHandler(file_handler)
    LOGGER.setLevel(logging.DEBUG if verbose else logging.INFO)
    LOGGER.propagate = False


class BoostClient:
    def __init__(self, host: str) -> None:
        self.host = host

    def send(self, enabled: bool) -> bool:
        action = "activate" if enabled else "release"
        command = boost_command(self.host, enabled)
        started = time.monotonic()
        log_event(logging.INFO, "boost_request_started", action=action, endpoint=command[-1])
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        duration_ms = round((time.monotonic() - started) * 1000)
        body, separator, status = result.stdout.rstrip().rpartition("\n")
        if not separator:
            body, status = result.stdout.strip(), "unknown"
        fields = {
            "action": action,
            "duration_ms": duration_ms,
            "http_status": status,
            "response": body,
            "return_code": result.returncode,
        }
        if result.stderr.strip():
            fields["error"] = result.stderr.strip()
        if result.returncode != 0:
            log_event(logging.ERROR, "boost_request_failed", **fields)
            return False
        log_event(logging.INFO, "boost_request_succeeded", **fields)
        return True


def monitor(gpio: int, client: BoostClient, debounce_s: float = 0.05) -> None:
    configure_gpio(gpio)
    active = False
    candidate = read_pressed(gpio)
    candidate_since = time.monotonic()
    log_event(logging.INFO, "button_ready", gpio=gpio, initial_pressed=candidate)
    try:
        while True:
            pressed = read_pressed(gpio)
            now = time.monotonic()
            if pressed != candidate:
                candidate = pressed
                candidate_since = now
                log_event(logging.DEBUG, "button_candidate_changed", gpio=gpio, pressed=pressed)
            elif candidate != active and now - candidate_since >= debounce_s:
                active = candidate
                log_event(logging.INFO, "button_state_changed", gpio=gpio, pressed=active)
                client.send(active)
            time.sleep(0.02)
    finally:
        if active:
            client.send(False)
        log_event(logging.INFO, "button_stopped", gpio=gpio)


def main() -> None:
    default_log = Path(__file__).with_suffix(".log")
    parser = argparse.ArgumentParser(description="Apply boost while a pull-up GPIO button is pressed")
    parser.add_argument("--gpio", type=int, default=int(os.environ.get("BOOST_GPIO", "17")))
    parser.add_argument("--host", default=os.environ.get("HOST", "http://127.0.0.1:18760"))
    parser.add_argument(
        "--log-file", type=Path, default=Path(os.environ.get("BOOST_BUTTON_LOG", default_log))
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.log_file, args.verbose)
    if not 0 <= args.gpio <= 27:
        parser.error("--gpio must be a BCM number between 0 and 27")
    try:
        boost_command(args.host, True)
        log_event(
            logging.INFO,
            "button_starting",
            gpio=args.gpio,
            host=args.host,
            log_file=str(args.log_file.resolve()),
        )
        monitor(args.gpio, BoostClient(args.host))
    except KeyboardInterrupt:
        log_event(logging.INFO, "button_interrupted", gpio=args.gpio)
    except Exception:
        LOGGER.exception(json.dumps({"event": "button_failed", "gpio": args.gpio}))
        raise


if __name__ == "__main__":
    main()
