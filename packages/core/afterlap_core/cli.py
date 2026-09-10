"""Coordinator CLI: ``python -m afterlap_core.cli <command>``.

Commands defined by the stack document. Each reports what it actually did; a
job that could not run reports failed or unavailable rather than exiting zero.
"""

from __future__ import annotations

import json
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
    seed: Annotated[int, typer.Option(help="Scenario seed.")] = 42,
    duration_s: Annotated[float, typer.Option(help="Simulated duration in seconds.")] = 30.0,
    dt_s: Annotated[float, typer.Option(help="Integration step in seconds.")] = 0.01,
    output: Annotated[Path | None, typer.Option(help="Write the trajectory summary here.")] = None,
) -> None:
    """Run a headless closed-loop simulation and report the energy ledger."""
    from .runner import run_headless

    result = run_headless(scenario_id=scenario, seed=seed, duration_s=duration_s, dt_s=dt_s)
    payload = result.summary()
    typer.echo(json.dumps(payload, indent=2))
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        typer.echo(f"wrote {output}")


@app.command()
def train(
    manifest: Annotated[Path | None, typer.Option(help="Training manifest YAML.")] = None,
    resume: Annotated[Path | None, typer.Option(help="Checkpoint to resume from.")] = None,
    total_steps: Annotated[int | None, typer.Option(help="Override the manifest step target.")] = None,
) -> None:
    """Train the SAC energy-strategy candidate."""
    from .learning.train_sac import run_training

    if manifest is None and resume is None:
        typer.echo("provide --manifest or --resume", err=True)
        raise typer.Exit(code=2)
    outcome = run_training(manifest=manifest, resume=resume, total_steps_override=total_steps)
    typer.echo(json.dumps(outcome, indent=2, default=str))


@app.command()
def evaluate(
    candidate: Annotated[str, typer.Option(help="Model bundle id, or 'baseline'.")] = "baseline",
    benchmark: Annotated[Path | None, typer.Option(help="Benchmark manifest YAML.")] = None,
    output: Annotated[Path | None, typer.Option(help="Write the report here.")] = None,
) -> None:
    """Run a held-out benchmark and write a machine-readable report."""
    from .evaluation.harness import run_benchmark

    report = run_benchmark(candidate=candidate, benchmark_path=benchmark, output=output)
    typer.echo(json.dumps(report, indent=2, default=str))


@app.command()
def ablate(
    candidate: Annotated[str, typer.Option(help="Model bundle id.")],
    disable: Annotated[str, typer.Option(help="policy | terminal | none")] = "none",
    benchmark: Annotated[Path | None, typer.Option(help="Benchmark manifest YAML.")] = None,
) -> None:
    """Run one ablation of the learned system against the same scenarios."""
    from .evaluation.harness import run_ablation

    report = run_ablation(candidate=candidate, disable=disable, benchmark_path=benchmark)
    typer.echo(json.dumps(report, indent=2, default=str))


@app.command()
def promote(
    bundle: Annotated[str, typer.Option(help="Model bundle id.")],
    approval: Annotated[Path, typer.Option(help="Signed approval document.")],
) -> None:
    """Record a promotion decision. Refuses without frozen thresholds and evidence."""
    from .learning.promotion import promote_bundle

    decision = promote_bundle(bundle_id=bundle, approval_path=approval)
    typer.echo(json.dumps(decision, indent=2, default=str))
    if decision.get("approved") is not True:
        raise typer.Exit(code=1)


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
