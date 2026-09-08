"""The machine-readable benchmark report. Absent evidence stays absent.

``validation/TECHNICAL_SPEC.md`` lists what a report must carry: manifest
hashes, environment versions, hardware, scenario population, sample counts,
missing and failed runs, paired estimates and intervals, per-family results,
calibration, latency percentiles, all hard violations and reproducible losing
snapshots. It also says the UI evidence screen "displays unavailable for absent
evidence".

That second requirement is the one that shapes this module. Every row of the
comparison matrix appears in the report whether or not it could be measured, and
an unmeasured row carries ``status: "unmeasured"`` and a reason instead of a
number. There is no code path that fills a missing measurement with a default,
and :func:`build_report` refuses to emit a comparison for a controller whose
runs were all unavailable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from afterlap_contracts import (
    SCHEMA_VERSION,
    BenchmarkComparison,
    BenchmarkReport,
    CalibrationReport,
    FailureCategory,
)
from afterlap_core.paths import Paths, atomic_write_json, sha256_json

from .controllers import COMPARISON_MATRIX
from .harness import BenchmarkRun, RunOutcome, percentile
from .statistics import BootstrapResult, CalibrationAssessment

__all__ = [
    "UNMEASURED",
    "ComparisonRow",
    "ReportBundle",
    "build_report",
    "family_breakdown",
    "losing_snapshots",
    "matrix_coverage",
    "write_report",
]

UNMEASURED = "unmeasured"
"""The status the UI reads as "unavailable". Never replaced by a placeholder."""


@dataclass(frozen=True, slots=True)
class ComparisonRow:
    """One matrix row's presence in the report, measured or not."""

    controller: str
    reference: str | None
    purpose: str
    owner: str
    status: str
    reason: str | None = None
    comparison: BenchmarkComparison | None = None
    distribution: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "controller": self.controller,
            "reference": self.reference,
            "purpose": self.purpose,
            "owner": self.owner,
            "status": self.status,
            "reason": self.reason,
            "comparison": None if self.comparison is None else self.comparison.model_dump(mode="json"),
            "distribution": self.distribution,
        }


def matrix_coverage(run: BenchmarkRun) -> tuple[dict[str, Any], ...]:
    """Every required matrix row with the reason it is or is not measurable."""
    measured = {outcome.controller for outcome in run.outcomes if outcome.measured}
    rows: list[dict[str, Any]] = []
    for row in COMPARISON_MATRIX:
        present = row.controller_name in measured
        rows.append(
            {
                "controller": row.controller_name,
                "uses_actor": row.uses_actor,
                "uses_learned_return": row.uses_learned_return,
                "purpose": row.purpose,
                "owner": row.owner,
                "status": "measured" if present else UNMEASURED,
                "reason": None
                if present
                else (
                    row.unmeasured_reason
                    or f"{row.controller_name} produced no completed run in this benchmark"
                ),
            }
        )
    return tuple(rows)


def family_breakdown(run: BenchmarkRun) -> dict[str, dict[str, Any]]:
    """Per-family counts, so a single dominant family cannot hide behind a mean."""
    families: dict[str, dict[str, Any]] = {}
    for outcome in run.outcomes:
        entry = families.setdefault(
            outcome.family,
            {
                "scenarios": set(),
                "seeds": set(),
                "completed": 0,
                "unavailable": 0,
                "failed": 0,
                "withdrawn_decisions": 0,
                "decisions": 0,
                "modelled_violations": 0,
            },
        )
        entry["scenarios"].add(outcome.scenario_id)
        entry["seeds"].add(outcome.seed)
        entry[outcome.status] = entry.get(outcome.status, 0) + 1
        entry["withdrawn_decisions"] += outcome.withdrawn_decisions
        entry["decisions"] += outcome.decisions
        entry["modelled_violations"] += outcome.modelled_violations
    return {
        name: {
            **{k: v for k, v in entry.items() if k not in {"scenarios", "seeds"}},
            "scenario_count": len(entry["scenarios"]),
            "seed_count": len(entry["seeds"]),
        }
        for name, entry in sorted(families.items())
    }


