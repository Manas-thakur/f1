"""The package model enforces the readiness ladder and hash identity structurally."""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from afterlap_core.tracks import (
    CompiledCentreline,
    EventOverlay,
    ReadinessStatus,
    SourceRecord,
    TrackPackage,
    readiness_rank,
)

from .conftest import analytic_loop, build_package


def test_readiness_cannot_be_edited_into_place_without_geometry():
    payload = build_package(status=ReadinessStatus.DISCOVERED).model_dump(mode="json")
    payload["validation"]["status"] = "geometry_validated"
    with pytest.raises(ValidationError, match="requires compiled geometry"):
        TrackPackage.model_validate(payload)


def test_geometry_validated_needs_measured_errors():
    payload = build_package().model_dump(mode="json")
    payload["validation"]["closure_error_m"] = None
    with pytest.raises(ValidationError, match="measured closure and length errors"):
        TrackPackage.model_validate(payload)


def test_event_rules_validated_needs_a_confirmed_overlay():
    with pytest.raises(ValidationError, match="two-reviewer confirmed"):
        build_package(status=ReadinessStatus.EVENT_RULES_VALIDATED)


def test_simulation_eligible_needs_a_known_corridor():
    overlay = EventOverlay(
        event_id="synthetic-event",
        ruleset_hash="synthetic",
        review_status="confirmed",
        reviewers=("reviewer-a", "reviewer-b"),
    )
    package = build_package().model_copy(update={"event_overlay": overlay})
    payload = package.model_dump(mode="json")
    payload["validation"]["status"] = "simulation_eligible"
    with pytest.raises(ValidationError, match="surveyed or validated corridor"):
        TrackPackage.model_validate(payload)
    payload["geometry"]["corridor_quality"] = "validated_estimate"
    assert TrackPackage.model_validate(payload).validation.status is ReadinessStatus.SIMULATION_ELIGIBLE


def test_a_confirmed_overlay_needs_two_distinct_reviewers():
    with pytest.raises(ValidationError, match="two distinct reviewers"):
        EventOverlay(event_id="e", ruleset_hash="h", review_status="confirmed", reviewers=("same", "same"))
    assert not EventOverlay(event_id="e", ruleset_hash="h").is_confirmed


def test_readiness_rank_orders_the_ladder():
    ranks = [readiness_rank(s) for s in ReadinessStatus if s is not ReadinessStatus.REJECTED]
    assert ranks == sorted(ranks)
    assert readiness_rank(ReadinessStatus.REJECTED) < readiness_rank(ReadinessStatus.DISCOVERED)


def test_content_hash_excludes_itself_and_tracks_content():
    package = build_package()
    frozen = package.with_hash()
    assert frozen.package_hash == package.content_hash()
    assert frozen.content_hash() == frozen.package_hash, "hashing must not depend on the stored hash"
    changed = package.model_copy(update={"display_name": "renamed"})
    assert changed.content_hash() != package.content_hash()


def test_source_record_hash_and_priority_are_validated():
    with pytest.raises(ValidationError):
        SourceRecord(source_id="s", title="t", url="u", retrieved_at="now", permission="p", sha256="not-hex")
    with pytest.raises(ValidationError):
        SourceRecord(source_id="s", title="t", url="u", retrieved_at="now", permission="p", priority=9)


def test_centreline_round_trips_through_npz(tmp_path):
    centreline = analytic_loop(corridor=True)
    digest = centreline.to_npz(tmp_path / "c.npz")
    loaded = CompiledCentreline.from_npz(tmp_path / "c.npz")
    assert len(digest) == 64
    assert loaded.point_count == centreline.point_count
    assert loaded.content_hash() == centreline.content_hash()
    probe = np.array([0.0, 700.0])
    np.testing.assert_allclose(loaded.curvature_array(probe), centreline.curvature_array(probe))
    assert loaded.corridor_known
    assert not analytic_loop().corridor_known


def test_centreline_is_periodic_and_closes():
    centreline = analytic_loop()
    length = centreline.length_m
    assert centreline.closure_error_m < 0.05
    assert centreline.curvature_at(length + 10.0) == pytest.approx(centreline.curvature_at(10.0))
    x0, y0, _ = centreline.position_at(0.0)
    x1, y1, _ = centreline.position_at(length)
    assert (x0, y0) == pytest.approx((x1, y1), abs=0.05)
    assert np.isnan(centreline.width_at(100.0)), "an unknown corridor is nan, not an invented width"
