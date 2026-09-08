"""AFTERLAP estimation module: own-car state and opponent beliefs.

Estimation owns beliefs. It consumes the canonical ``TelemetryEvent`` stream that
:mod:`afterlap_core.data` produces, and it publishes exactly one thing to the
controller and to operational UIs: the frozen
:class:`~afterlap_contracts.StateEstimate`.

Public entry points
-------------------

``update(events, prior, context) -> StateEstimate``
    Fuse observations up to ``context.cutoff_s`` and publish the posterior.
    Anything later than the cutoff is rejected before any filter sees it.

``predict(estimate, target_time_s) -> StateEstimate``
    Extrapolate without new observations. ``cutoff_s`` does not move.

``sample_scenarios(belief, count, seed) -> ScenarioEnsemble``
    Weighted, temporally correlated opponent futures for planner rollouts.

What this module refuses to do
------------------------------

* It never reads simulator state, an RL info dictionary or a debug service.
  Replacing every hidden rival state while holding the delivered observations
  fixed produces byte-identical beliefs; ``tests/estimation/test_rivals.py``
  asserts it.
* It never invents battery energy. Without an initialised, trustworthy energy
  interval the session loses precise energy advice and says so through
  ``EstimateQuality.own_energy_capability``.
* It never labels rival energy ``measured``, and it never claims lateral
  geometry a public feed cannot resolve.

Offline scoring lives in :mod:`afterlap_core.estimation.calibration`, which reads
privileged labels and is imported by nothing on the inference path.
"""

from .assembly import (
    DEFAULT_SLOTS,
    EstimatorState,
    RivalTrack,
    SlotChange,
    SlotTracker,
    create_state,
    predict,
    update,
    update_state,
)
from .calibration import (
    AdjacentRowSplitError,
    CalibrationRecord,
    CalibrationReport,
    CoverageResult,
    ReliabilityBin,
    evaluate,
    split_by_row,
    split_by_scenario,
)
from .config import (
    MODE_INDEX,
    MODE_ORDER,
    OWN_CAR_CONFIG_ID,
    RIVAL_CONFIG_ID,
    OwnCarConfig,
    RivalConfig,
    load_own_car_config,
    load_rival_config,
)
from .context import (
    OWN_CAR_CHANNELS,
    RIVAL_CHANNELS,
    EstimationContext,
    FamilyDiagnostic,
    Observation,
    RejectedObservation,
    observations_from_events,
)
from .own_car import (
    STATE_ACCELERATION,
    STATE_DIM,
    STATE_ENERGY,
    STATE_NAMES,
    STATE_PROGRESS,
    STATE_SPEED,
    EnergyLedger,
    MotionModel,
    OwnCarFilter,
    OwnCarFilterState,
    build_own_car_estimate,
    motion_process_noise,
)
from .rivals import (
    OwnStateSummary,
    ParticleSet,
    RivalContext,
    RivalObservation,
    RivalParticleFilter,
    effective_sample_size,
    normalise_log_weights,
    systematic_resample,
    weighted_quantile,
)
from .scenarios import (
    ScenarioEnsemble,
    ScenarioTrajectory,
    reachable_energy_step_j,
    sample_scenarios,
)

__all__ = [
    "DEFAULT_SLOTS",
    "MODE_INDEX",
    "MODE_ORDER",
    "OWN_CAR_CHANNELS",
    "OWN_CAR_CONFIG_ID",
    "RIVAL_CHANNELS",
    "RIVAL_CONFIG_ID",
    "STATE_ACCELERATION",
    "STATE_DIM",
    "STATE_ENERGY",
    "STATE_NAMES",
    "STATE_PROGRESS",
    "STATE_SPEED",
    "AdjacentRowSplitError",
    "CalibrationRecord",
    "CalibrationReport",
    "CoverageResult",
    "EnergyLedger",
    "EstimationContext",
    "EstimatorState",
    "FamilyDiagnostic",
    "MotionModel",
    "Observation",
    "OwnCarConfig",
    "OwnCarFilter",
    "OwnCarFilterState",
    "OwnStateSummary",
    "ParticleSet",
    "RejectedObservation",
    "ReliabilityBin",
    "RivalConfig",
    "RivalContext",
    "RivalObservation",
    "RivalParticleFilter",
    "RivalTrack",
    "ScenarioEnsemble",
    "ScenarioTrajectory",
    "SlotChange",
    "SlotTracker",
    "build_own_car_estimate",
    "create_state",
    "effective_sample_size",
    "evaluate",
    "load_own_car_config",
    "load_rival_config",
    "motion_process_noise",
    "normalise_log_weights",
    "observations_from_events",
    "predict",
    "reachable_energy_step_j",
    "sample_scenarios",
    "split_by_row",
    "split_by_scenario",
    "systematic_resample",
    "update",
    "update_state",
    "weighted_quantile",
]
