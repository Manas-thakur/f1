"""Operator-facing evaluation jobs.

``afterlap_core.cli evaluate`` called ``run_benchmark`` with keyword arguments
that do not exist, and ``afterlap_core.cli ablate`` imported a ``run_ablation``
that was never written. The harness was real; the way in was not.

This module assembles the controller set, runs the benchmark, reduces it to one
paired unit per episode, bootstraps the comparison and writes the report. Three
things it deliberately does not do:

* it does not silently omit a comparison-matrix row it cannot run. Every
  unmerged or unavailable row is passed to the harness as an explicit
  unavailable controller so the report renders it as unmeasured;
* it does not choose the reference controller for the caller when the requested
  one produced nothing. A bootstrap against an absent reference is refused with
  the reason;
* it does not assess a promotion gate. That is a separate frozen decision and
  it lives in :mod:`afterlap_core.learning.promotion`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..paths import Paths
from .controllers import (
    Controller,
    LegalFixedSchedule,
    LegalGreedyAttacker,
    unmeasured_matrix_controllers,
)
from .harness import (
    ABLATION_TARGETS,
    BenchmarkRun,
    load_benchmark_manifest,
    paired_sample_from_run,
    run_ablation,
    run_benchmark,
)
from .report import ReportBundle, build_report, write_report
from .statistics import BootstrapResult, CorrelatedSampleError, hierarchical_paired_bootstrap

__all__ = [
    "BASELINE_CANDIDATE",
    "DEFAULT_BENCHMARK_ID",
    "DEFAULT_REFERENCE",
    "baseline_controllers",
    "run_ablation_job",
    "run_evaluation",
]

DEFAULT_BENCHMARK_ID = "commissioning-smoke"
DEFAULT_REFERENCE = "legal_fixed_schedule"
BASELINE_CANDIDATE = "baseline"
_BOOTSTRAP_ITERATIONS = 2000
_BOOTSTRAP_SEED = 20260908


def baseline_controllers() -> tuple[Controller, ...]:
    """The two merged legal baselines. Neither uses a learned contribution."""
    return (
        LegalFixedSchedule(name="legal_fixed_schedule"),
        LegalGreedyAttacker(name="legal_greedy_attacker"),
    )


def _bootstraps(
    run: BenchmarkRun,
    reference: str,
    *,
    iterations: int,
    seed: int,
    paths: Paths | None = None,
) -> tuple[list[BootstrapResult], list[str]]:
    notes: list[str] = []
    sample = paired_sample_from_run(run, paths=paths)
    present = {name for unit in sample.units for name in unit.values}
    if reference not in present:
        notes.append(
            f"no paired comparison was computed: the reference controller {reference!r} produced "
            "no measured episode, and a comparison against an absent reference would be a "
            "fabricated difference"
        )
        return [], notes
    results: list[BootstrapResult] = []
    for name in sorted(present - {reference}):
        try:
            results.append(
                hierarchical_paired_bootstrap(sample, name, reference, iterations=iterations, seed=seed)
            )
        except (CorrelatedSampleError, ValueError) as exc:
            notes.append(f"{name} vs {reference}: no interval was computed ({exc})")
    return results, notes


def run_evaluation(
    *,
    candidate: str = BASELINE_CANDIDATE,
    benchmark_id: str | Path | None = None,
    controllers: Sequence[Controller] | None = None,
    reference: str = DEFAULT_REFERENCE,
    report_id: str | None = None,
    include_unavailable_rows: bool = True,
    bootstrap_iterations: int = _BOOTSTRAP_ITERATIONS,
    bootstrap_seed: int = _BOOTSTRAP_SEED,
    output: Path | None = None,
    paths: Paths | None = None,
) -> dict[str, Any]:
    """Run one benchmark and write a machine-readable report.

    ``candidate`` names what is being evaluated. ``"baseline"`` evaluates the
    two merged legal baselines against each other, which is the only comparison
    this package can measure without a model-backed controller supplied by the
    caller.
    """
    identifier = Path(str(benchmark_id)).stem if benchmark_id is not None else DEFAULT_BENCHMARK_ID
    manifest = load_benchmark_manifest(identifier, paths)
    supplied = tuple(controllers) if controllers is not None else baseline_controllers()
    if candidate != BASELINE_CANDIDATE and controllers is None:
        return {
            "job": "evaluate",
            "candidate": candidate,
            "benchmark_id": manifest.id,
            "status": "unavailable",
            "detail": (
                f"candidate {candidate!r} is not a controller this package can build on its own. "
                "Pass a model-backed controller through `controllers=`; a bundle id alone is not "
                "a controller and evaluating the baseline under its name would misreport the row."
            ),
        }

    active: list[Controller] = list(supplied)
    supplied_names = {c.name for c in supplied}
    if include_unavailable_rows:
        active.extend(unmeasured_matrix_controllers(supplied_names))

    run = run_benchmark(manifest, active, paths=paths)
    results, notes = _bootstraps(
        run, reference, iterations=bootstrap_iterations, seed=bootstrap_seed, paths=paths
    )
    bundle: ReportBundle = build_report(
        run,
        report_id=report_id or f"{manifest.id}-{candidate}",
        reference_controller=reference,
        bootstraps=results,
        notes=notes,
    )
    written = write_report(bundle, paths=paths)
    if output is not None:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(
            json.dumps(bundle.as_dict(), indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
    return {
        "job": "evaluate",
        "candidate": candidate,
        "benchmark_id": manifest.id,
        "manifest_hash": run.manifest_hash,
        "split": manifest.split,
        "status": "completed",
        "report_id": bundle.contract.id,
        "report_hash": bundle.report_hash,
        "report_path": str(written).replace("\\", "/"),
        "measured_controllers": sorted(name for name in run.controller_names if run.measured_units(name) > 0),
        "unavailable_controllers": list(run.unavailable_controllers),
        "failed_runs": len(run.failed_runs),
        "comparisons": [_comparison_record(result) for result in results],
        "notes": notes,
    }


def _comparison_record(result: BootstrapResult) -> dict[str, Any]:
    """The comparison plus the facts that decide whether it can be believed.

    ``degenerate_seed_variance`` travels with every interval on purpose. A
    package with no exogenous disturbance producer yields identical paired
    differences across seeds, and the resulting interval looks far tighter than
    the evidence earns.
    """
    contract = result.to_contract().model_dump(mode="json")
    contract["iterations"] = result.iterations
    contract["unit_count"] = result.unit_count
    contract["interval_excludes_zero"] = result.interval_excludes_zero
    contract["degenerate_seed_variance"] = result.degenerate_seed_variance
    contract["interval_widened_to_contain_estimate"] = result.interval_widened_to_contain_estimate
    return contract


def run_ablation_job(
    *,
    candidate: str,
    disable: str = "none",
    benchmark_id: str | Path | None = None,
    controllers: Sequence[Controller] | None = None,
    paths: Paths | None = None,
) -> dict[str, Any]:
    """Run one ablation of the learned system against the same scenarios."""
    if disable not in ABLATION_TARGETS:
        raise ValueError(f"unknown ablation target {disable!r}; expected one of {sorted(ABLATION_TARGETS)}")
    identifier = Path(str(benchmark_id)).stem if benchmark_id is not None else DEFAULT_BENCHMARK_ID
    manifest = load_benchmark_manifest(identifier, paths)
    if controllers is None:
        return {
            "job": "ablate",
            "candidate": candidate,
            "benchmark_id": manifest.id,
            "disable": disable,
            "target": ABLATION_TARGETS[disable],
            "status": "unavailable",
            "detail": (
                "no model-backed controller was supplied, so there is no learned contribution to "
                "remove. An ablation of an absent component would report no difference and read "
                "as evidence that the component does not matter."
            ),
        }
    run = run_ablation(manifest, tuple(controllers), disable=disable, paths=paths)
    return {
        "job": "ablate",
        "candidate": candidate,
        "benchmark_id": manifest.id,
        "manifest_hash": run.manifest_hash,
        "disable": disable,
        "target": ABLATION_TARGETS[disable],
        "status": "completed",
        "controllers": list(run.controller_names),
        "unavailable_controllers": list(run.unavailable_controllers),
        "measured": {name: run.measured_units(name) for name in run.controller_names},
        "failed_runs": len(run.failed_runs),
    }
