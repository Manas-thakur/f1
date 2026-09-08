"""Bounded durable spool for lifecycle writes a failing database refused.

``08_backend/TECHNICAL_SPEC.md``: *"A temporary DB outage uses a bounded durable
spool with sequence continuity; if exhausted, stop issuing new advice."*

Two properties matter and both are enforced here rather than documented:

* the spool is **bounded**. Appending past its capacity raises
  :class:`SpoolFull`, which is what makes "halt new recommendations" reachable
  instead of an unbounded memory leak that fails much later and much worse;
* entries keep **sequence continuity**. Each entry carries the monotonic
  position it was spooled at, and :meth:`BoundedSpool.drain` returns them in
  that order, so a replay cannot reorder a lifecycle change.

Entries are written with the workspace's atomic write, so a reader never sees a
half-written entry and a crash mid-append leaves the spool consistent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from afterlap_core.paths import atomic_write_json

DEFAULT_CAPACITY = 256


class SpoolFull(RuntimeError):
    """The durable spool is at capacity; new operational advice must stop."""

    def __init__(self, capacity: int, kind: str) -> None:
        super().__init__(
            f"the persistence spool is full ({capacity} entries); refusing to accept a "
            f"{kind!r} write. New recommendations are halted to preserve auditability."
        )
        self.capacity = capacity
        self.kind = kind


@dataclass(frozen=True, slots=True)
class SpoolEntry:
    """One deferred write, with everything needed to replay it verbatim."""

    position: int
    kind: str
    session_id: str
    session_time_s: float
    payload: dict[str, Any]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "kind": self.kind,
            "session_id": self.session_id,
            "session_time_s": self.session_time_s,
            "payload": self.payload,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SpoolEntry:
        return cls(
            position=int(payload["position"]),
            kind=str(payload["kind"]),
            session_id=str(payload["session_id"]),
            session_time_s=float(payload["session_time_s"]),
            payload=dict(payload["payload"]),
            reason=str(payload["reason"]),
        )


class BoundedSpool:
    """Durable, bounded, order-preserving spool for one session."""

    def __init__(self, root: Path, session_id: str, *, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("a spool needs room for at least one entry")
        self.root = Path(root) / session_id
        self.session_id = session_id
        self.capacity = capacity
        self.root.mkdir(parents=True, exist_ok=True)
        self._entries: list[SpoolEntry] = self._load()
        self._next_position = 1 + max((entry.position for entry in self._entries), default=0)

    def _load(self) -> list[SpoolEntry]:
        entries: list[SpoolEntry] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                entries.append(SpoolEntry.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError, KeyError):
                # A truncated entry from an unclean shutdown is dropped rather
                # than replayed as a partial lifecycle change.
                continue
        entries.sort(key=lambda entry: entry.position)
        return entries

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def full(self) -> bool:
        return len(self._entries) >= self.capacity

    @property
    def entries(self) -> tuple[SpoolEntry, ...]:
        return tuple(self._entries)

    def append(self, *, kind: str, session_time_s: float, payload: dict[str, Any], reason: str) -> SpoolEntry:
        if self.full:
            raise SpoolFull(self.capacity, kind)
        entry = SpoolEntry(
            position=self._next_position,
            kind=kind,
            session_id=self.session_id,
            session_time_s=session_time_s,
            payload=payload,
            reason=reason,
        )
        atomic_write_json(self.root / f"{entry.position:09d}.json", entry.as_dict())
        self._entries.append(entry)
        self._next_position += 1
        return entry

    def drain(self) -> tuple[SpoolEntry, ...]:
        """Return every entry in spooled order and clear the spool."""
        drained = tuple(self._entries)
        for entry in drained:
            (self.root / f"{entry.position:09d}.json").unlink(missing_ok=True)
        self._entries.clear()
        return drained

    def peek(self) -> SpoolEntry | None:
        return self._entries[0] if self._entries else None


__all__ = ["DEFAULT_CAPACITY", "BoundedSpool", "SpoolEntry", "SpoolFull"]
