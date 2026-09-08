"""Registry identity rules and source-manifest binding (A16-1). No network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from afterlap_core.paths import Paths
from afterlap_core.tracks.package import Direction, ReadinessStatus
from afterlap_core.tracks.registry import (
    ManifestRegistryMismatch,
    Registry,
    list_source_manifests,
    load_registry,
    load_source_manifest,
    parse_source_manifest,
    registry_path,
)

SPEC_REGISTRY = (
    Path(__file__).resolve().parents[2] / "docs" / "tracks" / "season_2026_registry.json"
)
QUALIFICATION_SET = ("monza", "monaco", "spa", "mexico-city", "suzuka", "singapore")


def _entry(track_id: str = "test-ring", event_id: str = "2026-test", **overrides):
    entry = {
        "track_id": track_id,
        "display_name": "Synthetic ring (fixture)",
        "official_length_m": {"value": 4000.0, "source_url": "synthetic://fixture"},
        "events": [{"event_id": event_id, "event_name": "Test Grand Prix", "round": 1, "race_laps": 60}],
    }
    entry.update(overrides)
    return entry


def _registry(*entries) -> dict:
    return {"schema_version": "1", "season": 2026, "entries": list(entries)}


def _manifest(track_id: str = "test-ring", **overrides) -> dict:
    document = {
        "track_id": track_id,
        "display_name": "Synthetic ring (fixture)",
        "direction": "clockwise",
        "official_length_m": {"value": 4000.0, "source_url": "synthetic://fixture"},
        "openf1": {"sessions": [{"session_key": 1, "year": 2025, "session_name": "Race"}]},
        "fia_documents": [],
        "permissions": {"geometry": "synthetic fixture", "documents": "synthetic fixture"},
    }
    document.update(overrides)
    return document


def _scratch_paths(root: Path) -> Paths:
    artifacts = root / "artifacts"
    return Paths(
        root=root,
        configs=root / "configs",
        artifacts=artifacts,
        trajectories=artifacts / "trajectories",
        models=artifacts / "models",
        reports=artifacts / "reports",
        exports=artifacts / "exports",
        spool=artifacts / "spool",
    )


# --------------------------------------------------------------------------- #
# model rules
# --------------------------------------------------------------------------- #


def test_duplicate_track_ids_are_rejected():
    with pytest.raises(ValidationError, match="duplicate track_id"):
        Registry.model_validate(_registry(_entry(event_id="2026-a"), _entry(event_id="2026-b")))


def test_duplicate_event_ids_are_rejected_even_across_circuits():
    with pytest.raises(ValidationError, match="duplicate event_id"):
        Registry.model_validate(_registry(_entry("ring-a", "2026-x"), _entry("ring-b", "2026-x")))


def test_track_id_pattern_is_enforced():
    with pytest.raises(ValidationError):
        Registry.model_validate(_registry(_entry(track_id="Monza")))


def test_unknown_direction_is_rejected_in_registry_and_manifest():
    with pytest.raises(ValidationError):
        Registry.model_validate(_registry(_entry(direction="anticlockwise")))
    with pytest.raises(ValidationError):
        parse_source_manifest(_manifest(direction="anticlockwise"))


def test_unknown_length_stays_null_and_is_not_verified():
    registry = Registry.model_validate(_registry(_entry(official_length_m={})))
    length = registry.get("test-ring").official_length_m
    assert length.value is None
    assert length.verified is False
    with pytest.raises(ValidationError):
        Registry.model_validate(_registry(_entry(official_length_m={"value": 0})))


def test_extra_fields_are_forbidden():
    with pytest.raises(ValidationError):
        Registry.model_validate(_registry(_entry(nominal_length_km=5.7)))
    with pytest.raises(ValidationError):
        parse_source_manifest(_manifest(openf1_session=9912))


def test_readiness_defaults_to_discovered():
    registry = Registry.model_validate(_registry(_entry()))
    assert registry.get("test-ring").readiness is ReadinessStatus.DISCOVERED


def test_get_names_the_missing_id():
    registry = Registry.model_validate(_registry(_entry()))
    with pytest.raises(KeyError, match="'nowhere'"):
        registry.get("nowhere")
    assert "test-ring" in registry
    assert "nowhere" not in registry


# --------------------------------------------------------------------------- #
# manifest binding
# --------------------------------------------------------------------------- #


def test_manifest_for_a_track_not_in_the_registry_is_refused():
    registry = Registry.model_validate(_registry(_entry()))
    with pytest.raises(ManifestRegistryMismatch, match="not in the 2026 registry"):
        parse_source_manifest(_manifest(track_id="ghost-ring"), registry)


def test_manifest_fia_document_for_a_foreign_event_is_refused():
    registry = Registry.model_validate(_registry(_entry()))
    document = _manifest(
        fia_documents=[{"event_id": "2026-elsewhere", "url": "https://example.test/x.pdf", "title": "x"}]
    )
    with pytest.raises(ManifestRegistryMismatch, match="2026-elsewhere"):
        parse_source_manifest(document, registry)


def test_manifest_session_keys_must_be_unique():
    sessions = {"sessions": [{"session_key": 1, "year": 2025, "session_name": "Race"}] * 2}
    with pytest.raises(ValidationError, match="twice"):
        parse_source_manifest(_manifest(openf1=sessions))


def test_load_source_manifest_uses_the_registry_under_the_same_paths(tmp_path):
    paths = _scratch_paths(tmp_path)
    registry_file = registry_path(paths)
    registry_file.parent.mkdir(parents=True)
    registry_file.write_text(json.dumps(_registry(_entry())), encoding="utf-8")
    good = paths.configs / "tracks" / "test-ring" / "source.yaml"
    good.parent.mkdir(parents=True)
    good.write_text(yaml.safe_dump(_manifest()), encoding="utf-8")
    bad = paths.configs / "tracks" / "ghost-ring" / "source.yaml"
    bad.parent.mkdir(parents=True)
    bad.write_text(yaml.safe_dump(_manifest(track_id="ghost-ring")), encoding="utf-8")

    assert list_source_manifests(paths) == ("ghost-ring", "test-ring")
    manifest = load_source_manifest("test-ring", paths)
    assert manifest.direction is Direction.CLOCKWISE
    assert manifest.openf1.sessions[0].session_key == 1
    with pytest.raises(ManifestRegistryMismatch):
        load_source_manifest("ghost-ring", paths)
    with pytest.raises(ManifestRegistryMismatch):
        load_source_manifest(bad, paths)


# --------------------------------------------------------------------------- #
# the shipped 2026 registry and manifests
# --------------------------------------------------------------------------- #


def test_shipped_registry_matches_the_specification_snapshot():
    registry = load_registry()
    spec = json.loads(SPEC_REGISTRY.read_text(encoding="utf-8"))
    assert registry.season == 2026
    assert len(registry.entries) == len(spec["events"]) == 23
    for event in spec["events"]:
        entry = registry.get(event["track_id"])
        assert entry.display_name == event["circuit_name"]
        assert entry.official_length_m.value == event["nominal_length_m"]
        assert entry.official_length_m.source_url == event["f1_page"]
        assert entry.event_ids == (event["event_id"],)
        assert entry.events[0].race_laps == event["race_laps"]
        assert entry.events[0].round == event["round"]
        # Fields the snapshot did not carry stay null rather than invented.
        assert entry.country is None
        assert entry.direction is None
        assert entry.events[0].event_date is None
        assert entry.readiness is ReadinessStatus.DISCOVERED


def test_shipped_registry_keeps_calendar_and_circuit_identity_separate():
    registry = load_registry()
    entry, event = registry.find_event("2026-bahrain-gp-malaysia")
    assert entry.track_id == "sepang"
    assert event.event_name == "Bahrain Grand Prix in Malaysia"


def test_shipped_length_verification_is_hash_backed_or_absent():
    registry = load_registry()
    for entry in registry.entries:
        length = entry.official_length_m
        if length.verified:
            assert length.sha256 is not None and length.retrieved_at is not None
        else:
            assert length.sha256 is None
    verified = {e.track_id for e in registry.entries if e.official_length_m.verified}
    assert set(QUALIFICATION_SET) <= verified


@pytest.mark.parametrize("track_id", QUALIFICATION_SET)
def test_shipped_manifests_bind_to_the_registry(track_id):
    registry = load_registry()
    manifest = load_source_manifest(track_id, registry=registry)
    entry = registry.get(track_id)
    assert manifest.track_id == track_id
    assert manifest.display_name == entry.display_name
    assert manifest.official_length_m.value == entry.official_length_m.value
    assert manifest.official_length_m.sha256 == entry.official_length_m.sha256
    assert manifest.openf1.sessions, "each qualification circuit declares a 2025 Race session"
    assert all(s.year == 2025 and s.session_name == "Race" for s in manifest.openf1.sessions)
    assert all(d.event_id in entry.event_ids for d in manifest.fia_documents)
