"""Coordinator CLI: ``python -m afterlap_core.cli <command>``.

Commands defined by the stack document. Each reports what it actually did; a
job that could not run reports failed or unavailable rather than exiting zero.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Annotated

import typer

from afterlap_contracts import CONTRACT_REVISION, SCHEMA_VERSION, CapabilityState

from .diagnostics import CapabilityKind, run_doctor
from .paths import Paths

app = typer.Typer(
    name="afterlap",
    help="AFTERLAP coordinator commands (synthetic, simulator-only).",
    no_args_is_help=True,
    add_completion=False,
)


def _emit(payload: dict[str, object], output: Path | None) -> None:
    """Print the record, and write it beside the run when a path was given."""
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    typer.echo(text)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        typer.echo(f"wrote {output}")


@app.command()
def doctor(
    json_output: Annotated[bool, typer.Option("--json", help="Emit machine-readable results.")] = False,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Exit non-zero when any capability is absent or degraded."),
    ] = False,
) -> None:
    """Check manifests, artefact storage and numerical solver availability.

    Prints no secrets. Exits 1 on a genuine failure: a capability that is
    installed and answers wrongly, or a probe that errored. An optional
    capability nobody installed is printed and does not fail the gate, so a
    default install passes. ``--strict`` additionally exits 2 when anything is
    absent or degraded.
    """
    report = run_doctor(Paths.default())
    absent = report.absent
    failed = report.failed
    degraded = [c for c in report.degraded if c.kind is not CapabilityKind.ABSENT]

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "contract_revision": CONTRACT_REVISION,
                    "checks": [
                        {
                            "name": c.name,
                            "state": c.state.value,
                            "kind": c.kind.value,
                            "detail": c.detail,
                            "version": c.version,
                        }
                        for c in report.checks
                    ],
                },
                indent=2,
            )
        )
    else:
        typer.echo(report.render())
        if failed:
            typer.echo("")
            typer.echo(f"failed capabilities: {', '.join(c.name for c in failed)}")
        if absent:
            typer.echo("")
            typer.echo("absent optional capabilities (not a failure): " + ", ".join(c.name for c in absent))
        if degraded:
            typer.echo(f"degraded capabilities: {', '.join(c.name for c in degraded)}")

    if failed:
        raise typer.Exit(code=1)
    if strict and (absent or report.degraded):
        raise typer.Exit(code=2)


@app.command("generate-contracts")
def generate_contracts(
    check: Annotated[
        bool, typer.Option("--check", help="Fail instead of writing when artefacts are stale.")
    ] = False,
) -> None:
    """Regenerate JSON Schema and TypeScript declarations from the Pydantic models."""
    from afterlap_contracts.schema_export import check_drift, default_output_dir, write_generated

    if check:
        problems = check_drift()
        if problems:
            for problem in problems:
                typer.echo(f"drift: {problem}", err=True)
            raise typer.Exit(code=1)
        typer.echo("generated contracts are current")
        return

    for path in write_generated(default_output_dir()):
        typer.echo(f"wrote {path}")


@app.command("list-configs")
def list_configs_command(
    kind: Annotated[str, typer.Argument(help="tracks | cars | rules | scenarios | learning | benchmarks")],
) -> None:
    """List available configuration documents of one kind."""
    from .config import list_configs

    names = list_configs(kind)
    if not names:
        typer.echo(f"no {kind} configurations found")
        raise typer.Exit(code=1)
    for name in names:
        typer.echo(name)


@app.command()
def simulate(
    scenario: Annotated[str, typer.Option(help="Scenario configuration id.")] = "two-straight-counterattack",
    seed: Annotated[int, typer.Option(min=0, max=2**32 - 1, help="Scenario seed.")] = 42,
    duration_s: Annotated[
        float, typer.Option(min=0.001, max=3600.0, help="Simulated duration in seconds.")
    ] = 30.0,
    dt_s: Annotated[float, typer.Option(min=0.001, max=0.1, help="Integration step in seconds.")] = 0.01,
    output: Annotated[Path | None, typer.Option(help="Write the trajectory summary here.")] = None,
) -> None:
    """Run a headless closed-loop simulation and report the energy ledger.

    The bounds are enforced before anything runs. ``--duration-s inf`` used to
    integrate without end, and ``--duration-s nan`` used to print a complete,
    successful-looking report of a zero-length run. Neither is a measurement,
    and a job that cannot run has to say so rather than produce a record.
    """
    from .config import list_configs
    from .runner import run_headless

    if not math.isfinite(duration_s) or not math.isfinite(dt_s):
        raise typer.BadParameter("duration and integration step must be finite")
    if scenario not in list_configs("scenarios"):
        raise typer.BadParameter("scenario must name a shipped configuration")

    summary = run_headless(scenario_id=scenario, seed=seed, duration_s=duration_s, dt_s=dt_s).summary()
    _emit(summary, output)


@app.command()
def train(
    sac_config: Annotated[str, typer.Option(help="SAC configuration id, or a path to one.")] = "sac-v1",
    env_config: Annotated[str, typer.Option(help="Environment configuration id, or a path.")] = "env-v1",
    seed: Annotated[int, typer.Option(help="Training seed.")] = 11,
    total_steps: Annotated[int | None, typer.Option(help="Override the configured step target.")] = None,
    scenario: Annotated[str | None, typer.Option(help="Restrict training to one scenario id.")] = None,
    n_envs: Annotated[int | None, typer.Option(help="Vectorised environment count.")] = None,
    checkpoint_every: Annotated[int | None, typer.Option(help="Checkpoint interval in steps.")] = None,
    smoke: Annotated[bool, typer.Option(help="Run the labelled smoke job, not a trained model.")] = False,
    *,
    resume: Annotated[Path | None, typer.Option(help="Checkpoint directory to resume from.")] = None,
    evaluation_episodes: Annotated[
        int, typer.Option(help="Deterministic evaluation episodes to run after training.")
    ] = 0,
    package: Annotated[bool, typer.Option(help="Package the final checkpoint into a bundle.")] = False,
    rule_family: Annotated[str, typer.Option(help="Rule family the bundle declares.")] = "synthetic-pack-v1",
    output: Annotated[Path | None, typer.Option(help="Write the job record here.")] = None,
) -> None:
    """Train the SAC energy-strategy candidate.

    A smoke run is labelled a smoke run everywhere it appears. Packaging writes
    an ``unevaluated`` bundle; it is not a promotion and cannot become one here.
    """
    from .learning.jobs import run_training

    payload = run_training(
        sac_config_id=sac_config,
        env_config_id=env_config,
        seed=seed,
        total_steps=total_steps,
        scenario_id=scenario,
        n_envs=n_envs,
        checkpoint_every=checkpoint_every,
        smoke=smoke,
        resume_from=resume,
        evaluation_episodes=evaluation_episodes,
        package=package,
        rule_family=rule_family,
    )
    _emit(payload, output)
    if payload["result"]["status"] != "completed":
        raise typer.Exit(code=1)


@app.command("package-model")
def package_model(
    checkpoint: Annotated[Path, typer.Option(help="Checkpoint directory to package.")],
    env_config: Annotated[str, typer.Option(help="Environment configuration id, or a path.")] = "env-v1",
    rule_family: Annotated[str, typer.Option(help="Rule family the bundle declares.")] = "synthetic-pack-v1",
    bundle_directory: Annotated[Path | None, typer.Option(help="Write the bundle here.")] = None,
    bundle_id: Annotated[str | None, typer.Option(help="Override the generated bundle id.")] = None,
    output: Annotated[Path | None, typer.Option(help="Write the job record here.")] = None,
) -> None:
    """Package a verified checkpoint into a frozen, loadable bundle."""
    from .learning.jobs import run_packaging
    from .learning.packaging import PackagingError

    try:
        payload = run_packaging(
            checkpoint,
            rule_family=rule_family,
            env_config_id=env_config,
            bundle_directory=bundle_directory,
            bundle_id=bundle_id,
        )
    except PackagingError as exc:
        typer.echo(json.dumps({"job": "package", "status": "refused", "detail": str(exc)}, indent=2))
        raise typer.Exit(code=1) from exc
    _emit(payload, output)


@app.command()
def throughput(
    env_config: Annotated[str, typer.Option(help="Environment configuration id, or a path.")] = "env-v1",
    transitions: Annotated[int, typer.Option(help="Transitions to measure.")] = 1000,
    scenario: Annotated[str | None, typer.Option(help="Restrict to one scenario id.")] = None,
    seed: Annotated[int, typer.Option(help="Sampling seed.")] = 11,
    output: Annotated[Path | None, typer.Option(help="Write the measurement here.")] = None,
) -> None:
    """Measure environment throughput before choosing a training budget."""
    from .learning.jobs import run_throughput_benchmark

    _emit(
        run_throughput_benchmark(
            env_config_id=env_config, transitions=transitions, scenario_id=scenario, seed=seed
        ),
        output,
    )


@app.command("fit-value")
def fit_value(
    env_config: Annotated[str, typer.Option(help="Environment configuration id, or a path.")] = "env-v1",
    value_config: Annotated[str, typer.Option(help="Value configuration id, or a path.")] = "value-v1",
    episodes: Annotated[int, typer.Option(help="Complete episodes to collect.")] = 12,
    seed: Annotated[int, typer.Option(help="Collection and fitting seed.")] = 0,
    scenario: Annotated[str | None, typer.Option(help="Restrict collection to one scenario id.")] = None,
    policy: Annotated[str, typer.Option(help="held-neutral | uniform-random")] = "held-neutral",
    output: Annotated[Path | None, typer.Option(help="Write the fit record here.")] = None,
) -> None:
    """Fit the continuation-return ensemble on complete simulator episodes.

    The train/tuning split is by episode. A collection with fewer than two
    complete episodes reports unavailable rather than fitting on one.
    """
    from .learning.jobs import run_value_fit

    payload = run_value_fit(
        env_config_id=env_config,
        value_config_id=value_config,
        episodes=episodes,
        seed=seed,
        scenario_id=scenario,
        policy=policy,
        output=output,
    )
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
    if payload["status"] != "completed":
        raise typer.Exit(code=2)


@app.command("fit-calibration")
def fit_calibration(
    env_config: Annotated[str, typer.Option(help="Environment configuration id, or a path.")] = "env-v1",
    episodes: Annotated[int, typer.Option(help="Complete episodes to collect.")] = 16,
    seed: Annotated[int, typer.Option(help="Collection and fitting seed.")] = 0,
    scenario: Annotated[str | None, typer.Option(help="Restrict collection to one scenario id.")] = None,
    policy: Annotated[str, typer.Option(help="held-neutral | uniform-random")] = "held-neutral",
    planner_deadline_s: Annotated[
        float, typer.Option(help="Deadline for collection; the operational budget is recorded too.")
    ] = 5.0,
    min_support: Annotated[int, typer.Option(help="Minimum labelled samples per event.")] = 30,
    output: Annotated[Path | None, typer.Option(help="Write the fit record here.")] = None,
) -> None:
    """Fit the probability calibrator on forecast/realisation pairs.

    Re-simulation is enabled for collection, which changes the environment
    revision, and the deadline is raised so the ensemble can finish: collecting
    only the decisions that fit the operational 200 ms budget would keep a
    biased sample of the easy cases. Both values are recorded on the report.
    """
    from .learning.jobs import run_calibration_fit

    payload = run_calibration_fit(
        env_config_id=env_config,
        episodes=episodes,
        seed=seed,
        scenario_id=scenario,
        policy=policy,
        planner_deadline_s=planner_deadline_s,
        min_support=min_support,
        output=output,
    )
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
    if payload["status"] != "completed":
        raise typer.Exit(code=2)


@app.command()
def evaluate(
    candidate: Annotated[str, typer.Option(help="Candidate name, or 'baseline'.")] = "baseline",
    benchmark: Annotated[str, typer.Option(help="Benchmark manifest id, or a path.")] = "commissioning-smoke",
    reference: Annotated[str, typer.Option(help="Paired reference controller.")] = "legal_fixed_schedule",
    report_id: Annotated[str | None, typer.Option(help="Override the report id.")] = None,
    bootstrap_iterations: Annotated[int, typer.Option(help="Paired bootstrap iterations.")] = 2000,
    output: Annotated[Path | None, typer.Option(help="Write the report here.")] = None,
) -> None:
    """Run a benchmark and write a machine-readable report.

    Comparison-matrix rows that are not merged are passed to the harness as
    explicit unavailable controllers, so the report renders them as unmeasured
    instead of omitting them.
    """
    from .evaluation.jobs import run_evaluation

    payload = run_evaluation(
        candidate=candidate,
        benchmark_id=benchmark,
        reference=reference,
        report_id=report_id,
        bootstrap_iterations=bootstrap_iterations,
        output=output,
    )
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
    if payload["status"] != "completed":
        raise typer.Exit(code=2)


@app.command()
def ablate(
    candidate: Annotated[str, typer.Option(help="Candidate name.")],
    disable: Annotated[str, typer.Option(help="policy | terminal | none")] = "none",
    benchmark: Annotated[str, typer.Option(help="Benchmark manifest id, or a path.")] = "commissioning-smoke",
) -> None:
    """Run one ablation of the learned system against the same scenarios."""
    from .evaluation.jobs import run_ablation_job

    payload = run_ablation_job(candidate=candidate, disable=disable, benchmark_id=benchmark)
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
    if payload["status"] != "completed":
        raise typer.Exit(code=2)


@app.command()
def promote(
    bundle: Annotated[Path, typer.Option(help="Model bundle directory.")],
    report: Annotated[Path | None, typer.Option(help="Benchmark report JSON.")] = None,
    evidence: Annotated[
        list[str] | None, typer.Option("--evidence", help="One supplied evidence item. Repeatable.")
    ] = None,
    expected_rule_family: Annotated[
        str | None, typer.Option(help="Rule family the session will use.")
    ] = None,
    output: Annotated[Path | None, typer.Option(help="Write the decision here.")] = None,
) -> None:
    """Record a promotion decision. Refuses without frozen thresholds and evidence."""
    from .learning.promotion import decide_from_paths

    decision = decide_from_paths(
        bundle_directory=bundle,
        report_path=report,
        evidence_supplied=tuple(evidence or ()),
        expected_rule_family=expected_rule_family,
    )
    _emit(decision, output)
    if decision.get("promoted") is not True:
        raise typer.Exit(code=1)


@app.command("model-registry")
def model_registry(
    output: Annotated[Path | None, typer.Option(help="Write the registry JSON here.")] = None,
    markdown: Annotated[bool, typer.Option("--markdown", help="Print the summary table.")] = False,
) -> None:
    """Emit the machine-readable inventory of every model in the repository.

    Derived from the code and the frozen configuration documents, so a
    published table cannot drift from what would actually run. Parameter counts
    come from constructed networks; when the learning extra is absent they are
    reported as unavailable with the reason rather than guessed.
    """
    from .model_registry import as_markdown, build_registry, write_registry

    report = build_registry()
    if markdown:
        typer.echo(as_markdown(report))
        return
    payload = report.as_dict()
    payload["content_hash"] = report.content_hash()
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
    if output is not None:
        typer.echo(f"wrote {write_registry(report, output=output)}")


@app.command()
def version() -> None:
    """Print component versions."""
    from . import __version__

    typer.echo(
        json.dumps(
            {
                "afterlap_core": __version__,
                "schema_version": SCHEMA_VERSION,
                "contract_revision": CONTRACT_REVISION,
                "python": sys.version.split()[0],
            },
            indent=2,
        )
    )


def main() -> None:  # pragma: no cover - CLI entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["CapabilityState", "app", "main"]
