"""Immutable raw-source cache with provenance records (TRACK_DATA_PIPELINE.md).

Every external byte the track pipeline consumes lands here first, under
``artifacts/tracks/raw/<source>/<sha256>/``, together with a JSON record of
where it came from, when, under what permission and with what hash. Compiled
packages reference these records; nothing is compiled from an un-cached fetch.

Coordinator-owned seam shared by the registry, ingestion, validation and
conditions workers. Network access is confined to :meth:`RawSourceCache.fetch`;
tests use :meth:`RawSourceCache.put` with fixture bytes.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..paths import Paths
from .package import SourceRecord

if TYPE_CHECKING:
    from pathlib import Path

USER_AGENT = "afterlap-track-pipeline/1.0 (research simulator; contact via repository)"

FETCHABLE_SCHEMES = frozenset({"http", "https"})
"""Schemes the ingestion cache will open. ``file:`` and ``data:`` are refused.

``urllib.request.urlopen`` honours every scheme its openers register, so a
source manifest naming ``file:///etc/passwd`` would be read and cached as if it
were an upstream document. A track source is a network document; nothing else
is a legitimate value here.
"""


@dataclass(frozen=True, slots=True)
class CachedSource:
    """A raw file on disk plus the provenance record that describes it."""

    record: SourceRecord
    path: Path
    content_type: str | None

    def read_bytes(self) -> bytes:
        data = self.path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        expected = self.record.sha256 or ""
        if digest != expected:
            raise ValueError(
                f"raw source {self.record.source_id} changed on disk: {digest[:12]} != {expected[:12]}"
            )
        return data


class RawSourceCache:
    """Content-addressed store for raw inputs under ``artifacts/tracks/raw``."""

    def __init__(self, root: Path | None = None, *, paths: Paths | None = None) -> None:
        self.root = root or (paths or Paths.default()).artifacts / "tracks" / "raw"

    def _dir(self, source: str, sha256: str) -> Path:
        return self.root / source / sha256

    def put(
        self,
        data: bytes,
        *,
        source: str,
        source_id: str,
        title: str,
        url: str,
        permission: str,
        priority: int | None,
        retrieved_at: datetime | None = None,
        document_revision: str | None = None,
        locator: str | None = None,
        content_type: str | None = None,
        filename: str = "payload.bin",
    ) -> CachedSource:
        """Store bytes immutably and write their provenance record."""
        digest = hashlib.sha256(data).hexdigest()
        directory = self._dir(source, digest)
        directory.mkdir(parents=True, exist_ok=True)
        payload = directory / filename
        if not payload.exists():
            staging = payload.with_suffix(payload.suffix + ".staging")
            staging.write_bytes(data)
            staging.replace(payload)
        record = SourceRecord(
            source_id=source_id,
            title=title,
            url=url,
            retrieved_at=(retrieved_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
            sha256=digest,
            permission=permission,
            priority=priority,
            document_revision=document_revision,
            locator=locator,
        )
        meta = {
            "record": record.model_dump(mode="json"),
            "content_type": content_type,
            "filename": filename,
            "bytes": len(data),
        }
        record_path = directory / "source.json"
        if not record_path.exists():
            record_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
        return CachedSource(record=record, path=payload, content_type=content_type)

    def get(self, source: str, sha256: str) -> CachedSource:
        directory = self._dir(source, sha256)
        record_path = directory / "source.json"
        if not record_path.exists():
            raise FileNotFoundError(f"no cached raw source {source}/{sha256[:12]} under {self.root}")
        meta = json.loads(record_path.read_text(encoding="utf-8"))
        record = SourceRecord.model_validate(meta["record"])
        return CachedSource(
            record=record, path=directory / meta["filename"], content_type=meta.get("content_type")
        )

    def find(self, source: str, url: str, params: dict[str, object] | None = None) -> CachedSource | None:
        """The most recently retrieved cached copy of ``url`` (with ``params``), if any."""
        full = _full_url(url, params)
        best: CachedSource | None = None
        source_dir = self.root / source
        if not source_dir.exists():
            return None
        for record_path in source_dir.glob("*/source.json"):
            meta = json.loads(record_path.read_text(encoding="utf-8"))
            if meta["record"]["url"] != full:
                continue
            candidate = CachedSource(
                record=SourceRecord.model_validate(meta["record"]),
                path=record_path.parent / meta["filename"],
                content_type=meta.get("content_type"),
            )
            if best is None or candidate.record.retrieved_at > best.record.retrieved_at:
                best = candidate
        return best

    def list(self, source: str | None = None) -> tuple[SourceRecord, ...]:
        pattern = f"{source}/*/source.json" if source else "*/*/source.json"
        return tuple(
            SourceRecord.model_validate(json.loads(p.read_text(encoding="utf-8"))["record"])
            for p in sorted(self.root.glob(pattern))
        )

    def fetch(
        self,
        url: str,
        *,
        source: str,
        source_id: str,
        title: str,
        permission: str,
        priority: int | None,
        params: dict[str, object] | None = None,
        document_revision: str | None = None,
        locator: str | None = None,
        filename: str | None = None,
        timeout_s: float = 60.0,
        refresh: bool = False,
    ) -> CachedSource:
        """Retrieve ``url`` once and cache it; later calls return the cached copy.

        ``refresh=True`` fetches again and stores a second, separately hashed
        copy so a changed upstream document is visible as a new revision rather
        than a silent overwrite.
        """
        full = _full_url(url, params)
        if not refresh:
            cached = self.find(source, url, params)
            if cached is not None:
                return cached
        require_fetchable_url(full)
        request = urllib.request.Request(  # noqa: S310 - require_fetchable_url ran above
            full, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            data = response.read()
            content_type = response.headers.get("Content-Type")
        return self.put(
            data,
            source=source,
            source_id=source_id,
            title=title,
            url=full,
            permission=permission,
            priority=priority,
            document_revision=document_revision,
            locator=locator,
            content_type=content_type,
            filename=filename or _guess_filename(full, content_type),
        )


def require_fetchable_url(url: str) -> str:
    """Return ``url`` when it names a network document, else refuse it."""
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in FETCHABLE_SCHEMES:
        raise ValueError(
            f"source url scheme {scheme or '(none)'!r} is not fetchable; "
            f"expected one of {sorted(FETCHABLE_SCHEMES)}"
        )
    return url


def _full_url(url: str, params: dict[str, object] | None) -> str:
    if not params:
        return url
    query = urllib.parse.urlencode({k: str(v) for k, v in sorted(params.items())})
    return f"{url}{'&' if '?' in url else '?'}{query}"


def _guess_filename(url: str, content_type: str | None) -> str:
    kind = (content_type or "").split(";")[0].strip().lower()
    if kind == "application/json":
        return "payload.json"
    if kind == "application/pdf":
        return "document.pdf"
    tail = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
    return tail if tail and "." in tail else "payload.bin"


__all__ = ["FETCHABLE_SCHEMES", "USER_AGENT", "CachedSource", "RawSourceCache", "require_fetchable_url"]
