"""Raw inputs are content-addressed, provenance-recorded and tamper-evident."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from afterlap_core.tracks.provenance import RawSourceCache


def _put(cache: RawSourceCache, data: bytes, when: datetime, url: str = "https://example.test/doc"):
    return cache.put(
        data,
        source="fixture",
        source_id="fixture-doc",
        title="Fixture document",
        url=url,
        permission="synthetic fixture",
        priority=5,
        retrieved_at=when,
        content_type="application/octet-stream",
    )


def test_put_records_hash_url_time_and_permission(tmp_path):
    cache = RawSourceCache(tmp_path)
    when = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    cached = _put(cache, b"hello", when)
    assert cached.record.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert cached.record.retrieved_at == "2026-09-08T12:00:00Z"
    assert cached.record.permission == "synthetic fixture"
    assert cached.path.exists()
    assert cache.get("fixture", cached.record.sha256).record == cached.record
    assert cache.list("fixture") == (cached.record,)


def test_a_changed_upstream_document_becomes_a_second_revision_not_an_overwrite(tmp_path):
    cache = RawSourceCache(tmp_path)
    first = _put(cache, b"v1", datetime(2026, 1, 1, tzinfo=UTC))
    second = _put(cache, b"v2", datetime(2026, 2, 1, tzinfo=UTC))
    assert first.record.sha256 != second.record.sha256
    assert first.path.read_bytes() == b"v1"
    assert len(cache.list("fixture")) == 2
    assert cache.find("fixture", "https://example.test/doc").record == second.record


def test_disk_tampering_is_detected_on_read(tmp_path):
    cache = RawSourceCache(tmp_path)
    cached = _put(cache, b"original", datetime(2026, 1, 1, tzinfo=UTC))
    cached.path.write_bytes(b"edited")
    with pytest.raises(ValueError, match="changed on disk"):
        cached.read_bytes()


def test_find_distinguishes_query_parameters(tmp_path):
    cache = RawSourceCache(tmp_path)
    _put(cache, b"a", datetime(2026, 1, 1, tzinfo=UTC), url="https://api.test/location?session_key=1")
    assert cache.find("fixture", "https://api.test/location", {"session_key": 1}) is not None
    assert cache.find("fixture", "https://api.test/location", {"session_key": 2}) is None
    assert cache.find("nowhere", "https://api.test/location") is None
