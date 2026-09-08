"""Chunked Parquet recording, atomic manifests, provenance and redaction."""

from __future__ import annotations

import json

import pytest

from afterlap_contracts import Quality
from afterlap_core.data import (
    AcquisitionRecord,
    ChunkReader,
    IngestionPipeline,
    MemorySink,
    TelemetryRecorder,
    redact_mapping,
    redact_text,
    redact_url,
)
from afterlap_core.data.recording import REDACTED

from .conftest import SESSION_ID, observation, simulator_config

MAPPING_REVISION = "sim-observation-map-1"

SECRETS = {
    "api_token": "tok_live_9f3ab7c21e",
    "cookie": "session=abcdef123456; Path=/",
    "password": "hunter2-not-a-real-password",
    "endpoint": "https://engineer:s3cr3t@feed.example.invalid/stream?token=tok_live_9f3ab7c21e&car=1",
}
SECRET_VALUES = (
    "tok_live_9f3ab7c21e",
    "abcdef123456",
    "hunter2-not-a-real-password",
    "s3cr3t",
)


def _recorded(tmp_path, count: int = 12, chunk_duration_s: float = 0.2):
    sink = MemorySink()
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.0), sink=sink)
    pipeline.ingest_all(
        [
            observation(
                i,
                i * 0.05,
                {"speed_mps": 70.0 + i, "battery_energy_j": 2_400_000.0 - i * 1000},
                received_time_s=i * 0.05,
            )
            for i in range(count)
        ]
    )
    recorder = TelemetryRecorder(
        tmp_path, SESSION_ID, mapping_revision=MAPPING_REVISION, chunk_duration_s=chunk_duration_s
    )
    for packet, car_id, session_time_s in sink.raw:
        recorder.append_raw(packet, car_id=car_id, session_time_s=session_time_s)
    for record in sink.normalised:
        recorder.append_normalised(record)
    return sink, recorder


def test_chunk_hashes_verify(tmp_path):
    _sink, recorder = _recorded(tmp_path)
    published = recorder.flush()
    assert published

    reader = ChunkReader(tmp_path, SESSION_ID)
    assert reader.verify() == ()
    for chunk in reader.manifest():
        assert chunk.chunk_hash.startswith("sha256:")
        assert chunk.row_count > 0
        assert chunk.mapping_revision == MAPPING_REVISION
        assert chunk.end_session_time_s >= chunk.start_session_time_s


def test_a_corrupted_chunk_fails_verification(tmp_path):
    _, recorder = _recorded(tmp_path)
    recorder.flush()
    reader = ChunkReader(tmp_path, SESSION_ID)
    target = reader.session_root / reader.manifest()[0].path
    target.write_bytes(target.read_bytes() + b"tamper")
    failures = reader.verify()
    assert len(failures) == 1
    assert "does not match manifest" in failures[0]


def test_a_reader_sees_only_completed_chunks(tmp_path):
    _, recorder = _recorded(tmp_path)
    pending = recorder.stage()
    assert pending
    for chunk in pending:
        assert chunk.staging_path.exists()
        assert not chunk.final_path.exists()

    reader = ChunkReader(tmp_path, SESSION_ID)
    assert reader.manifest() == ()
    assert reader.read_normalised() == ()

    recorder.publish(pending)
    assert reader.manifest()
    assert reader.read_normalised()
    for chunk in pending:
        assert chunk.final_path.exists()
        assert not chunk.staging_path.exists()


def test_raw_and_canonical_records_are_kept_separately_with_their_mapping_revision(tmp_path):
    sink, recorder = _recorded(tmp_path)
    recorder.flush()
    reader = ChunkReader(tmp_path, SESSION_ID)

    canonical_paths = [c.path for c in reader.manifest() if c.path.startswith("canonical/")]
    raw_paths = [c.path for c in reader.manifest() if c.path.startswith("raw/")]
    assert canonical_paths and raw_paths

    canonical_rows = reader.read_canonical_rows()
    raw_rows = reader.read_raw_rows()
    assert len(canonical_rows) == len(sink.normalised)
    assert len(raw_rows) == len(sink.raw)
    assert {row["mapping_revision"] for row in canonical_rows} == {MAPPING_REVISION}
    assert {row["mapping_revision"] for row in raw_rows} == {MAPPING_REVISION}

    # Raw rows keep every vendor field, including any that were never mapped.
    fields = json.loads(raw_rows[0]["fields_json"])
    assert "speed_mps" in fields and "battery_energy_j" in fields


def test_chunks_are_partitioned_by_car_family_and_time(tmp_path):
    _, recorder = _recorded(tmp_path, count=12, chunk_duration_s=0.2)
    recorder.flush()
    reader = ChunkReader(tmp_path, SESSION_ID)
    paths = [c.path for c in reader.manifest()]
    assert any("car=car-01" in p for p in paths)
    assert any("family=motion" in p for p in paths)
    assert any("family=electrical" in p for p in paths)
    assert any("family=raw" in p for p in paths)
    chunk_indices = {p.split("chunk=")[1].split("/")[0] for p in paths}
    assert len(chunk_indices) > 1  # session was split into bounded time chunks


