"""Behavior that must stay identical on Windows, Linux and macOS."""

from __future__ import annotations

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
