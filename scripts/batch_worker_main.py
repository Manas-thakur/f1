#!/usr/bin/env python


from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def _ensure_workspace_on_path() -> None:
    root = _HERE.parent
    for candidate in (
        root,
        root / "apps" / "api",
        root / "packages" / "core",
        root / "packages" / "contracts",
        root / "packages" / "infrastructure",
        root / "packages" / "application",
    ):
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


_ensure_workspace_on_path()

from afterlap_ops.quota import ArtifactQuota, QuotaPolicy, QuotaVerdict  # noqa: E402

logger = logging.getLogger("afterlap.ops.batch")

CONTROLLER_REGISTRY: dict[str, str] = {
    "legal_fixed_schedule": "A13 reference: deterministic profile schedule, filtered through the rules",
    "legal_greedy_attacker": "A13 reference: myopic spender, filtered through the rules",
}
"""Treatment ids this worker can resolve to a merged controller."""

RUNNING_HEARTBEAT_INTERVAL_S = 5.0


@contextmanager
def repeating_heartbeat(
    write: Callable[[], None], *, interval_s: float = RUNNING_HEARTBEAT_INTERVAL_S
) -> Iterator[None]:
    """Keep a long-running job live in the container health probe."""
    if interval_s <= 0.0:
        raise ValueError("heartbeat interval must be positive")
    stopped = threading.Event()

    def repeat() -> None:
        while not stopped.wait(interval_s):
            write()

    write()
    thread = threading.Thread(target=repeat, name="afterlap-batch-heartbeat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=interval_s + 1.0)


def _rule_pack_id_for(db: Any, ruleset_hash: str) -> str:
    """Resolve a rule-pack id from its content hash.

    Prefers the `rule_manifest` table. If nothing there matches, every rule
    pack in `configs/rules/` is loaded and compared by hash — deterministic,
    and it never guesses: an unresolvable hash raises so the job fails with a
    reason rather than running against a pack nobody asked for.
    """
    from afterlap_core.config import list_configs
    from afterlap_core.rules import load_rule_pack
    from afterlap_infrastructure.persistence.models import RuleManifestRow

    row = db.get(RuleManifestRow, ruleset_hash)
    if row is not None:
        return str(row.ruleset_id)

    for candidate in list_configs("rules"):
        try:
            pack = load_rule_pack(candidate)
        except Exception:  # pragma: no cover - a malformed config is A04's problem
            logger.debug("rule pack %s could not be loaded while resolving %s", candidate, ruleset_hash)
            continue
        if pack.ruleset_hash == ruleset_hash:
            return candidate
    raise RuntimeError(
        f"ruleset hash {ruleset_hash} matches no row in rule_manifest and no pack in configs/rules; "
        "the job cannot be run against an unidentified ruleset"
    )


def _controller_for(treatment_id: str, controller_id: str) -> Any:
    from afterlap_core.evaluation.controllers import (
        LegalFixedSchedule,
        LegalGreedyAttacker,
        UnavailableController,
    )

    if controller_id == "legal_fixed_schedule":
        return LegalFixedSchedule(name=treatment_id)
    if controller_id == "legal_greedy_attacker":
        return LegalGreedyAttacker(name=treatment_id)
    return UnavailableController(
        treatment_id,
        owner="unresolved",
        detail=(
            f"controller {controller_id!r} for treatment {treatment_id!r} is unavailable. "
            f"Resolvable controllers: {sorted(CONTROLLER_REGISTRY)}."
        ),
    )


def build_runner(factory: Any) -> Any:
    """Return a runner closure for `BatchWorker.run`."""
    from afterlap_contracts import ExperimentManifest
    from afterlap_core.evaluation.harness import BenchmarkManifest, run_benchmark
    from afterlap_core.paths import Paths
    from afterlap_infrastructure.persistence.engine import transaction
    from afterlap_infrastructure.persistence.models import Manifest, Session, SnapshotRow

    def runner(context: Any) -> dict[str, Any]:
        with transaction(factory) as db:
            stored = db.get(Manifest, context.manifest_hash)
            if stored is None:
                raise RuntimeError(
                    f"experiment manifest {context.manifest_hash} is not in the manifest store"
                )
            manifest = ExperimentManifest.model_validate(stored.payload)
            snapshot = db.query(SnapshotRow).filter_by(snapshot_hash=manifest.snapshot_hash).one_or_none()
            if snapshot is None:
                raise RuntimeError(
                    f"snapshot {manifest.snapshot_hash} referenced by the experiment no longer exists"
                )
            session = db.get(Session, snapshot.session_id)
            if session is None:
                raise RuntimeError(f"session {snapshot.session_id} no longer exists")
            scenario_id = session.scenario_id
            if not scenario_id:
                raise RuntimeError(f"session {session.id} records no scenario id")
            rule_pack_id = _rule_pack_id_for(db, session.ruleset_hash)

        controllers = [
            _controller_for(treatment, controller)
            for treatment, controller in zip(manifest.treatment_ids, manifest.controller_ids, strict=True)
        ]
        benchmark = BenchmarkManifest(
            id=f"experiment-{context.job_id}",
            split="tuning",
            synthetic=True,
            description=(
                f"operator-requested branch comparison for experiment {context.job_id} "
                f"from snapshot {manifest.snapshot_hash}"
            ),
            scenario_ids=(scenario_id,),
            seeds=tuple(manifest.disturbance_seed_ids),
            horizon_s=manifest.evaluation_horizon_s,
            dt_s=0.02,
            decision_interval_s=1.0,
            compute_budget_ms=200.0,
            rule_pack_id=rule_pack_id,
            evaluator_version=manifest.evaluator_version,
        )

        context.token.raise_if_cancelled()
        context.heartbeat()

        run = run_benchmark(benchmark, controllers, paths=Paths.default())

        for controller in run.controller_names:
            context.token.raise_if_cancelled()
            context.heartbeat()
            outcomes = run.for_controller(controller)
            context.checkpoint(
                controller,
                {
                    "controller": controller,
                    "measured_units": run.measured_units(controller),
                    "outcomes": [o.as_dict() for o in outcomes],
                },
            )

        return {
            "kind": "afterlap.experiment.branch_comparison/1",
            "experiment_manifest_hash": context.manifest_hash,
            "snapshot_hash": manifest.snapshot_hash,
            "controller_ids": dict(zip(manifest.treatment_ids, manifest.controller_ids, strict=True)),
            "scenario_id": scenario_id,
            "rule_pack_id": rule_pack_id,
            "benchmark": run.as_dict(),
            "limitations": [
                "split=tuning: this is an operator-requested comparison, not a held-out benchmark.",
                (
                    "runs start from the frozen scenario and seed, not from the branched "
                    "simulator snapshot; snapshot_hash is recorded for traceability only."
                ),
                (
                    "coordinator decision D-06: no exogenous physical disturbance exists, so "
                    "seed-level variance is degenerate and no seed-resampled interval is valid."
                ),
            ],
        }

    return runner


class _Stop:
    """SIGTERM/SIGINT flag, so `docker compose down` is a clean exit."""

    def __init__(self) -> None:
        self.requested = False

    def install(self) -> None:
        for name in ("SIGTERM", "SIGINT"):
            sig = getattr(signal, name, None)
            if sig is not None:
                signal.signal(sig, self._handle)

    def _handle(self, signum: int, _frame: Any) -> None:
        logger.info("received signal %s; finishing the current job then exiting", signum)
        self.requested = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AFTERLAP batch experiment worker.")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--max-jobs", type=int, default=None)
    parser.add_argument("--once", action="store_true", help="Poll once and exit (used by tests).")
    parser.add_argument("--wait-for-database", type=float, default=60.0, metavar="SECONDS")
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Exit 0 if this worker's heartbeat is recent, 1 otherwise. Used as the container probe.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    if args.healthcheck:
        return _healthcheck()

    from workers.batch_worker import BatchWorker

    from afterlap_core.paths import Paths
    from afterlap_infrastructure.persistence.engine import (
        create_db_engine,
        create_session_factory,
        default_database_url,
    )

    url = default_database_url()
    if args.wait_for_database > 0.0:
        import migrate

        migrate._wait_for_database(url, args.wait_for_database)

    engine = create_db_engine(url)
    factory = create_session_factory(engine)
    paths = Paths.default(
        Path(os.environ["AFTERLAP_ARTIFACT_ROOT"]) if os.environ.get("AFTERLAP_ARTIFACT_ROOT") else None
    ).ensure()
    quota = ArtifactQuota(paths.artifacts, QuotaPolicy.from_environment())
    worker = BatchWorker(
        factory,
        staging_root=paths.artifacts / "staging",
        reports_root=paths.reports,
    )
    runner = build_runner(factory)

    stop = _Stop()
    stop.install()
    logger.info(
        "batch worker %s polling every %.1f s; experiment ceiling %d B, operational reserve %d B",
        worker.worker_id,
        args.poll_interval,
        quota.policy.experiment_ceiling_bytes,
        quota.policy.operational_reserve_bytes,
    )

    completed = 0
    last_verdict: QuotaVerdict | None = None

    def beat(state: str, *, detail: str | None = None, job_id: str | None = None) -> None:
        """Report this worker's own state into the shared artefact root.

        This service runs no HTTP server, so without a heartbeat a wedged
        worker is indistinguishable from an idle one to everything outside its
        own process. Written on every poll, not only on a state change: the
        age is the signal.
        """
        _write_heartbeat(
            paths.artifacts,
            worker_id=worker.worker_id,
            state=state,
            detail=detail,
            jobs_completed=completed,
            current_job_id=job_id,
            quota_verdict=None if last_verdict is None else last_verdict.value,
        )

    try:
        while not stop.requested and (args.max_jobs is None or completed < args.max_jobs):
            reading = quota.read()
            if reading.verdict is not last_verdict:
                logger.warning("artefact quota %s: %s", reading.verdict.value, reading.detail)
                last_verdict = reading.verdict
            if not reading.accepts_experiment_jobs:
                beat("refusing_work_on_quota", detail=reading.detail)
                if args.once:
                    return 0
                time.sleep(args.poll_interval)
                continue

            claimed = worker.claim()
            if claimed is None:
                beat("idle", detail="no queued experiment job to claim")
                if args.once:
                    return 0
                time.sleep(args.poll_interval)
                continue

            job_id, manifest_hash = claimed
            logger.info("claimed experiment job %s (manifest %s)", job_id, manifest_hash)
            with repeating_heartbeat(
                partial(beat, "running", detail=f"manifest {manifest_hash}", job_id=job_id)
            ):
                outcome = worker.run(job_id, manifest_hash, runner)
            completed += 1
            logger.info(
                "job %s finished: status=%s partial=%s units=%s failure=%s",
                outcome.job_id,
                outcome.status.value,
                outcome.partial_results,
                list(outcome.completed_units),
                outcome.failure,
            )
            beat("idle", detail=f"job {outcome.job_id} finished {outcome.status.value}")
            if args.once:
                return 0
        beat("stopped", detail="the worker loop exited")
    finally:
        engine.dispose()
    return 0


def _write_heartbeat(artifacts_root: Path, **fields: Any) -> None:
    """Write one heartbeat, never failing the worker over it.

    A heartbeat is diagnostic. An unwritable artefact root is already reported
    by the quota reading and by the API's own storage probe; losing the job
    that is running because the report could not be written would be worse
    than losing the report.
    """
    from afterlap_api.worker_health import WorkerHeartbeat

    try:
        WorkerHeartbeat.now(**fields).write(artifacts_root)
    except OSError as exc:
        logger.warning("could not write the batch worker heartbeat: %s", exc)


def _healthcheck() -> int:
    """Container probe: 0 while this worker's heartbeat is recent."""
    from afterlap_api.worker_health import worker_status
    from afterlap_core.paths import Paths

    storage_root = os.environ.get("AFTERLAP_ARTIFACT_ROOT")
    status = worker_status(Paths.default(None if storage_root is None else Path(storage_root)).artifacts)
    print(f"batch worker {status.status}: {status.detail}")
    return 0 if status.live else 1


if __name__ == "__main__":
    raise SystemExit(main())
