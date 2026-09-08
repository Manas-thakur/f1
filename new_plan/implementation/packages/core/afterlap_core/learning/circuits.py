"""The frozen circuit split and the no-track-identity check (A16-7).

``RL_TRACK_GENERALISATION.md`` asks for a group split frozen before training,
recorded on every training manifest, and for the track id to stay out of the
actor's features. This module is the reader for ``configs/learning/
circuit-split-v1.yaml`` and the check that the frozen feature contract carries
no circuit identity.

A :class:`CircuitSplit` is content-hashed as a whole; ``split_hash`` is what a
run manifest records. Readiness is deliberately not part of the split document:
whether a listed circuit is *usable* is derived from its package's validation
evidence at load time by :func:`afterlap_core.simulation.config.load_track`,
which refuses anything below ``geometry_validated``. :func:`circuit_readiness`
and :func:`group_availability` are that derivation, so a caller can say which
listed circuits are runnable today and *why* the rest are not, without editing
a rung into the split. A pending circuit is skipped with its reason recorded; it
is never replaced by another circuit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from afterlap_contracts import FeatureManifest

from ..config import load_config
from ..paths import Paths, sha256_json

__all__ = [
    "CIRCUIT_SPLIT_REVISION",
    "REQUIRED_READINESS",
    "SPLIT_GROUPS",
    "CircuitReadiness",
    "CircuitSplit",
    "EnergyDistribution",
    "GroupAvailability",
    "TrackIdentityLeak",
    "assert_no_track_identity_in_features",
    "circuit_readiness",
    "group_availability",
    "load_circuit_split",
    "split_readiness",
]

CIRCUIT_SPLIT_REVISION = "circuit-split-v1"
SPLIT_GROUPS: tuple[str, ...] = ("train", "calibration", "heldout_circuits", "heldout_conditions")

REQUIRED_READINESS = "geometry_validated"
"""The lowest rung ``load_track`` will resolve a compiled package at.

A circuit below it cannot be simulated at all, so an episode on it cannot be
built. This constant mirrors the rung
:func:`afterlap_core.tracks.loader.load_track_package_source` requires; it does
not grant readiness to anything.
"""

_FORBIDDEN_FEATURE_TOKENS: tuple[str, ...] = (
    "track_id",
    "track_hash",
    "track_index",
    "track_name",
    "circuit",
    "venue",
    "event_id",
    "embedding",
    "package_hash",
)
"""Substrings that would name a circuit identity in a feature or its note.