def test_a_missing_value_survives_recording_as_null_not_zero(tmp_path):
    sink = MemorySink()
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.0), sink=sink)
    pipeline.ingest_all([observation(0, 1.0, {"speed_mps": None}, received_time_s=1.0)])
    recorder = TelemetryRecorder(tmp_path, SESSION_ID, mapping_revision=MAPPING_REVISION)
    for record in sink.normalised:
        recorder.append_normalised(record)
    recorder.flush()

    rows = ChunkReader(tmp_path, SESSION_ID).read_canonical_rows()
    assert len(rows) == 1
    assert rows[0]["value"] is None
    assert rows[0]["quality"] == Quality.MISSING.value
    assert rows[0]["reason"]


def test_acquisition_manifest_records_source_url_license_and_terms_review(tmp_path):
    _, recorder = _recorded(tmp_path)
    recorder.flush()
    recorder.write_acquisition_manifest(
        [
            AcquisitionRecord(
                source_id="public-replay",
                source_url="https://api.example.invalid/v1/car_data?session_key=9999",
                license_note="Public reference archive; see source register D01.",
                terms_review_status="review_required",
                retrieved_at="2026-09-08T12:00:00+00:00",
                mapping_revision="public-openf1-shape-map-1",
                synthetic=True,
                note="Synthetic fixture in the shape of the public schema.",
            )
        ]
    )
    acquisition = ChunkReader(tmp_path, SESSION_ID).acquisition()
    source = acquisition["sources"][0]
    assert source["source_url"].startswith("https://api.example.invalid/")
    assert source["terms_review_status"] == "review_required"
    assert source["license_note"]
    assert source["synthetic"] is True


def test_credentials_in_a_source_config_never_appear_in_a_manifest(tmp_path):
    _, recorder = _recorded(tmp_path)
    recorder.flush()
    recorder.write_acquisition_manifest(
        [
            AcquisitionRecord(
                source_id="team-feed",
                source_url=SECRETS["endpoint"],
                license_note="Authorised team feed; terms under review.",
                terms_review_status="review_required",
                retrieved_at="2026-09-08T12:00:00+00:00",
                mapping_revision="team-feed-map-0-unreviewed",
                synthetic=False,
                note=f"configured with Authorization: Bearer {SECRETS['api_token']}",
                config=dict(SECRETS),
            )
        ]
    )
    written = (ChunkReader(tmp_path, SESSION_ID).session_root / "acquisition.json").read_text(
        encoding="utf-8"
    )
    for secret in SECRET_VALUES:
        assert secret not in written
    assert REDACTED in written
    # The non-secret parts survive so provenance is still auditable.
    assert "feed.example.invalid" in written
    assert "review_required" in written


def test_credentials_never_appear_in_a_log_line():
    line = (
        "opened feed https://engineer:s3cr3t@feed.example.invalid/stream?token=tok_live_9f3ab7c21e "
        "with Authorization: Bearer tok_live_9f3ab7c21e and Cookie: session=abcdef123456"
    )
    redacted = redact_text(line)
    for secret in ("s3cr3t", "tok_live_9f3ab7c21e", "abcdef123456"):
        assert secret not in redacted
    assert "feed.example.invalid" in redacted
    assert REDACTED in redacted


def test_redaction_helpers_leave_ordinary_values_alone():
    payload = {"source_id": "public-replay", "rate_hz": 3.7, "limitations": ["no battery-energy channel"]}
    assert redact_mapping(payload) == payload
    assert redact_url("https://openf1.org/docs/") == "https://openf1.org/docs/"
    assert redact_text("no secrets here") == "no secrets here"


def test_redaction_walks_nested_structures():
    payload = {
        "sources": [{"name": "team", "api_key": "abc123def456"}],
        "nested": {"credential": "zzz999yyy888"},
    }
    redacted = redact_mapping(payload)
    assert redacted["sources"][0]["api_key"] == REDACTED
    assert redacted["nested"]["credential"] == REDACTED
    assert redacted["sources"][0]["name"] == "team"


def test_manifest_is_replaced_atomically_and_never_left_partial(tmp_path):
    _, recorder = _recorded(tmp_path)
    recorder.flush()
    reader = ChunkReader(tmp_path, SESSION_ID)
    first = len(reader.manifest())

    # A second import appends chunks; the manifest is rewritten in one step.
    sink = MemorySink()
    pipeline = IngestionPipeline(simulator_config(reorder_window_s=0.0), sink=sink)
    pipeline.ingest_all([observation(50, 5.0, {"speed_mps": 80.0}, received_time_s=5.0)])
    for record in sink.normalised:
        recorder.append_normalised(record)
    recorder.flush()

    assert len(reader.manifest()) > first
    assert reader.verify() == ()
    staging = list(reader.session_root.rglob("*.staging.parquet"))
    assert staging == []


def test_recorder_rejects_a_non_positive_chunk_duration(tmp_path):
    with pytest.raises(ValueError):
        TelemetryRecorder(tmp_path, SESSION_ID, mapping_revision=MAPPING_REVISION, chunk_duration_s=0.0)
