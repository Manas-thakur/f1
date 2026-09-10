"""Behavior that must stay identical on Windows, Linux and macOS."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from afterlap_api.redaction import ELIDED, scrub_local_paths


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            r"missing C:\work\afterlap\artifacts\tracks\monza\package.json",
            "missing artifacts/tracks/monza/package.json",
        ),
        (
            "missing C:/work/afterlap/configs/rules/fia-2026.yaml",
            "missing configs/rules/fia-2026.yaml",
        ),
        (
            "missing /Users/engineer/afterlap/artifacts/tracks/spa/package.json",
            "missing artifacts/tracks/spa/package.json",
        ),
        (
            r"missing \\build-server\workspace\artifacts\reports\run.json",
            "missing artifacts/reports/run.json",
        ),
        (r"missing C:\Users\engineer\private\token.txt", f"missing {ELIDED}"),
        ("missing /home/engineer/private/token.txt", f"missing {ELIDED}"),
    ],
)
def test_local_paths_are_redacted_independently_of_the_host_os(message: str, expected: str):
    assert scrub_local_paths(message) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.fia.com/regulation/category/110",
        "https://api.openf1.org/v1/location?session_key=latest",
    ],
)
def test_remote_source_urls_survive_path_redaction(url: str):
    assert scrub_local_paths(f"source {url}") == f"source {url}"


INTERPRETER_PATHS = re.compile(r"\.venv[\/](?:Scripts|bin)[\/]")
"""How the repository's own rule names a non-portable interpreter invocation."""

ALLOWED_TO_QUOTE_THE_RULE = frozenset(
    {
        Path(__file__).resolve().parents[2] / "README.md",
        Path(__file__).resolve(),
    }
)
"""The files that state the rule, and are therefore allowed to spell out the shape it forbids."""

SEARCHED_SUFFIXES = frozenset({".py", ".md", ".toml", ".yml", ".yaml", ".ts", ".tsx"})

SEARCHED_ROOTS = ("apps", "packages", "scripts", "workers", "infra", "configs", "tests")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_no_shared_instruction_invokes_the_virtualenv_interpreter_directly():
    """`README.md`: do not call `.venv/Scripts/python.exe` from shared scripts.

    The rule exists because those paths are per-platform. It was being broken
    in four places, one of which wrote the Windows path into the
    ``rerun_command`` field of every benchmark report — an evidence artefact
    whose whole purpose is that someone else can run it again.
    """
    root = _repository_root()
    offenders: list[str] = []
    for directory in SEARCHED_ROOTS:
        for path in (root / directory).rglob("*"):
            if path.suffix not in SEARCHED_SUFFIXES or not path.is_file():
                continue
            if path.resolve() in ALLOWED_TO_QUOTE_THE_RULE:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if INTERPRETER_PATHS.search(line):
                    offenders.append(f"{path.relative_to(root).as_posix()}:{number}: {line.strip()}")

    assert not offenders, "shared instructions must run through `uv run`:\n" + "\n".join(offenders)
