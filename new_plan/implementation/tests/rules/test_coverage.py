"""The coverage matrix must be honest.

These tests parse the rules test files themselves, so a coverage row cannot
claim ``implemented_and_tested`` while naming a test that does not exist.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from afterlap_contracts import CoverageStatus
from afterlap_core.config import config_dir
from afterlap_core.rules import (
    FORBIDDEN_CLAIM_PHRASES,
    CoverageSpec,
    list_rule_packs,
    load_rule_pack,
)

TEST_DIR = Path(__file__).resolve().parent
TEST_ID_PATTERN = re.compile(r"^(?P<file>test_[a-z0-9_]+\.py)::(?P<name>test_[A-Za-z0-9_]+)$")
DEF_PATTERN = re.compile(r"^def (test_[A-Za-z0-9_]+)\s*\(", re.MULTILINE)

# The concerns listed in 04_rules/RULE_MATRIX.md. Every pack must take a
# position on each of them; silence is not a coverage status.
RULE_MATRIX_CONCERNS = (
    "Electrical DC ceiling",
    "Speed/context curves",
    "Charge range",
    "Recharge allowance",
    "Power demand transitions",
    "Overtake permission",
    "Flags and conditions",
    "Driver information path",
    "Unknown referenced documents",
)


def collected_test_names() -> dict[str, set[str]]:
    """Map each rules test file to the test functions it actually defines."""
    found: dict[str, set[str]] = {}
    for path in sorted(TEST_DIR.glob("test_*.py")):
        found[path.name] = set(DEF_PATTERN.findall(path.read_text(encoding="utf-8")))
    return found


def all_packs():
    return [load_rule_pack(pack_id) for pack_id in list_rule_packs()]


def test_collected_test_names_is_not_vacuous():
    """Guard the guard: the parser must actually find this module's own tests."""
    names = collected_test_names()
    assert "test_coverage.py" in names
    assert "test_collected_test_names_is_not_vacuous" in names["test_coverage.py"]
    assert "test_checker.py" in names
    assert len(names["test_checker.py"]) >= 8


def test_claimed_test_ids_exist():
    names = collected_test_names()
    claims = 0
    for pack in all_packs():
        for entry in pack.manifest.coverage:
            if entry.status is not CoverageStatus.IMPLEMENTED_AND_TESTED:
                continue
            assert entry.test_ids, (
                f"{pack.manifest.ruleset_id}/{entry.concern} claims tested with no test ids"
            )
            for test_id in entry.test_ids:
                match = TEST_ID_PATTERN.match(test_id)
                assert match is not None, f"malformed test id {test_id!r} in {pack.manifest.ruleset_id}"
                file_name = match.group("file")
                test_name = match.group("name")
                assert file_name in names, (
                    f"{pack.manifest.ruleset_id}/{entry.concern} names missing file {file_name}"
                )
                assert test_name in names[file_name], (
                    f"{pack.manifest.ruleset_id}/{entry.concern} names missing test {file_name}::{test_name}"
                )
                claims += 1
    assert claims >= 20


def test_implemented_and_tested_requires_test_ids():
    with pytest.raises(ValidationError):
        CoverageSpec(concern="Electrical DC ceiling", status=CoverageStatus.IMPLEMENTED_AND_TESTED)
    # Every other status may legitimately have none.
    CoverageSpec(concern="Driver information path", status=CoverageStatus.NOT_APPLICABLE)


def test_no_pack_claims_fia_certification():
    for path in sorted(config_dir("rules").glob("*.yaml")):
        text = path.read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN_CLAIM_PHRASES:
            assert phrase not in text, f"{path.name} contains the compliance claim {phrase!r}"
        assert "certified" not in text
        assert "not a transcription" in text or "illustrative" in text


def test_every_synthetic_pack_is_marked_synthetic():
    packs = all_packs()
    assert len(packs) == 3
    for pack in packs:
        assert pack.manifest.synthetic is True
        assert pack.document.synthetic is True
        # Nothing shipped here has been through regulatory review.
        assert pack.manifest.reviewed is False
        assert all(statement.reviewer is None for statement in pack.document.merged_statements().values())


def test_coverage_matrix_covers_every_rule_matrix_concern():
    for pack in all_packs():
        declared = {entry.concern for entry in pack.manifest.coverage}
        missing = [concern for concern in RULE_MATRIX_CONCERNS if concern not in declared]
        assert not missing, f"{pack.manifest.ruleset_id} does not take a position on {missing}"


def test_coverage_is_per_concern_and_not_a_blanket_badge():
    for pack in all_packs():
        statuses = {entry.status for entry in pack.manifest.coverage}
        # If every row were implemented_and_tested the matrix would be a badge.
        assert statuses != {CoverageStatus.IMPLEMENTED_AND_TESTED}
        assert CoverageStatus.NOT_APPLICABLE in statuses or CoverageStatus.UNSUPPORTED in statuses
        assert any(
            entry.status in (CoverageStatus.REVIEW_REQUIRED, CoverageStatus.UNSUPPORTED)
            for entry in pack.manifest.coverage
        )


def test_thermal_derating_is_never_claimed_as_transcribed():
    """The derate model is exercised but its source is unresolved, so it is not
    allowed to claim implemented_and_tested."""
    for pack in all_packs():
        status = pack.coverage_status("Thermal and torque derating")
        if status is None:
            continue
        assert status is not CoverageStatus.IMPLEMENTED_AND_TESTED


def test_every_coverage_reference_carries_provenance():
    for pack in all_packs():
        for entry in pack.manifest.coverage:
            for reference in entry.references:
                assert reference.article
                assert reference.source_id
                # A reviewer field exists and is honestly empty.
                assert reference.reviewer is None
