"""Load a hash-pinned real-circuit package as a simulator track source.

Coordinator-owned seam. ``load_track`` in the simulation package falls back to
this when no synthetic sketch YAML exists for a track id. A package that is
absent, unhashed, hash-mismatched or below the readiness rung a caller demands
is refused with a named reason rather than defaulted.

Layout under ``artifacts/tracks/<track_id>/``:

    package.json      -- TrackPackage, with package_hash set
    centreline.npz    -- CompiledCentreline arrays (sha256 recorded in package)
    events/<event_id>.json  -- optional EventOverlay documents
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from ..paths import Paths
from .package import CompiledCentreline, EventOverlay, ReadinessStatus, TrackPackage, readiness_rank

if TYPE_CHECKING:
    from pathlib import Path


class TrackPackageError(FileNotFoundError):
    """A track package could not be loaded honestly.

    Subclasses ``FileNotFoundError`` so the existing ``load_track`` callers that
    treat a missing track as not-found keep their semantics.
    """


def package_dir(track_id: str, paths: Paths | None = None) -> Path:
    return (paths or Paths.default()).artifacts / "tracks" / track_id


def package_path(track_id: str, paths: Paths | None = None) -> Path:
    return package_dir(track_id, paths) / "package.json"


def centreline_path(track_id: str, paths: Paths | None = None) -> Path:
    return package_dir(track_id, paths) / "centreline.npz"


def event_overlay_path(track_id: str, event_id: str, paths: Paths | None = None) -> Path:
    return package_dir(track_id, paths) / "events" / f"{event_id}.json"


def load_track_package(track_id: str, paths: Paths | None = None) -> TrackPackage:
    """Load and verify a package document. Refuses an unhashed or tampered file."""
    path = package_path(track_id, paths)
    if not path.exists():
        raise TrackPackageError(
            f"track {track_id!r} has neither a synthetic sketch in configs/tracks nor a compiled "
            f"package at {path}"
        )
    package = TrackPackage.model_validate(json.loads(path.read_text(encoding="utf-8")))
    if package.package_hash is None:
        raise TrackPackageError(f"track package {track_id!r} carries no package_hash; it was never frozen")
    recomputed = package.content_hash()
    if recomputed != package.package_hash:
        raise TrackPackageError(
            f"track package {track_id!r} failed hash verification: stored {package.package_hash[:12]}, "
            f"recomputed {recomputed[:12]}"
        )
    if package.track_id != track_id:
        raise TrackPackageError(f"package at {path} declares track_id {package.track_id!r}, not {track_id!r}")
    return package


def load_centreline(track_id: str, package: TrackPackage, paths: Paths | None = None) -> CompiledCentreline:
    """Load the arrays and verify them against the hash the package recorded."""
    path = centreline_path(track_id, paths)
    if not path.exists():
        raise TrackPackageError(f"track package {track_id!r} has no compiled centreline at {path}")
    if package.geometry.arrays_sha256 is not None:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != package.geometry.arrays_sha256:
            raise TrackPackageError(
                f"centreline for {track_id!r} failed hash verification: package records "
                f"{package.geometry.arrays_sha256[:12]}, file is {actual[:12]}"
            )
    centreline = CompiledCentreline.from_npz(path)
    if centreline.point_count != package.geometry.point_count:
        raise TrackPackageError(
            f"centreline for {track_id!r} has {centreline.point_count} samples; package declares "
            f"{package.geometry.point_count}"
        )
    return centreline


def load_event_overlay(track_id: str, event_id: str, paths: Paths | None = None) -> EventOverlay:
    path = event_overlay_path(track_id, event_id, paths)
    if not path.exists():
        raise TrackPackageError(f"no event overlay {event_id!r} for track {track_id!r} at {path}")
    return EventOverlay.model_validate(json.loads(path.read_text(encoding="utf-8")))


def require_readiness(package: TrackPackage, minimum: ReadinessStatus) -> None:
    """Refuse a package below the rung a caller needs, naming both."""
    if readiness_rank(package.validation.status) < readiness_rank(minimum):
        raise TrackPackageError(
            f"track {package.track_id!r} is {package.validation.status.value}; {minimum.value} is required. "
            "Readiness is derived from validation evidence and cannot be edited into place."
        )


def load_track_package_source(track_id: str, paths: Paths | None = None) -> Any:
    """The ``load_track`` fallback: a verified package as a ``TrackSource``.

    Any readiness rung loads here, because the simulator may legitimately run
    a ``geometry_validated`` circuit as a *real-circuit synthetic scenario*.
    Callers that need more (a real-track *claim*) call :func:`require_readiness`.
    """
    from ..simulation.track_source import CompiledTrackSource

    package = load_track_package(track_id, paths)
    require_readiness(package, ReadinessStatus.GEOMETRY_VALIDATED)
    centreline = load_centreline(track_id, package, paths)
    return CompiledTrackSource(package, centreline)


def list_track_packages(paths: Paths | None = None) -> tuple[str, ...]:
    root = (paths or Paths.default()).artifacts / "tracks"
    if not root.exists():
        return ()
    return tuple(sorted(p.parent.name for p in root.glob("*/package.json")))


__all__ = [
    "TrackPackageError",
    "centreline_path",
    "event_overlay_path",
    "list_track_packages",
    "load_centreline",
    "load_event_overlay",
    "load_track_package",
    "load_track_package_source",
    "package_dir",
    "package_path",
    "require_readiness",
]
