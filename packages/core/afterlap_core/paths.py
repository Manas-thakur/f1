"""Filesystem layout and the content-addressed artefact store.

Every path a job writes to is validated against a configured root, so a
traversal in a manifest cannot escape the storage area.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator


def implementation_root() -> Path:
    """Root of the implementation workspace (the directory holding pyproject.toml)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() and (parent / "packages").is_dir():
            return parent
    raise RuntimeError("could not locate the implementation workspace root")


@dataclass(frozen=True, slots=True)
class Paths:
    """Resolved storage roots for one runtime."""

    root: Path
    configs: Path
    artifacts: Path
    trajectories: Path
    models: Path
    reports: Path
    exports: Path
    spool: Path

    @classmethod
    def default(cls, root: Path | None = None) -> Paths:
        base = root or Path(os.environ.get("AFTERLAP_ROOT", implementation_root()))
        artifacts = base / "artifacts"
        return cls(
            root=base,
            configs=base / "configs",
            artifacts=artifacts,
            trajectories=artifacts / "trajectories",
            models=artifacts / "models",
            reports=artifacts / "reports",
            exports=artifacts / "exports",
            spool=artifacts / "spool",
        )

    def ensure(self) -> Paths:
        for path in (self.artifacts, self.trajectories, self.models, self.reports, self.exports, self.spool):
            path.mkdir(parents=True, exist_ok=True)
        return self

    def writable_roots(self) -> tuple[Path, ...]:
        return (self.artifacts,)

    def resolve_within(self, candidate: str | Path, root: Path | None = None) -> Path:
        """Resolve ``candidate`` and refuse anything outside a writable root."""
        base = (root or self.artifacts).resolve()
        text = os.fspath(candidate).replace("\\", "/")
        target = (base / text).resolve() if not Path(text).is_absolute() else Path(text).resolve()
        try:
            target.relative_to(base)
        except ValueError as exc:
            raise ValueError(f"path {target} escapes the configured storage root {base}") from exc
        return target


def sha256_file(path: Path, *, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def sha256_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def sha256_json(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return sha256_bytes(text.encode("utf-8"))


def atomic_write_bytes(target: Path, payload: bytes) -> Path:
    """Write via a task-owned temporary file, then rename.

    Readers therefore never observe a partially written artefact.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", dir=target.parent, prefix=f".{target.name}.", suffix=".staging", delete=False
    )
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        Path(handle.name).replace(target)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise
    return target


def atomic_write_text(target: Path, text: str) -> Path:
    return atomic_write_bytes(target, text.encode("utf-8"))


def atomic_write_json(target: Path, payload: Any) -> Path:
    return atomic_write_text(target, json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


class ArtifactStore:
    """Content-addressed local store.

    The database holds references; the bytes live here keyed by SHA-256, so an
    artefact cannot be silently replaced under a stable name.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, digest: str) -> Path:
        if not digest.startswith("sha256:"):
            raise ValueError(f"expected a 'sha256:' prefixed digest, got {digest!r}")
        hex_digest = digest.split(":", 1)[1]
        if len(hex_digest) != 64 or any(c not in "0123456789abcdef" for c in hex_digest):
            raise ValueError(f"malformed digest {digest!r}")
        return self.root / hex_digest[:2] / hex_digest[2:4] / hex_digest

    def put_bytes(self, payload: bytes) -> str:
        digest = sha256_bytes(payload)
        path = self._path_for(digest)
        if not path.exists():
            atomic_write_bytes(path, payload)
        return digest

    def put_json(self, payload: Any) -> str:
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        return self.put_bytes(text.encode("utf-8"))

    def put_file(self, source: Path) -> str:
        digest = sha256_file(source)
        path = self._path_for(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            staging = path.with_suffix(".staging")
            shutil.copy2(source, staging)
            staging.replace(path)
        return digest

    def get_bytes(self, digest: str) -> bytes:
        path = self._path_for(digest)
        if not path.exists():
            raise FileNotFoundError(f"artefact {digest} is not in the store at {self.root}")
        payload = path.read_bytes()
        actual = sha256_bytes(payload)
        if actual != digest:
            raise ValueError(f"artefact {digest} failed hash verification (found {actual})")
        return payload

    def get_json(self, digest: str) -> Any:
        return json.loads(self.get_bytes(digest))

    def has(self, digest: str) -> bool:
        try:
            return self._path_for(digest).exists()
        except ValueError:
            return False

    def path_of(self, digest: str) -> Path:
        path = self._path_for(digest)
        if not path.exists():
            raise FileNotFoundError(f"artefact {digest} is not in the store")
        return path

    def iter_digests(self) -> Iterator[str]:
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and len(path.name) == 64:
                yield f"sha256:{path.name}"


__all__ = [
    "ArtifactStore",
    "Paths",
    "atomic_write_bytes",
    "atomic_write_json",
    "atomic_write_text",
    "implementation_root",
    "sha256_bytes",
    "sha256_file",
    "sha256_json",
]
