"""``python -m afterlap_core.tracks.cli`` never fakes success and never touches the network in tests."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import urllib.request
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import yaml

from afterlap_core.paths import Paths
from afterlap_core.tracks import cli
from afterlap_core.tracks.provenance import RawSourceCache

if TYPE_CHECKING:
    from pathlib import Path

F1_PAGE = "https://fixture.test/racing/2026/test"
FIA_PDF = "https://fixture.test/decision-document/2026_test_grand_prix_-_power_unit_information.pdf"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("tests must not open network connections")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def _run(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.main(list(argv), out)
    return code, out.getvalue()


def _fixture_tree(root: Path, *, with_manifest: bool = True) -> Paths:
    artifacts = root / "artifacts"
    paths = Paths(
        root=root,
        configs=root / "configs",
        artifacts=artifacts,
        trajectories=artifacts / "trajectories",
        models=artifacts / "models",
        reports=artifacts / "reports",
        exports=artifacts / "exports",
        spool=artifacts / "spool",
    )
    registry = {
        "schema_version": "1",
        "season": 2026,
        "entries": [
            {
                "track_id": "test-ring",
                "display_name": "Synthetic ring (fixture)",
                "official_length_m": {"value": 4000.0, "source_url": F1_PAGE},
                "events": [
                    {"event_id": "2026-test", "event_name": "Test Grand Prix", "round": 1, "f1_page": F1_PAGE}
                ],
            }
        ],
    }
    registry_file = paths.configs / "tracks" / "registry" / "season_2026.json"
    registry_file.parent.mkdir(parents=True)
    registry_file.write_text(json.dumps(registry), encoding="utf-8")
    if with_manifest:
        manifest = {
            "track_id": "test-ring",
            "display_name": "Synthetic ring (fixture)",
            "direction": "clockwise",
            "official_length_m": {"value": 4000.0, "source_url": F1_PAGE},
            "openf1": {"sessions": [{"session_key": 1, "year": 2025, "session_name": "Race"}]},
            "fia_documents": [{"event_id": "2026-test", "url": FIA_PDF, "title": "Fixture PU information"}],
            "permissions": {"geometry": "synthetic fixture", "documents": "synthetic fixture"},
        }
        manifest_file = paths.configs / "tracks" / "test-ring" / "source.yaml"
        manifest_file.parent.mkdir(parents=True)
        manifest_file.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return paths


def _prime_cache(paths: Paths) -> RawSourceCache:
    """Synthetic fixture bytes stand in for the pages; nothing here is a real document."""
    cache = RawSourceCache(paths=paths)
    when = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    cache.put(
        b"<html>synthetic fixture page</html>",
        source="f1com",
        source_id="fixture-page",
        title="Synthetic fixture page",
        url=F1_PAGE,
        permission="synthetic fixture",
        priority=5,
        retrieved_at=when,
    )
    cache.put(
        b"%PDF-1.4 synthetic fixture",
        source="fia",
        source_id="fixture-pdf",
        title="Synthetic fixture PDF",
        url=FIA_PDF,
        permission="synthetic fixture",
        priority=1,
        retrieved_at=when,
    )
    return cache


def test_registry_list_and_show(tmp_path):
    paths = _fixture_tree(tmp_path)
    code, text = _run("--root", str(paths.root), "registry", "list")
    assert code == cli.EXIT_OK
    assert "test-ring" in text and "[snapshot]" in text
    code, text = _run("--root", str(paths.root), "registry", "list", "--json")
    assert code == cli.EXIT_OK
    assert json.loads(text)[0]["length_verified"] is False
    code, text = _run("--root", str(paths.root), "registry", "show", "test-ring")
    assert code == cli.EXIT_OK
    assert json.loads(text)["official_length_m"]["value"] == 4000.0


def test_registry_show_unknown_id_is_refused(tmp_path):
    paths = _fixture_tree(tmp_path)
    code, text = _run("--root", str(paths.root), "registry", "show", "ghost-ring")
    assert code == cli.EXIT_REFUSED
    assert "ghost-ring" in text


def test_shipped_registry_lists_from_the_real_configs():
    code, text = _run("registry", "list", "--json")
    assert code == cli.EXIT_OK
    ids = {row["track_id"] for row in json.loads(text)}
    assert {"monza", "monaco", "spa", "suzuka", "mexico-city", "singapore", "sepang"} <= ids


def test_sources_fetch_returns_cached_records_without_network(tmp_path):
    paths = _fixture_tree(tmp_path)
    _prime_cache(paths)
    code, text = _run("--root", str(paths.root), "sources", "fetch", "--registry-entry", "test-ring")
    assert code == cli.EXIT_OK
    report = json.loads(text)
    assert report["failures"] == []
    by_url = {r["url"]: r for r in report["records"]}
    assert by_url[F1_PAGE]["sha256"] == hashlib.sha256(b"<html>synthetic fixture page</html>").hexdigest()
    assert by_url[F1_PAGE]["priority"] == 5
    assert by_url[FIA_PDF]["priority"] == 1
    assert by_url[FIA_PDF]["sha256"] == hashlib.sha256(b"%PDF-1.4 synthetic fixture").hexdigest()


def test_sources_fetch_reports_a_failed_retrieval_instead_of_substituting(tmp_path, monkeypatch):
    paths = _fixture_tree(tmp_path)
    _prime_cache(paths)

    def refuse(*args, **kwargs):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    code, text = _run(
        "--root", str(paths.root), "sources", "fetch", "--registry-entry", "test-ring", "--refresh"
    )
    assert code == cli.EXIT_REFUSED
    report = json.loads(text)
    assert report["records"] == []
    assert {f["url"] for f in report["failures"]} == {F1_PAGE, FIA_PDF}


def test_sources_fetch_refuses_an_unknown_registry_entry(tmp_path):
    paths = _fixture_tree(tmp_path)
    code, text = _run("--root", str(paths.root), "sources", "fetch", "--registry-entry", "ghost-ring")
    assert code == cli.EXIT_REFUSED
    assert "refused" in text


def test_sources_fetch_refuses_a_manifest_bound_to_a_foreign_track(tmp_path):
    paths = _fixture_tree(tmp_path)
    manifest_file = paths.configs / "tracks" / "test-ring" / "source.yaml"
    document = yaml.safe_load(manifest_file.read_text(encoding="utf-8"))
    document["track_id"] = "ghost-ring"
    manifest_file.write_text(yaml.safe_dump(document), encoding="utf-8")
    code, text = _run("--root", str(paths.root), "sources", "fetch", "--registry-entry", "test-ring")
    assert code == cli.EXIT_REFUSED
    assert "ghost-ring" in text


DELEGATED = [
    ("afterlap_core.tracks.ingest.openf1", ["ingest", "--session", "1", "--track", "test-ring"]),
    ("afterlap_core.tracks.compile", ["compile", "--manifest", "configs/tracks/test-ring/source.yaml"]),
    ("afterlap_core.tracks.validate", ["validate", "--track", "test-ring"]),
    (
        "afterlap_core.tracks.fia_overlay",
        ["ingest-fia", "--track", "test-ring", "--event", "2026-test", "--document", "doc.pdf"],
    ),
    (
        "afterlap_core.tracks.fia_overlay",
        [
            "review-overlay",
            "--track",
            "test-ring",
            "--event",
            "2026-test",
            "--reviewer",
            "r1",
            "--decision",
            "pass",
        ],
    ),
]


@pytest.mark.parametrize(("module", "argv"), DELEGATED, ids=[a[0] for _, a in DELEGATED])
def test_missing_stage_module_exits_2_and_names_the_capability(tmp_path, monkeypatch, module, argv):
    paths = _fixture_tree(tmp_path)
    monkeypatch.setitem(sys.modules, module, None)
    code, text = _run("--root", str(paths.root), *argv)
    assert code == cli.EXIT_UNAVAILABLE
    assert text.strip() == f"capability not yet available: {module}"


def test_stage_module_without_the_agreed_function_is_unavailable_not_faked(tmp_path, monkeypatch):
    import types

    paths = _fixture_tree(tmp_path)
    stub = types.ModuleType("afterlap_core.tracks.validate")
    monkeypatch.setitem(sys.modules, "afterlap_core.tracks.validate", stub)
    code, text = _run("--root", str(paths.root), "validate", "--track", "test-ring")
    assert code == cli.EXIT_UNAVAILABLE
    assert "capability not yet available: afterlap_core.tracks.validate.validate_track" in text


def test_present_stage_module_is_called_with_the_agreed_signature(tmp_path, monkeypatch):
    import types

    paths = _fixture_tree(tmp_path)
    seen: dict[str, object] = {}

    def validate_track(track_id: str, paths_arg: Paths):
        seen["track_id"] = track_id
        seen["root"] = paths_arg.root
        return {"status": "discovered", "checks": {"closure": "unknown"}}

    stub = types.ModuleType("afterlap_core.tracks.validate")
    stub.validate_track = validate_track  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "afterlap_core.tracks.validate", stub)
    code, text = _run("--root", str(paths.root), "validate", "--track", "test-ring")
    assert code == cli.EXIT_OK
    assert seen == {"track_id": "test-ring", "root": paths.root}
    assert json.loads(text)["checks"]["closure"] == "unknown"


def test_ingest_refuses_an_undeclared_source(tmp_path):
    paths = _fixture_tree(tmp_path)
    code, text = _run(
        "--root", str(paths.root), "ingest", "--source", "fastf1", "--session", "1", "--track", "x"
    )
    assert code == cli.EXIT_REFUSED
    assert "fastf1" in text