``lap_fraction`` and the lookahead geometry are *functions of position on the
geometry*, which the actor is meant to see; an id, hash or index of the circuit
is what it may not see.
"""


class TrackIdentityLeak(AssertionError):
    """The feature manifest carries a value derivable from the circuit identity."""


@dataclass(frozen=True, slots=True)
class EnergyDistribution:
    """The declared synthetic own-energy distribution the sampler draws from."""

    label: str
    source: str
    distribution: str
    low_j: float
    high_j: float

    def __post_init__(self) -> None:
        if self.distribution != "uniform":
            raise ValueError(
                f"unsupported energy distribution {self.distribution!r}; only 'uniform' is declared"
            )
        if not 0.0 <= self.low_j < self.high_j:
            raise ValueError("energy distribution needs 0 <= low_j < high_j")
        if self.label != "real_circuit_synthetic_energy":
            raise ValueError("own energy on a real circuit must be labelled real_circuit_synthetic_energy")


@dataclass(frozen=True, slots=True)
class CircuitSplit:
    """The frozen group split, its coherent condition regimes and sampling declarations."""

    revision: str
    split_hash: str
    train: tuple[str, ...]
    calibration: tuple[str, ...]
    heldout_circuits: tuple[str, ...]
    heldout_conditions: tuple[str, ...]
    scenario_documents: dict[str, str]
    training_conditions: dict[str, tuple[str, ...]]
    heldout_condition_tapes: dict[str, tuple[str, ...]]
    decision_interval_m: float
    energy: EnergyDistribution
    seed_low: int
    seed_high: int
    status_note: str

    def __post_init__(self) -> None:
        for name in SPLIT_GROUPS:
            ids = self.group(name)
            if len(set(ids)) != len(ids):
                raise ValueError(f"split group {name!r} lists a track twice")
        seen = set(self.train) | set(self.calibration)
        leaked = seen & set(self.heldout_circuits)
        if leaked:
            raise ValueError(f"held-out circuits {sorted(leaked)} also appear in train/calibration")
        if set(self.train) & set(self.calibration):
            raise ValueError("a circuit cannot be both a training and a calibration circuit")
        outside = set(self.heldout_conditions) - seen
        if outside:
            raise ValueError(
                f"heldout_conditions names {sorted(outside)}, which are not trained/calibration circuits; "
                "that group is for unseen condition combinations on seen circuits"
            )
        for track_id, tapes in self.training_conditions.items():
            heldout = set(self.heldout_condition_tapes.get(track_id, ()))
            both = heldout & set(tapes)
            if both:
                raise ValueError(f"tapes {sorted(both)} for {track_id!r} are both training and held-out")
        if self.decision_interval_m <= 0.0:
            raise ValueError("decision_interval_m must be positive")
        if not 0 <= self.seed_low < self.seed_high:
            raise ValueError("seed range must satisfy 0 <= low < high")

    def group(self, name: str) -> tuple[str, ...]:
        if name not in SPLIT_GROUPS:
            raise KeyError(f"unknown split group {name!r}; groups are {SPLIT_GROUPS}")
        value: tuple[str, ...] = getattr(self, name)
        return value

    @property
    def all_track_ids(self) -> tuple[str, ...]:
        ordered: list[str] = []
        for name in SPLIT_GROUPS:
            for track_id in self.group(name):
                if track_id not in ordered:
                    ordered.append(track_id)
        return tuple(ordered)

    def tapes_for(self, track_id: str, group: str) -> tuple[str, ...]:
        """Coherent condition tapes a sampler for ``group`` may draw for ``track_id``.

        The held-out tapes are only reachable through the ``heldout_conditions``
        group. An empty tuple means no coherent regime is declared; the sampler
        reports that rather than substituting the static reference.
        """
        if group == "heldout_conditions":
            return self.heldout_condition_tapes.get(track_id, ())
        return self.training_conditions.get(track_id, ())

    def as_manifest(self, readiness: Mapping[str, CircuitReadiness] | None = None) -> dict[str, Any]:
        """What a training manifest records: the groups and the hash.

        ``readiness``, when given, adds the *derived* usability of each listed
        circuit under the readiness rung ``load_track`` requires. It is recorded
        separately from the groups and it does not enter ``split_hash``: the
        split is frozen, readiness is evidence that changes as packages are
        revalidated. A run whose manifest shows a pending circuit did not sample
        that circuit, and the reason is on the record.
        """
        manifest: dict[str, Any] = {
            "revision": self.revision,
            "split_hash": self.split_hash,
            "groups": {name: list(self.group(name)) for name in SPLIT_GROUPS},
            "energy_label": self.energy.label,
        }
        if readiness is not None:
            resolved = {track_id: _require(readiness, track_id) for track_id in self.all_track_ids}
            manifest["readiness"] = {
                "required": REQUIRED_READINESS,
                "status": {track_id: entry.status for track_id, entry in resolved.items()},
                "usable": [track_id for track_id, entry in resolved.items() if entry.usable],
                "pending": {
                    track_id: entry.reason for track_id, entry in resolved.items() if entry.reason is not None
                },
            }
        return manifest


def load_circuit_split(config_id: str = CIRCUIT_SPLIT_REVISION, paths: Paths | None = None) -> CircuitSplit:
    document = load_config("learning", config_id, paths)
    groups = document["groups"]
    missing = [name for name in SPLIT_GROUPS if name not in groups]
    if missing:
        raise KeyError(f"circuit split {config_id!r} lacks groups {missing}")
    conditions = document.get("conditions", {})
    energy = document["energy"]
    seeds = document.get("seeds", {})
    return CircuitSplit(
        revision=str(document["id"]),
        split_hash=sha256_json(document),
        train=tuple(str(t) for t in groups["train"]),
        calibration=tuple(str(t) for t in groups["calibration"]),
        heldout_circuits=tuple(str(t) for t in groups["heldout_circuits"]),
        heldout_conditions=tuple(str(t) for t in groups["heldout_conditions"]),
        scenario_documents={str(k): str(v) for k, v in document.get("scenario_documents", {}).items()},
        training_conditions={
            str(k): tuple(str(x) for x in v) for k, v in conditions.get("training", {}).items()
        },
        heldout_condition_tapes={
            str(k): tuple(str(x) for x in v) for k, v in conditions.get("heldout", {}).items()
        },
        decision_interval_m=float(document["balance"]["decision_interval_m"]),
        energy=EnergyDistribution(
            label=str(energy["label"]),
            source=str(energy["source"]),
            distribution=str(energy["distribution"]),
            low_j=float(energy["low_j"]),
            high_j=float(energy["high_j"]),
        ),
        seed_low=int(seeds.get("low", 1)),
        seed_high=int(seeds.get("high", 1_000_000)),
        status_note=str(document.get("status_note", "")),
    )


# --------------------------------------------------------------------------- #
# Derived readiness: which listed circuits can actually be simulated today
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CircuitReadiness:
    """Whether one listed circuit can be loaded, derived from its package.

    ``status`` is the package's readiness rung, or ``None`` when there is no
    compiled package at all — an unknown rung is never reported as a rung.
    ``reason`` is set exactly when ``usable`` is false and always names the rung
    found and the rung required, because that is what a caller has to put in
    front of a human.
    """

    track_id: str
    status: str | None
    usable: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.usable and self.reason is not None:
            raise ValueError("a usable circuit must not carry an unusability reason")
        if not self.usable and not self.reason:
            raise ValueError("an unusable circuit must record why")

    def as_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "status": self.status,
            "usable": self.usable,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class GroupAvailability:
    """One split group narrowed to the circuits that load, and why the rest do not.

    ``usable`` keeps the split's own order. ``pending`` maps every skipped
    circuit to its reason. Nothing is substituted for a skipped circuit: a group
    whose circuits are all pending has an empty ``usable`` and the caller is
    expected to refuse rather than sample something else.
    """

    group: str
    usable: tuple[str, ...]
    pending: dict[str, str] = field(default_factory=dict)

    @property
    def any_usable(self) -> bool:
        return bool(self.usable)

    def refusal(self) -> str:
        """One message naming the group and every reason it cannot be sampled."""
        reasons = "; ".join(f"{track_id}: {reason}" for track_id, reason in sorted(self.pending.items()))
        return (
            f"no circuit in split group {self.group!r} has a package at {REQUIRED_READINESS} or above, "
            f"so no episode can be built for it. {reasons}"
        )


def circuit_readiness(track_id: str, paths: Paths | None = None) -> CircuitReadiness:
    """Derive whether ``track_id`` can be simulated, from its package's evidence.

    A compiled package at or above ``geometry_validated`` is usable. Anything
    else — a lower rung, ``rejected``, an unfrozen or hash-mismatched package,
    or no package at all — is not, and the reason is the loader's own message so
    the rung is named exactly once, by the code that owns it.
    """
    from ..tracks.loader import TrackPackageError, load_track_package, require_readiness
    from ..tracks.package import ReadinessStatus

    try:
        package = load_track_package(track_id, paths)
    except TrackPackageError as error:
        return CircuitReadiness(
            track_id=track_id,
            status=None,
            usable=False,
            reason=(
                f"no usable compiled track package: {error}. {REQUIRED_READINESS} is required and "
                "readiness is derived from validation evidence, not declared."
            ),
        )
    status = str(package.validation.status.value)
    try:
        require_readiness(package, ReadinessStatus.GEOMETRY_VALIDATED)
    except TrackPackageError as error:
        return CircuitReadiness(track_id=track_id, status=status, usable=False, reason=str(error))
    return CircuitReadiness(track_id=track_id, status=status, usable=True)


def split_readiness(split: CircuitSplit, paths: Paths | None = None) -> dict[str, CircuitReadiness]:
    """Derived readiness for every circuit the split lists, in split order."""
    return {track_id: circuit_readiness(track_id, paths) for track_id in split.all_track_ids}


def group_availability(
    split: CircuitSplit,
    group: str,
    *,
    paths: Paths | None = None,
    readiness: Mapping[str, CircuitReadiness] | None = None,
) -> GroupAvailability:
    """Narrow one split group to the circuits whose packages load.

    ``readiness`` overrides the on-disk derivation. It exists so a caller that
    has already resolved readiness once does not re-read every package, and so
    an in-memory split of stand-in circuits can be reasoned about; it cannot
    make a real package loadable, because ``load_track`` still checks the rung
    when the bundle is built.
    """
    usable: list[str] = []
    pending: dict[str, str] = {}
    for track_id in split.group(group):
        entry = _require(readiness, track_id) if readiness is not None else circuit_readiness(track_id, paths)
        if entry.usable:
            usable.append(track_id)
        else:
            assert entry.reason is not None  # guaranteed by CircuitReadiness
            pending[track_id] = entry.reason
    return GroupAvailability(group=group, usable=tuple(usable), pending=pending)


def _require(readiness: Mapping[str, CircuitReadiness], track_id: str) -> CircuitReadiness:
    try:
        return readiness[track_id]
    except KeyError as error:
        raise KeyError(
            f"readiness for circuit {track_id!r} was not supplied; a missing rung is not assumed usable"
        ) from error


def _known_identities(paths: Paths | None) -> tuple[str, ...]:
    """Every string that would identify a circuit: registry ids and names, package ids and hashes."""
    identities: list[str] = []
    try:
        from ..tracks.registry import load_registry

        registry = load_registry(paths)
        for entry in registry.entries:
            identities.append(entry.track_id)
            identities.append(entry.display_name)
            identities.extend(event.event_id for event in entry.events)
    except FileNotFoundError:
        pass
    from ..tracks.loader import TrackPackageError, list_track_packages, load_track_package

    for track_id in list_track_packages(paths):
        identities.append(track_id)
        try:
            package = load_track_package(track_id, paths)
        except TrackPackageError:
            continue
        if package.package_hash:
            identities.append(package.package_hash)
            identities.append(package.package_hash[:12])
    return tuple(identity.lower().replace("-", "_") for identity in identities if identity)


def assert_no_track_identity_in_features(manifest: FeatureManifest, paths: Paths | None = None) -> None:
    """Fail if the feature contract exposes anything derivable from the track id.

    Checks every field name and provenance note for the forbidden identity
    tokens, for any known track id, display name, event id or package hash, and
    for a categorical field (a feature carrying an id would have no physical
    unit). Geometry the actor is *meant* to read, such as curvature, grade and
    ``lap_fraction``, is not identity and passes.
    """
    identities = _known_identities(paths)
    for feature in manifest.fields:
        haystacks = (
            feature.name.lower().replace("-", "_"),
            (feature.provenance_note or "").lower().replace("-", "_"),
        )
        for text in haystacks:
            for token in _FORBIDDEN_FEATURE_TOKENS:
                if token in text:
                    raise TrackIdentityLeak(
                        f"feature {feature.name!r} (index {feature.index}) mentions {token!r}; "
                        "the actor may not see circuit identity"
                    )
            for identity in identities:
                # Whole-word match on ids/names; a hash prefix anywhere is enough.
                if len(identity) >= 12 and identity in text:
                    raise TrackIdentityLeak(
                        f"feature {feature.name!r} (index {feature.index}) carries "
                        f"track identity {identity!r}"
                    )
                if any(part == identity for part in text.split("_")):
                    raise TrackIdentityLeak(
                        f"feature {feature.name!r} (index {feature.index}) names circuit {identity!r}"
                    )
        if feature.unit.lower() in {"id", "index", "hash", "categorical", "label"}:
            raise TrackIdentityLeak(f"feature {feature.name!r} has a categorical unit {feature.unit!r}")
