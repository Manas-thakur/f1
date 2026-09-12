"""Session manifests, snapshots and the REST snapshot payload."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from .base import ContentHash, Contract, HexDigest, VersionedContract
from .enums import CapabilityState, SessionMode, TrackReadiness
from .estimate import StateEstimate
from .lifecycle import ControlLease
from .planning import Recommendation
from .rules import RuleContext
from .telemetry import SourceCapability


class SessionManifest(VersionedContract):
    """Immutable identity of a session.

    Every hash here must be reproducible from local artefacts; an export that
    cannot rebuild these is not a reproducible experiment.
    """

    id: str = Field(min_length=1)
    mode: SessionMode
    track_hash: ContentHash
    car_hashes: dict[str, ContentHash] = Field(min_length=1)
    ruleset_hash: ContentHash
    model_hash: ContentHash | None = None
    objective_hash: ContentHash
    seed: int = Field(ge=0)
    created_at: datetime
    source_capabilities: tuple[SourceCapability, ...] = ()
    scenario_id: str | None = None
    synthetic: bool = True
    label: str | None = None
    track_id: str | None = None
    event_id: str | None = None
    track_package_hash: HexDigest | None = None
    event_package_hash: HexDigest | None = None
    track_readiness: TrackReadiness | None = None
    geometry_provenance: str | None = None
    conditions_id: str | None = None
    conditions_hash: ContentHash | None = None

    @model_validator(mode="after")
    def _capabilities_match_mode(self) -> SessionManifest:
        for capability in self.source_capabilities:
            if capability.mode is not self.mode:
                raise ValueError(
                    f"source {capability.source_id} declares mode {capability.mode}, session is {self.mode}"
                )
        return self

    @property
    def allows_simulator_driver_input(self) -> bool:
        """Only a simulation session may accept a driver-action command."""
        return self.mode is SessionMode.SIMULATION


class SessionSummary(Contract):
    """Row shown in the session list."""

    id: str = Field(min_length=1)
    mode: SessionMode
    status: str = Field(min_length=1, max_length=64)
    revision: int = Field(ge=0)
    created_at: datetime
    label: str | None = None
    synthetic: bool = True
    scenario_id: str | None = None


class SnapshotReference(Contract):
    """Handle to a complete simulator state capture."""

    snapshot_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    snapshot_hash: ContentHash
    session_time_s: float = Field(ge=0.0)
    label: str | None = None
    created_at: datetime


class RuntimeCapabilities(Contract):
    """Honest declaration of what this runtime can currently do."""

    own_energy: CapabilityState = CapabilityState.AVAILABLE
    rival_energy: CapabilityState = CapabilityState.UNAVAILABLE
    lateral_geometry: CapabilityState = CapabilityState.UNAVAILABLE
    rules_coverage: CapabilityState = CapabilityState.DEGRADED
    solver: CapabilityState = CapabilityState.AVAILABLE
    learned_model: CapabilityState = CapabilityState.UNAVAILABLE
    persistence: CapabilityState = CapabilityState.AVAILABLE
    driver_link: CapabilityState = CapabilityState.UNAVAILABLE
    track_geometry: CapabilityState = Field(
        default=CapabilityState.DEGRADED,
        description=(
            "available for a real-circuit package at or above geometry_validated, which is the rung "
            "at which the centreline has been independently checked for closure, length, curvature "
            "and grade; degraded for a synthetic sketch, whose widths and curvature are invented; "
            "unavailable when no geometry loads or the package no longer hashes to the session's. "
            "This is deliberately not gated on simulation_eligible: that rung additionally requires "
            "a surveyed corridor, which position telemetry cannot supply, so gating here would "
            "report validated geometry as unavailable. The corridor is reported separately by "
            "lateral_geometry, which is never available on an unsurveyed corridor."
        ),
    )
    notes: tuple[str, ...] = ()


class SessionSnapshot(VersionedContract):
    """Authoritative REST snapshot; the resync target for a stream gap."""

    session_id: str = Field(min_length=1)
    revision: int = Field(ge=0)
    last_sequence: int = Field(ge=0)
    server_time: datetime
    session_time_s: float = Field(ge=0.0)
    status: str = Field(min_length=1, max_length=64)
    manifest: SessionManifest
    estimate: StateEstimate | None = None
    rule_context: RuleContext | None = None
    recommendation: Recommendation | None = None
    lease: ControlLease | None = None
    capabilities: RuntimeCapabilities = RuntimeCapabilities()

    @model_validator(mode="after")
    def _no_truth_leak(self) -> SessionSnapshot:
        if self.estimate is not None and self.estimate.session_id != self.session_id:
            raise ValueError("snapshot estimate belongs to a different session")
        if self.recommendation is not None and self.recommendation.session_id != self.session_id:
            raise ValueError("snapshot recommendation belongs to a different session")
        return self


__all__ = [
    "RuntimeCapabilities",
    "SessionManifest",
    "SessionSnapshot",
    "SessionSummary",
    "SnapshotReference",
]