def losing_snapshots(
    run: BenchmarkRun, *, controller: str, reference: str, limit: int = 5
) -> tuple[dict[str, Any], ...]:
    """Reproducible identifiers for the worst units, so a loss can be replayed.

    A snapshot hash plus the manifest hash, the scenario id and the seed is
    enough to restore exactly the state a branch started from; the harness never
    discards a losing branch.
    """
    by_key: dict[tuple[str, int], dict[str, RunOutcome]] = {}
    for outcome in run.outcomes:
        if not outcome.measured or outcome.elapsed_time_s is None:
            continue
        by_key.setdefault((outcome.scenario_id, outcome.seed), {})[outcome.controller] = outcome
    losses: list[dict[str, Any]] = []
    for (scenario_id, seed), entries in sorted(by_key.items()):
        if controller not in entries or reference not in entries:
            continue
        candidate = entries[controller]
        baseline = entries[reference]
        margin = (candidate.final_progress_m or 0.0) - (baseline.final_progress_m or 0.0)
        if margin >= 0.0:
            continue
        losses.append(
            {
                "scenario_id": scenario_id,
                "seed": seed,
                "family": candidate.family,
                "controller": controller,
                "reference": reference,
                "progress_margin_m": margin,
                "snapshot_hash": candidate.snapshot_hash,
                "manifest_hash": run.manifest_hash,
                "candidate": candidate.as_dict(),
                "reference_run": baseline.as_dict(),
            }
        )
    losses.sort(key=lambda item: item["progress_margin_m"])
    return tuple(losses[:limit])


def _hard_violations(run: BenchmarkRun) -> tuple[dict[str, Any], ...]:
    """Every modelled rule or physical violation, listed individually."""
    violations: list[dict[str, Any]] = []
    for outcome in run.outcomes:
        if outcome.modelled_violations:
            violations.append(
                {
                    "kind": "inadmissible_profile_issued",
                    "scenario_id": outcome.scenario_id,
                    "seed": outcome.seed,
                    "controller": outcome.controller,
                    "count": outcome.modelled_violations,
                    "snapshot_hash": outcome.snapshot_hash,
                }
            )
        if outcome.envelope_exceedances:
            violations.append(
                {
                    "kind": "tyre_envelope_exceedance",
                    "scenario_id": outcome.scenario_id,
                    "seed": outcome.seed,
                    "controller": outcome.controller,
                    "count": outcome.envelope_exceedances,
                    "snapshot_hash": outcome.snapshot_hash,
                }
            )
    return tuple(violations)


def _failures_by_category(run: BenchmarkRun) -> dict[FailureCategory, int]:
    counts: dict[FailureCategory, int] = {}
    for outcome in run.outcomes:
        if outcome.failure_category is not None:
            counts[outcome.failure_category] = counts.get(outcome.failure_category, 0) + 1
    return counts


