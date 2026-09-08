"""Independent validation, benchmarking and release evidence.

This package is the *check*, not part of the thing being checked. Two rules keep
that true and both are enforced by tests:

* :mod:`~afterlap_core.evaluation.independent_ledger` never imports the
  simulator's physics or battery modules. Its equations are retyped from
  ``03_simulation/NUMERICS_AND_VALIDATION.md`` so that a shared defect cannot
  make the simulator and its auditor agree with each other.
* No module here imports ``afterlap_core.planning`` or
  ``afterlap_core.estimation``. A planner reaches the harness through the
  :class:`~afterlap_core.evaluation.controllers.Controller` protocol, so the
  evaluation package has no opinion about how a candidate is built.

Nothing in this package asserts certification, and
:mod:`~afterlap_core.evaluation.gates` cannot express such a claim.
"""

from __future__ import annotations

from .controllers import (
    COMPARISON_MATRIX,
    ControlDecision,
    Controller,
    ControlRequest,
    HashCheckedController,
    LegalFixedSchedule,
    LegalGreedyAttacker,
    MatrixRow,
    ScheduleEntry,
    UnavailableController,
    build_request,
    unavailable_matrix_controllers,
)
from .gates import (
    CertificationClaimError,
    FidelityStatus,
    Gate,
    GateEvidence,
    GateReport,
    GateStatus,
    NumericalConvergence,
    PhysicsFidelity,
    RealCarValidation,
    build_gate_report,
)
from .harness import (
    BenchmarkManifest,
    BenchmarkRun,
    CheckpointOutcome,
    RunOutcome,
    environment_record,
    list_benchmark_manifests,
    load_benchmark_manifest,
    load_objective,
    objective_utility,
    run_benchmark,
)
from .independent_ledger import (
    Crossing,
    Discrepancy,
    LedgerAudit,
    LedgerTolerances,
    ProgressSample,
    RecordedTrajectory,
    TrajectoryFrame,
    TrajectoryRecorder,
    compare_crossings,
    find_crossings,
    reconstruct,
    record_trajectory,
    recorded_crossings,
)
from .report import ReportBundle, build_report, write_report
from .robustness import (
    RobustnessDimension,
    RobustnessOutcome,
    assert_no_confident_directive_under_unknown,
    run_robustness_sweep,
)
from .statistics import (
    BootstrapResult,
    CalibrationAssessment,
    CorrelatedSampleError,
    DistributionSummary,
    EvaluationUnit,
    MetricDirection,
    PairedSample,
    TelemetryFrameSeries,
    assess_calibration,
    brier_score,
    hierarchical_paired_bootstrap,
    log_loss,
    reliability_bins,
    summarise,
)

__all__ = [
    "COMPARISON_MATRIX",
    "BenchmarkManifest",
    "BenchmarkRun",
    "BootstrapResult",
    "CalibrationAssessment",
    "CertificationClaimError",
    "CheckpointOutcome",
    "ControlDecision",
    "ControlRequest",
    "Controller",
    "CorrelatedSampleError",
    "Crossing",
    "Discrepancy",
    "DistributionSummary",
    "EvaluationUnit",
    "FidelityStatus",
    "Gate",
    "GateEvidence",
    "GateReport",
    "GateStatus",
    "HashCheckedController",
    "LedgerAudit",
    "LedgerTolerances",
    "LegalFixedSchedule",
    "LegalGreedyAttacker",
    "MatrixRow",
    "MetricDirection",
    "NumericalConvergence",
    "PairedSample",
    "PhysicsFidelity",
    "ProgressSample",
    "RealCarValidation",
    "RecordedTrajectory",
    "ReportBundle",
    "RobustnessDimension",
    "RobustnessOutcome",
    "RunOutcome",
    "ScheduleEntry",
    "TelemetryFrameSeries",
    "TrajectoryFrame",
    "TrajectoryRecorder",
    "UnavailableController",
    "assert_no_confident_directive_under_unknown",
    "assess_calibration",
    "brier_score",
    "build_gate_report",
    "build_report",
    "build_request",
    "compare_crossings",
    "environment_record",
    "find_crossings",
    "hierarchical_paired_bootstrap",
    "list_benchmark_manifests",
    "load_benchmark_manifest",
    "load_objective",
    "log_loss",
    "objective_utility",
    "reconstruct",
    "record_trajectory",
    "recorded_crossings",
    "reliability_bins",
    "run_benchmark",
    "run_robustness_sweep",
    "summarise",
    "unavailable_matrix_controllers",
    "write_report",
]
