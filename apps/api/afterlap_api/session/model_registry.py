"""Discovering the model bundles a control plane may actually serve.

``SessionFactory`` accepted a ``model_bundles`` mapping and nothing ever
populated it, so every request naming a ``model_bundle_id`` returned 404 and
``GET /models`` read a database table no code wrote. The registry and the
runtime were not connected at either end.

This scans the local artefact tree and returns only bundles that survive
validation, because the alternative -- listing a directory of weights as an
available model -- is how an operator ends up selecting an artifact that cannot
load. Every rejected directory is kept with its reason so the listing can say
what was found and refused rather than silently showing a shorter list.

Nothing here promotes anything. A discovered bundle carries whatever
``approval_status`` its manifest declares, and an unapproved bundle is
discovered, listed and refused a contribution.

The learning extra is optional. Discovery reads ``bundle.json`` and validates
its declared hashes with no torch involved, so a default install can list what
exists and report that it cannot serve it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from afterlap_contracts import ApprovalStatus, ModelManifest
from afterlap_core.feature_manifest import ENERGY_V1
from afterlap_core.paths import Paths, sha256_file

__all__ = [
    "BUNDLE_ROOT",
    "DiscoveredBundle",
    "ModelRegistry",
    "discover_bundles",
    "load_prediction_service",
]

BUNDLE_ROOT = "bundles"
_BUNDLE_FILE = "bundle.json"


@dataclass(frozen=True, slots=True)
class DiscoveredBundle:
    """One bundle found on disk, with its manifest and its directory."""

    bundle_id: str
    directory: Path
    manifest: ModelManifest

    @property
    def approved(self) -> bool:
        return self.manifest.approval_status is ApprovalStatus.APPROVED

    def as_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "directory": str(self.directory).replace("\\", "/"),
            "weights_hash": self.manifest.weights_hash,
            "approval_status": self.manifest.approval_status.value,
            "rule_family": self.manifest.rule_family,
            "reward_revision": self.manifest.reward_revision,
            "feature_schema_hash": self.manifest.feature_schema_hash,
        }


@dataclass(frozen=True, slots=True)
class ModelRegistry:
    """What the artefact tree offers, and what it offered and could not serve."""

    bundles: dict[str, DiscoveredBundle] = field(default_factory=dict)
    rejected: dict[str, str] = field(default_factory=dict)
    root: Path | None = None

    @property
    def manifests(self) -> dict[str, ModelManifest]:
        """The mapping ``SessionFactory`` and ``resolve_artefacts`` consume."""
        return {bundle_id: found.manifest for bundle_id, found in self.bundles.items()}

    def approved(self) -> dict[str, DiscoveredBundle]:
        return {key: found for key, found in self.bundles.items() if found.approved}

    def directory_for(self, bundle_id: str | None) -> Path | None:
        if bundle_id is None:
            return None
        found = self.bundles.get(bundle_id)
        return None if found is None else found.directory

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": None if self.root is None else str(self.root).replace("\\", "/"),
            "bundles": [found.as_dict() for _, found in sorted(self.bundles.items())],
            "approved_count": len(self.approved()),
            "rejected": dict(sorted(self.rejected.items())),
            "note": (
                "a rejected directory is listed with its reason rather than omitted; a directory "
                "of weights that cannot be validated is not an available model"
            ),
        }


def _validate_declared_hashes(directory: Path, payload: dict[str, Any]) -> str | None:
    """Re-hash every declared artifact. Returns the first problem, or ``None``."""
    hashes = payload.get("artifact_hashes") or {}
    if not hashes:
        return "the bundle declares no artifact hashes"
    for name, expected in sorted(hashes.items()):
        path = directory / str(name)
        if not path.is_file():
            return f"declared artifact {name!r} is absent"
        if sha256_file(path) != expected:
            return f"artifact {name!r} does not match its declared hash"
    return None


def discover_bundles(paths: Paths | None = None, *, root: Path | None = None) -> ModelRegistry:
    """Scan the artefact tree for bundles, refusing anything that fails validation.

    Feature-schema mismatch is a rejection rather than a silent omission: an
    operator who trained a bundle under another feature revision needs to be
    told that is why it is not offered.
    """
    resolved = paths or Paths.default()
    base = Path(root) if root is not None else resolved.models / BUNDLE_ROOT
    if not base.is_dir():
        return ModelRegistry(root=base)

    found: dict[str, DiscoveredBundle] = {}
    rejected: dict[str, str] = {}
    for directory in sorted(p for p in base.iterdir() if p.is_dir()):
        bundle_file = directory / _BUNDLE_FILE
        key = directory.name
        if not bundle_file.is_file():
            rejected[key] = f"{directory.name} has no {_BUNDLE_FILE}; a directory of weights is not a bundle"
            continue
        try:
            payload = json.loads(bundle_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            rejected[key] = f"{_BUNDLE_FILE} is unreadable: {exc}"
            continue
        problem = _validate_declared_hashes(directory, payload)
        if problem is not None:
            rejected[key] = problem
            continue
        try:
            manifest = ModelManifest.model_validate(payload["model_manifest"])
        except Exception as exc:
            rejected[key] = f"the model manifest did not validate: {exc}"
            continue
        if manifest.feature_schema_hash != ENERGY_V1.content_hash():
            rejected[manifest.id] = (
                f"bundle was trained against feature schema {manifest.feature_schema_hash} but "
                f"this runtime encodes {ENERGY_V1.content_hash()}"
            )
            continue
        found[manifest.id] = DiscoveredBundle(bundle_id=manifest.id, directory=directory, manifest=manifest)
    return ModelRegistry(bundles=found, rejected=rejected, root=base)


def load_prediction_service(
    directory: Path | None,
    *,
    expected_rule_family: str | None = None,
    expected_reward_revision: str | None = None,
    baseline_identity: str,
) -> tuple[Any | None, str]:
    """The prediction service for a pinned bundle, or the reason there is none.

    Returns ``(None, reason)`` rather than raising for every path an operator
    can reach: no bundle pinned, the learning extra absent, or a bundle the
    loader refused. Each reason is published on the recommendation, because
    "the baseline answered" is not an explanation on its own.
    """
    if directory is None:
        return None, f"no learned bundle is pinned for this session; {baseline_identity} answers"
    try:
        from afterlap_core.learning.prediction import PredictionUnavailable, service_from_directory
    except ImportError as exc:
        return None, (
            f"the learning extra is not installed, so no learned model can be served ({exc}); "
            f"{baseline_identity} answers"
        )
    result = service_from_directory(
        directory,
        expected_rule_family=expected_rule_family,
        expected_reward_revision=expected_reward_revision,
        baseline_identity=baseline_identity,
    )
    if isinstance(result, PredictionUnavailable):
        return None, f"{result.reason}: {result.detail}"
    return result, ""
