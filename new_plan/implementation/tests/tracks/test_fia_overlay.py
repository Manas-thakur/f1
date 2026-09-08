"""FIA overlay ingestion is a draft queue; only two distinct reviewers make a rule."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from afterlap_core.tracks import EventOverlay
from afterlap_core.tracks.fia_overlay import (
    NUMERIC_FIELDS,
    RECHARGE_COLUMNS,
    extract_pdf_text,
    ingest_fia_document,
    overlay_effective_values,
    parse_pui_text,
    review_overlay,
)
from afterlap_core.tracks.loader import load_event_overlay
from afterlap_core.tracks.provenance import RawSourceCache

from .conftest import scratch_paths
from .fixtures.fia.make_fixtures import FIXTURES, build_minimal_pdf

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "fia"
TABULAR = FIXTURE_DIR / "synthetic_pui_tabular.pdf"
CHART = FIXTURE_DIR / "synthetic_pui_chart_layout.pdf"
TRACK = "synthetic-oval-package"
EVENT = "2026-synthetic"


def test_checked_in_fixtures_match_their_generator():
    for name, lines in FIXTURES.items():
        assert (FIXTURE_DIR / name).read_bytes() == build_minimal_pdf(lines)


def test_tabular_fixture_parses_to_the_expected_rows():
    parsed = parse_pui_text("\n".join(extract_pdf_text(TABULAR.read_bytes())))
    assert parsed.round_no == "R99"
    assert parsed.centreline_km == 2.4
    assert parsed.recharge_by_column_mj == dict(zip(RECHARGE_COLUMNS, (8.0, 8.5, 6.0, 8.5, 8.5), strict=True))
    assert parsed.power_limited_distance_m == 1000.0
    assert parsed.power_reduction_rate_kw_per_s == 100.0
    assert (parsed.detection_line_m, parsed.activation_line_m) == (1200.0, 1350.0)
    assert parsed.detection_gap_s == 1.0
    assert parsed.loop_labels == ["L5", "L6"]
    assert parsed.curves["standard"] == [(220.0, 350.0), (260.0, 300.0), (300.0, 250.0), (340.0, 200.0)]
    assert parsed.curves["overtake"] == [(220.0, 350.0), (300.0, 350.0), (340.0, 300.0)]
    assert parsed.race_laps == 57
    assert parsed.main_overtaking_zones == [
        {"start_m": 300.0, "end_m": 500.0, "qualifying_only": False, "speed_threshold_kph": 240.0},
        {"start_m": 1400.0, "end_m": 1700.0, "qualifying_only": False, "speed_threshold_kph": 240.0},
    ]
    assert set(parsed.unknown) == {"straight_mode_ranges"}


def test_chart_layout_fixture_reports_curves_unknown_and_flags_tbc():
    parsed = parse_pui_text("\n".join(extract_pdf_text(CHART.read_bytes())))
    assert parsed.curves == {}
    assert "standard_curve" in parsed.unknown and "overtake_curve" in parsed.unknown
    assert parsed.detection_line_m == 2805.0 and parsed.detection_line_tbc is True
    assert parsed.activation_line_m == 2950.0 and parsed.activation_line_tbc is False
    assert parsed.main_overtaking_zones == []  # the '- - -' row
    assert parsed.race_laps is None and "race_laps" in parsed.unknown
    # Axis ticks must never be mistaken for curve rows or lap-distance lines.
    assert parsed.lap_distance_windows == [
        {"start_m": 2980.0, "end_m": 3200.0, "qualifying_only": True},
        {"start_m": 3070.0, "end_m": 3400.0, "qualifying_only": True},
    ]


def test_ingest_from_path_writes_an_unreviewed_draft_and_sidecar(tmp_path):
    paths = scratch_paths(tmp_path)
    overlay = ingest_fia_document(TRACK, EVENT, TABULAR, paths)

    assert overlay.review_status == "unreviewed"
    assert overlay.reviewers == ()
    assert overlay.detection_lines_m == (1200.0,)
    assert overlay.activation_lines_m == (1350.0,)
    assert overlay.recharge_allowance_mj == 8.0
    assert overlay.race_laps == 57
    assert [(r.speed_kph, r.power_kw) for r in overlay.standard_curve][:2] == [(220.0, 350.0), (260.0, 300.0)]
    assert overlay.straight_mode_ranges == ()
    assert any(f.startswith("straight_mode_ranges:") for f in overlay.unknown_fields)
    assert len(overlay.fia_documents) == 1
    doc = overlay.fia_documents[0]
    assert doc.priority == 1 and doc.sha256 is not None and "FIA public decision document" in doc.permission

    events = paths.artifacts / "tracks" / TRACK / "events"
    assert load_event_overlay(TRACK, EVENT, paths) == overlay
    sidecar = json.loads((events / f"{EVENT}.extraction.json").read_text(encoding="utf-8"))
    assert sidecar["review_status"] == "unreviewed"
    assert sidecar["parsed"]["recharge_by_column_mj"]["qualifying"] == 6.0
    assert sidecar["parsed"]["assumptions"]  # every text-order heuristic is written down for reviewers
    # The raw bytes are in the immutable cache under the document hash.
    cached = RawSourceCache(paths=paths).get("fia", doc.sha256)
    assert cached.read_bytes() == TABULAR.read_bytes()


def test_a_revised_document_supersedes_and_restarts_review(tmp_path):
    paths = scratch_paths(tmp_path)
    first = ingest_fia_document(TRACK, EVENT, TABULAR, paths)
    review_overlay(TRACK, EVENT, "reviewer-a", "confirm", paths)
    review_overlay(TRACK, EVENT, "reviewer-b", "confirm", paths)
    assert load_event_overlay(TRACK, EVENT, paths).is_confirmed

    second = ingest_fia_document(TRACK, EVENT, CHART, paths)
    assert second.review_status == "unreviewed"
    assert second.fia_documents[0].sha256 != first.fia_documents[0].sha256
    events = paths.artifacts / "tracks" / TRACK / "events"
    aside = list(events.glob(f"{EVENT}.superseded-*.json"))
    assert len(aside) == 1
    assert EventOverlay.model_validate(json.loads(aside[0].read_text())).is_confirmed


def test_effective_values_are_none_until_two_distinct_reviewers_confirm(tmp_path):
    paths = scratch_paths(tmp_path)
    draft = ingest_fia_document(TRACK, EVENT, TABULAR, paths)
    assert all(overlay_effective_values(draft)[name] is None for name in NUMERIC_FIELDS)

    one = review_overlay(TRACK, EVENT, "reviewer-a", "confirm", paths)
    assert one.review_status == "one_reviewer"
    assert one.reviewers == ("reviewer-a",)
    assert all(overlay_effective_values(one)[name] is None for name in NUMERIC_FIELDS)

    same_again = review_overlay(TRACK, EVENT, "reviewer-a", "confirm", paths)
    assert same_again.review_status == "one_reviewer"
    assert same_again.reviewers == ("reviewer-a",)
    assert all(overlay_effective_values(same_again)[name] is None for name in NUMERIC_FIELDS)

    padded = review_overlay(TRACK, EVENT, "  reviewer-a ", "confirm", paths)
    assert padded.review_status == "one_reviewer"

    confirmed = review_overlay(TRACK, EVENT, "reviewer-b", "confirm", paths)
    assert confirmed.review_status == "confirmed"
    assert confirmed.reviewers == ("reviewer-a", "reviewer-b")
    values = overlay_effective_values(confirmed)
    assert values["detection_lines_m"] == [1200.0]
    assert values["activation_lines_m"] == [1350.0]
    assert values["recharge_allowance_mj"] == 8.0
    assert values["race_laps"] == 57
    assert values["standard_curve"][0] == (220.0, 350.0)
    # A field the reviewers listed as unknown stays unknown even when confirmed.
    assert values["straight_mode_ranges"] is None

    stored = load_event_overlay(TRACK, EVENT, paths)
    assert stored.reviewers == ("reviewer-a", "reviewer-b")
    log = (paths.artifacts / "tracks" / TRACK / "events" / f"{EVENT}.reviews.jsonl").read_text().splitlines()
    assert len(log) == 4
    assert json.loads(log[1])["no_change"] is True


def test_reject_recalls_and_a_recalled_overlay_takes_no_further_review(tmp_path):
    paths = scratch_paths(tmp_path)
    ingest_fia_document(TRACK, EVENT, TABULAR, paths)
    review_overlay(TRACK, EVENT, "reviewer-a", "confirm", paths)
    recalled = review_overlay(TRACK, EVENT, "reviewer-b", "reject", paths)
    assert recalled.review_status == "recalled"
    assert recalled.reviewers == ("reviewer-a", "reviewer-b")
    assert all(overlay_effective_values(recalled)[name] is None for name in NUMERIC_FIELDS)
    with pytest.raises(ValueError, match="recalled"):
        review_overlay(TRACK, EVENT, "reviewer-c", "confirm", paths)


def test_review_input_validation(tmp_path):
    paths = scratch_paths(tmp_path)
    ingest_fia_document(TRACK, EVENT, TABULAR, paths)
    with pytest.raises(ValueError, match="reviewer name"):
        review_overlay(TRACK, EVENT, "   ", "confirm", paths)
    with pytest.raises(ValueError, match="decision"):
        review_overlay(TRACK, EVENT, "reviewer-a", "approve", paths)


def test_a_confirmed_overlay_cannot_be_hand_written_with_one_reviewer():
    with pytest.raises(ValueError, match="two distinct reviewers"):
        EventOverlay(event_id=EVENT, ruleset_hash="x", review_status="confirmed", reviewers=("a", "a"))


def test_missing_document_path_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        ingest_fia_document(TRACK, EVENT, tmp_path / "absent.pdf", scratch_paths(tmp_path))