@dataclass(frozen=True, slots=True)
class ReportBundle:
    """The frozen contract record plus everything the contract cannot carry."""

    contract: BenchmarkReport
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def report_hash(self) -> str:
        return sha256_json(self.contract.model_dump(mode="json"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "report": self.contract.model_dump(mode="json"),
            "report_hash": self.report_hash,
            "detail": self.detail,
        }


def build_report(
    run: BenchmarkRun,
    *,
    report_id: str,
    reference_controller: str,
    bootstraps: Sequence[BootstrapResult] = (),
    calibrations: Sequence[CalibrationAssessment] = (),
    gate_report: Mapping[str, Any] | None = None,
    robustness: Sequence[Mapping[str, Any]] = (),
    ledger_audits: Sequence[Mapping[str, Any]] = (),
    notes: Sequence[str] = (),
) -> ReportBundle:
    """Assemble the report. Rows without evidence are emitted as unmeasured."""
    comparisons: list[BenchmarkComparison] = []
    rows: list[ComparisonRow] = []
    measured_controllers = {o.controller for o in run.outcomes if o.measured}
    by_controller = {result.controller: result for result in bootstraps}

    for matrix_row in COMPARISON_MATRIX:
        name = matrix_row.controller_name
        if name == reference_controller:
            rows.append(
                ComparisonRow(
                    controller=name,
                    reference=None,
                    purpose=matrix_row.purpose,
                    owner=matrix_row.owner,
                    status="reference",
                    reason="this row is the paired reference for the others",
                )
            )
            continue
        result = by_controller.get(name)
        if result is not None:
            contract = result.to_contract()
            comparisons.append(contract)
            rows.append(
                ComparisonRow(
                    controller=name,
                    reference=result.reference,
                    purpose=matrix_row.purpose,
                    owner=matrix_row.owner,
                    status="measured",
                    comparison=contract,
                    distribution=result.distribution.as_dict(),
                )
            )
            continue
        reason = matrix_row.unmeasured_reason
        if reason is None:
            reason = (
                f"{name} completed runs but no paired estimate was requested"
                if name in measured_controllers
                else f"{name} produced no completed run in this benchmark"
            )
        rows.append(
            ComparisonRow(
                controller=name,
                reference=reference_controller,
                purpose=matrix_row.purpose,
                owner=matrix_row.owner,
                status=UNMEASURED,
                reason=reason,
            )
        )

    calibration_reports: list[CalibrationReport] = [item.report for item in calibrations]
    latencies = [ms for outcome in run.outcomes for ms in outcome.latency_ms]
    scenario_ids = sorted({outcome.scenario_id for outcome in run.outcomes})
    seeds = sorted({outcome.seed for outcome in run.outcomes})

    report_notes = list(notes)
    unmeasured_rows = [row.controller for row in rows if row.status == UNMEASURED]
    if unmeasured_rows:
        report_notes.append(
            "unmeasured comparison-matrix rows: "
            + ", ".join(unmeasured_rows)
            + ". These rows carry no number; the evidence screen must render them as unavailable."
        )
    if run.unavailable_controllers:
        report_notes.append(
            "controllers that reported themselves unavailable at every tick: "
            + ", ".join(run.unavailable_controllers)
        )
    degenerate = [r.controller for r in bootstraps if r.degenerate_seed_variance]
    if degenerate:
        report_notes.append(
            "zero within-scenario seed variance for: "
            + ", ".join(degenerate)
            + ". Every seed produced the identical paired difference, so the seed level of the "
            "hierarchical bootstrap contributed nothing and the interval reflects the scenario "
            "population alone. This is a property of the fixtures, which carry no exogenous "
            "physical disturbance producer, not of the estimator."
        )
    if not calibration_reports:
        report_notes.append(
            "no probability calibration was assessed: this benchmark declares no probabilistic "
            "event forecast, so calibration is unmeasured rather than perfect"
        )

    contract = BenchmarkReport(
        schema_version=SCHEMA_VERSION,
        id=report_id,
        created_at=datetime.now(UTC),
        evaluator_version=run.manifest.evaluator_version,
        metrics_version=run.manifest.metrics_version,
        scenario_family=run.manifest.split,
        scenario_count=len(scenario_ids),
        seed_count=len(seeds),
        comparisons=tuple(comparisons),
        calibration=tuple(calibration_reports),
        latency_p50_ms=percentile(latencies, 50.0),
        latency_p95_ms=percentile(latencies, 95.0),
        latency_p99_ms=percentile(latencies, 99.0),
        withdrawn_decisions=sum(outcome.withdrawn_decisions for outcome in run.outcomes),
        modelled_violations=sum(outcome.modelled_violations for outcome in run.outcomes),
        failures_by_category=_failures_by_category(run),
        hardware=run.environment.hardware,
        rerun_command=run.rerun_command,
        notes=tuple(report_notes),
    )

    detail: dict[str, Any] = {
        "manifest": {
            "id": run.manifest.id,
            "hash": run.manifest_hash,
            "split": run.manifest.split,
            "scenario_ids": list(run.manifest.scenario_ids),
            "seeds": list(run.manifest.seeds),
            "horizon_s": run.manifest.horizon_s,
            "dt_s": run.manifest.dt_s,
            "decision_interval_s": run.manifest.decision_interval_s,
            "rule_pack_id": run.manifest.rule_pack_id,
            "frozen_at": None if run.manifest.frozen_at is None else run.manifest.frozen_at.isoformat(),
        },
        "environment": run.environment.as_dict(),
        "population": {
            "scenario_ids": scenario_ids,
            "seeds": seeds,
            "planned_units": run.manifest.unit_count,
            "completed_runs": sum(1 for o in run.outcomes if o.measured),
            "unavailable_runs": sum(1 for o in run.outcomes if o.status == "unavailable"),
            "failed_runs": sum(1 for o in run.outcomes if o.status == "failed"),
        },
        "comparison_matrix": [row.as_dict() for row in rows],
        "matrix_coverage": list(matrix_coverage(run)),
        "per_family": family_breakdown(run),
        "hard_violations": list(_hard_violations(run)),
        "failed_runs": [dict(item) for item in run.failed_runs],
        "raw_outcomes": [outcome.as_dict() for outcome in run.outcomes],
        "calibration": [item.as_dict() for item in calibrations],
        "robustness": [dict(item) for item in robustness],
        "independent_ledger_audits": [dict(item) for item in ledger_audits],
        "gates": dict(gate_report) if gate_report is not None else {"status": UNMEASURED},
        "certification": "not_claimed",
    }
    if bootstraps:
        detail["losing_snapshots"] = {
            result.controller: list(
                losing_snapshots(run, controller=result.controller, reference=result.reference)
            )
            for result in bootstraps
        }
    else:
        detail["losing_snapshots"] = {"status": UNMEASURED, "reason": "no paired estimate was computed"}
    return ReportBundle(contract=contract, detail=detail)


def write_report(bundle: ReportBundle, *, paths: Paths | None = None) -> Path:
    """Write the report under ``artifacts/reports`` and return its path."""
    resolved = (paths or Paths.default()).ensure()
    target = resolved.reports / f"{bundle.contract.id}.json"
    atomic_write_json(target, bundle.as_dict())
    return target
