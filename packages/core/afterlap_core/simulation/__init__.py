"""AFTERLAP simulation module: truth, physics, opponents and branching.

The simulator owns physical truth. Nothing in this package returns hidden truth
to a controller: :func:`~.observation.observe` is the only input path, and
``WorldState`` has no wire schema.

Every shipped configuration is synthetic and labelled as such. The module is a
reduced physical model with documented assumptions, not a validated digital twin
of any real car or circuit.
"""

from __future__ import annotations

from .battery import EnergyLedger, LedgerPlan, SaturationEvent
from .branching import (
    BranchResult,
    Treatment,
    branch,
    capture_complete_state,
    run_branch,
    run_paired,
    snapshot_hash,
)
from .config import (
    CarConfig,
    DriverConfig,
    InitialCarState,
    ObservationConfig,
    PolicySpec,
    ScenarioBundle,
    ScenarioConfig,
    TrackCheckpoint,
    TrackConfig,
    TrackSegment,
    load_bundle,
    load_car,
    load_scenario,
    load_track,
    parameter_provenance,
)
from .engine import DEPLOY_FRACTION, HARVEST_FRACTION, TIMING_LINE_ID, Simulator, StepReport
from .observation import Observation, debug_truth, observe
from .policies import (
    AttackPolicy,
    ConservePolicy,
    DefendPolicy,
    DriverAction,
    NormalPolicy,
    OpponentPolicy,
    build_policy,
)
from .state import CarState, CheckpointRecord, PassRecord, RaceState, WorldState
from .track import CarFootprint, TrackGeometry, geometry_for, overlap

__all__ = [
    "DEPLOY_FRACTION",
    "HARVEST_FRACTION",
    "TIMING_LINE_ID",
    "AttackPolicy",
    "BranchResult",
    "CarConfig",
    "CarFootprint",
    "CarState",
    "CheckpointRecord",
    "ConservePolicy",
    "DefendPolicy",
    "DriverAction",
    "DriverConfig",
    "EnergyLedger",
    "InitialCarState",
    "LedgerPlan",
    "NormalPolicy",
    "Observation",
    "ObservationConfig",
    "OpponentPolicy",
    "PassRecord",
    "PolicySpec",
    "RaceState",
    "SaturationEvent",
    "ScenarioBundle",
    "ScenarioConfig",
    "Simulator",
    "StepReport",
    "TrackCheckpoint",
    "TrackConfig",
    "TrackGeometry",
    "TrackSegment",
    "Treatment",
    "WorldState",
    "branch",
    "build_policy",
    "capture_complete_state",
    "debug_truth",
    "geometry_for",
    "load_bundle",
    "load_car",
    "load_scenario",
    "load_track",
    "observe",
    "overlap",
    "parameter_provenance",
    "run_branch",
    "run_paired",
    "snapshot_hash",
]
