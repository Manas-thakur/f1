"""2026 circuit registry and per-track source manifests (A16-1).

The registry separates *calendar identity* (``event_id``, one per round) from
*physical circuit identity* (``track_id``), as TRACK_REGISTRY_2026.md requires:
the 2026 Bahrain Grand Prix runs at Sepang, so one event can point at a
circuit whose name it does not share.

Two documents live here:

* ``configs/tracks/registry/season_<year>.json`` -- the machine registry. Every
  numeric field carries its provenance; a value the source snapshot did not
  provide is ``null``, never ``0`` and never guessed. ``readiness`` defaults to
  ``discovered`` and is informational only: the validator derives the real rung
  from evidence (see ``package.py``).
* ``configs/tracks/<track_id>/source.yaml`` -- a source manifest declaring which
  OpenF1 sessions, FIA documents and official pages the compiler may consume
  for one circuit. A manifest must name a registry track id; the field names
  are fixed in ``handoffs/A16-1.md`` so the compile worker can rely on them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..paths import Paths
from .package import Direction, ReadinessStatus

TRACK_ID_PATTERN = r"^[a-z0-9-]+$"
DEFAULT_SEASON = 2026
_TRACK_ID_RE = re.compile(TRACK_ID_PATTERN)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class LengthProvenance(_Frozen):
    """An official circuit length with the record of where it was read.

    ``value`` is a gross-scale check (TRACK_REGISTRY_2026.md), not geometry.
    ``sha256`` is set only when the page was actually retrieved into the
    :class:`~afterlap_core.tracks.provenance.RawSourceCache`; a value copied
    from the specification snapshot keeps ``retrieved_at`` and ``sha256`` null.
    """

    value: float | None = Field(default=None, gt=0.0, description="Metres.")
    source_url: str | None = None
    retrieved_at: str | None = Field(default=None, description="ISO-8601 UTC of the actual retrieval.")
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    note: str | None = None

    @property
    def verified(self) -> bool:
        """True only when the value was read from a hashed retrieval."""
        return self.value is not None and self.sha256 is not None and self.retrieved_at is not None


class EventEntry(_Frozen):
    """One calendar round that visits a physical circuit."""

    event_id: str = Field(min_length=1, pattern=r"^[0-9]{4}-[a-z0-9-]+$")
    event_name: str = Field(min_length=1)
    round: int | None = Field(default=None, ge=1)
    event_date: str | None = Field(
        default=None, description="ISO-8601 date if the source gave one; the 2026 snapshot did not."
    )
    race_laps: int | None = Field(default=None, ge=1)
    f1_page: str | None = None


class RegistryEntry(_Frozen):
    """Identity of one physical circuit plus the rounds that visit it."""

    track_id: str = Field(min_length=1, pattern=TRACK_ID_PATTERN)
    display_name: str = Field(min_length=1)
    country: str | None = None
    official_length_m: LengthProvenance = LengthProvenance()
    direction: Direction | None = None
    events: tuple[EventEntry, ...] = ()
    readiness: ReadinessStatus = ReadinessStatus.DISCOVERED
    notes: tuple[str, ...] = ()

    @property
    def event_ids(self) -> tuple[str, ...]:
        return tuple(event.event_id for event in self.events)


class Registry(_Frozen):
    """The season registry: unique track ids, unique event ids."""

    schema_version: str = "1"
    season: int = Field(ge=1950)
    snapshot_date: str | None = None
    status: str | None = None
    calendar_source: str | None = None
    notes: tuple[str, ...] = ()
    entries: tuple[RegistryEntry, ...] = ()

    @model_validator(mode="after")
    def _identities_are_unique(self) -> Registry:
        seen_tracks: set[str] = set()
        seen_events: set[str] = set()
        for entry in self.entries:
            if entry.track_id in seen_tracks:
                raise ValueError(f"duplicate track_id {entry.track_id!r} in registry")
            seen_tracks.add(entry.track_id)
            for event in entry.events:
                if event.event_id in seen_events:
                    raise ValueError(f"duplicate event_id {event.event_id!r} in registry")
                seen_events.add(event.event_id)
        return self

    @property
    def track_ids(self) -> tuple[str, ...]:
        return tuple(entry.track_id for entry in self.entries)

    def get(self, track_id: str) -> RegistryEntry:
        for entry in self.entries:
            if entry.track_id == track_id:
                return entry
        raise KeyError(f"track_id {track_id!r} is not in the {self.season} registry")

    def find_event(self, event_id: str) -> tuple[RegistryEntry, EventEntry]:
        for entry in self.entries:
            for event in entry.events:
                if event.event_id == event_id:
                    return entry, event
        raise KeyError(f"event_id {event_id!r} is not in the {self.season} registry")

    def __contains__(self, track_id: object) -> bool:
        return isinstance(track_id, str) and any(e.track_id == track_id for e in self.entries)


# --------------------------------------------------------------------------- #
# Source manifests
# --------------------------------------------------------------------------- #


class OpenF1Session(_Frozen):
    """An OpenF1 session the compiler may read ``/location`` telemetry from."""

    session_key: int = Field(ge=1)
    year: int = Field(ge=2018)
    session_name: str = Field(min_length=1)
    driver_number: int | None = Field(default=None, ge=1, le=99)
    note: str | None = None


class OpenF1Sources(_Frozen):
    sessions: tuple[OpenF1Session, ...] = ()


class FiaDocumentRef(_Frozen):
    """A public FIA decision document declared for one event."""

    event_id: str = Field(min_length=1, pattern=r"^[0-9]{4}-[a-z0-9-]+$")
    url: str = Field(min_length=1)
    title: str = Field(min_length=1)


class Permissions(_Frozen):
    geometry: str = Field(min_length=1)
    documents: str = Field(min_length=1)


class SourceManifest(_Frozen):
    """``configs/tracks/<track_id>/source.yaml``; field names fixed in handoffs/A16-1.md."""

    track_id: str = Field(min_length=1, pattern=TRACK_ID_PATTERN)
    display_name: str = Field(min_length=1)
    direction: Direction
    official_length_m: LengthProvenance = LengthProvenance()
    openf1: OpenF1Sources = OpenF1Sources()
    fia_documents: tuple[FiaDocumentRef, ...] = ()
    permissions: Permissions

    @model_validator(mode="after")
    def _sessions_are_unique(self) -> SourceManifest:
        keys = [s.session_key for s in self.openf1.sessions]
        if len(keys) != len(set(keys)):
            raise ValueError(f"manifest {self.track_id!r} lists an OpenF1 session key twice")
        return self


class ManifestRegistryMismatch(ValueError):
    """A manifest names a track id or event id the registry does not know."""


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def registry_path(paths: Paths | None = None, season: int = DEFAULT_SEASON) -> Path:
    return (paths or Paths.default()).configs / "tracks" / "registry" / f"season_{season}.json"


def load_registry(paths: Paths | None = None, season: int = DEFAULT_SEASON) -> Registry:
    path = registry_path(paths, season)
    if not path.exists():
        raise FileNotFoundError(f"no circuit registry for season {season} at {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    return Registry.model_validate(document)


def manifest_path(track_id: str, paths: Paths | None = None) -> Path:
    if not _TRACK_ID_RE.match(track_id):
        raise ValueError(f"track_id {track_id!r} does not match {TRACK_ID_PATTERN}")
    return (paths or Paths.default()).configs / "tracks" / track_id / "source.yaml"


def list_source_manifests(paths: Paths | None = None) -> tuple[str, ...]:
    root = (paths or Paths.default()).configs / "tracks"
    if not root.exists():
        return ()
    return tuple(sorted(p.parent.name for p in root.glob("*/source.yaml")))


def parse_source_manifest(document: dict[str, Any], registry: Registry | None = None) -> SourceManifest:
    """Validate a manifest document; with a registry, also require a known track and events."""
    manifest = SourceManifest.model_validate(document)
    if registry is not None:
        check_manifest_against_registry(manifest, registry)
    return manifest


def check_manifest_against_registry(manifest: SourceManifest, registry: Registry) -> RegistryEntry:
    if manifest.track_id not in registry:
        raise ManifestRegistryMismatch(
            f"source manifest names track_id {manifest.track_id!r}, which is not in the "
            f"{registry.season} registry"
        )
    entry = registry.get(manifest.track_id)
    known_events = set(entry.event_ids)
    for document in manifest.fia_documents:
        if document.event_id not in known_events:
            raise ManifestRegistryMismatch(
                f"manifest {manifest.track_id!r} declares FIA document for event {document.event_id!r}, "
                f"which the registry does not attach to that circuit (known: {sorted(known_events)})"
            )
    return entry


def load_source_manifest(
    source: str | Path, paths: Paths | None = None, registry: Registry | None = None
) -> SourceManifest:
    """Load ``source.yaml`` for a track id or from an explicit path.

    When ``registry`` is omitted the season registry is loaded from ``paths`` so
    a manifest can never be accepted for a circuit the registry does not know.
    """
    path = Path(source) if isinstance(source, Path) or str(source).endswith((".yaml", ".yml")) else None
    if path is None:
        path = manifest_path(str(source), paths)
    if not path.exists():
        raise FileNotFoundError(f"no source manifest at {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"source manifest {path} is not a mapping")
    if registry is None:
        registry = load_registry(paths)
    return parse_source_manifest(document, registry)


__all__ = [
    "DEFAULT_SEASON",
    "TRACK_ID_PATTERN",
    "EventEntry",
    "FiaDocumentRef",
    "LengthProvenance",
    "ManifestRegistryMismatch",
    "OpenF1Session",
    "OpenF1Sources",
    "Permissions",
    "Registry",
    "RegistryEntry",
    "SourceManifest",
    "check_manifest_against_registry",
    "list_source_manifests",
    "load_registry",
    "load_source_manifest",
    "manifest_path",
    "parse_source_manifest",
    "registry_path",
]
