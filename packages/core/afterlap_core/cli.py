"""Coordinator CLI: ``python -m afterlap_core.cli <command>``.

Commands defined by the stack document. Each reports what it actually did; a
job that could not run reports failed or unavailable rather than exiting zero.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Annotated, NoReturn

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


def _emit(payload: dict[str, object], output: Path | None = None) -> None:
    text = json.dumps(payload, indent=2, allow_nan=False)
    if output is not None:
        from .paths import atomic_write_text

        atomic_write_text(output, text + "\n")
    typer.echo(text)


@app.command()
def simulate(
    scenario: Annotated[str, typer.Option(help="Scenario configuration id.")] = "two-straight-counterattack",
    seed: Annotated[int, typer.Option(min=0, max=2**32 - 1)] = 42,
    duration_s: Annotated[float, typer.Option(min=0.001, max=3600)] = 30.0,
    dt_s: Annotated[float, typer.Option(min=0.001, max=0.1)] = 0.01,
    output: Annotated[Path | None, typer.Option()] = None,
) -> None:
    from .config import list_configs
    from .evaluation import BenchmarkManifest, LegalFixedSchedule, run_benchmark

    if scenario not in list_configs("scenarios"):
        raise typer.BadParameter("scenario must name a shipped configuration")
    if not math.isfinite(duration_s) or not math.isfinite(dt_s):
        raise typer.BadParameter("duration and integration step must be finite")
    manifest = BenchmarkManifest(
        id="cli-simulation",
        split="tuning",
        description="Synthetic closed-loop legal baseline simulation; no learned policy.",
        scenario_ids=(scenario,),
        seeds=(seed,),
        horizon_s=duration_s,
        dt_s=dt_s,
        decision_interval_s=1.0,
        compute_budget_ms=200.0,
        rule_pack_id="synthetic-pack-v1",
    )
    run = run_benchmark(manifest, [LegalFixedSchedule()])
    _emit(run.as_dict(), output)
    if run.failed_runs or any(item.status != "completed" for item in run.outcomes):
        raise typer.Exit(code=1)


@app.command()
def train(
    environment: Annotated[str, typer.Option()] = "env-v1",
    algorithm: Annotated[str, typer.Option()] = "sac-v1",
    total_steps: Annotated[int, typer.Option(min=1)] = 64,
    seed: Annotated[int, typer.Option(min=0, max=2**32 - 1)] = 11,
    resume: Annotated[Path | None, typer.Option(exists=True)] = None,
) -> None:
    from .learning.config import load_env_config, load_sac_config

    try:
        from .learning.train_sac import TrainingStatus, train as run_training
    except ImportError:
        _unavailable("learning", "install the learning dependency group to train")
    outcome = run_training(
        config=load_env_config(environment),
        algorithm=load_sac_config(algorithm),
        total_timesteps=total_steps,
        seed=seed,
        resume_from=resume,
        is_smoke_run=True,
    )
    _emit(outcome.as_dict())
    if outcome.status is not TrainingStatus.COMPLETED:
        raise typer.Exit(code=1)


@app.command()
def evaluate(
    candidate: Annotated[str, typer.Option()] = "baseline",
    benchmark: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    output: Annotated[Path | None, typer.Option()] = None,
) -> None:
    from .config import load_yaml
    from .evaluation import BenchmarkManifest, LegalFixedSchedule, load_benchmark_manifest, run_benchmark

    if candidate != "baseline":
        _unavailable("model_evaluation", "no registered candidate controller is wired to this command")
    manifest = (
        load_benchmark_manifest("commissioning-smoke")
        if benchmark is None
        else BenchmarkManifest.model_validate(load_yaml(benchmark))
    )
    run = run_benchmark(manifest, [LegalFixedSchedule()])
    _emit(run.as_dict(), output)
    if run.failed_runs or any(item.status != "completed" for item in run.outcomes):
        raise typer.Exit(code=1)


@app.command()
def ablate(
    candidate: Annotated[str, typer.Option()],
    disable: Annotated[str, typer.Option()] = "none",
    benchmark: Annotated[Path | None, typer.Option(exists=True)] = None,
) -> None:
    del candidate, disable, benchmark
    _unavailable("learned_ablation", "no promoted learned controller is wired to the comparison harness")


def _unavailable(capability: str, reason: str) -> NoReturn:
    _emit({"status": "unavailable", "capability": capability, "reason": reason})
    raise typer.Exit(code=1)


@app.command()
def promote(
    bundle: Annotated[str, typer.Option()],
    approval: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
) -> None:
    del bundle, approval
    _unavailable("model_promotion", "signed approval verification and registry promotion are not implemented")


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
