"""Artefact root filling up: experiment jobs stop first, evidence survives.

**Genuinely causes the condition.** The artefact root is filled with real
bytes — `write_filler` writes and `fsync`s them, no sparse files — and the
guard measures the tree with `os.walk` plus a real `shutil.disk_usage`
reading. The batch worker entrypoint is then run as a process function
(`scripts/batch_worker_main.main(["--once", ...])`) against that root and a
real database holding a real queued job, and the job's status afterwards is
what the drill asserts on.

**What is honestly new code rather than product behaviour.** There is no
quota check anywhere in `apps/` or `packages/` — `grep -r quota` finds
nothing. `ARCHITECTURE.md` requires the behaviour, so `afterlap_ops.quota`
implements it and `scripts/batch_worker_main.py` uses it. The API route
`POST /experiments` still admits a job with the disk full; that hunk is in
`handoffs/A14-integration-patch.md` and the gap is stated in `handoffs/A14.md`.
These drills therefore prove: the guard's thresholds behave as specified, the
batch worker genuinely refuses work under them, and operational evidence
written before the fill is intact and still extendable afterwards.
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from afterlap_ops.quota import ArtifactQuota, QuotaExceeded, QuotaPolicy, QuotaVerdict

from afterlap_api.db.engine import command_transaction
from afterlap_api.db.models import ExperimentJob
from afterlap_contracts import JobStatus
from afterlap_core.paths import Paths

from .conftest import LocalStore, actionable, open_store, start_session, tree_bytes, write_filler

CEILING = 4 * 1024 * 1024
RESERVE = 1024 * 1024
POLICY = QuotaPolicy(experiment_ceiling_bytes=CEILING, operational_reserve_bytes=RESERVE)


@pytest.fixture
def artefact_root(tmp_path: Path) -> Paths:
    """A real artefact tree, created the way the application creates it."""
    return Paths.default(tmp_path / "install").ensure()


def _queue_job(store: LocalStore, manifest_hash: str) -> str:
    job_id = f"exp-{uuid.uuid4().hex[:16]}"
    with command_transaction(store.factory) as db:
        db.add(
            ExperimentJob(
                id=job_id,
                manifest_hash=manifest_hash,
                status=JobStatus.QUEUED.value,
                progress=0.0,
                partial_results=False,
                created_at=datetime.now(UTC),
            )
        )
    return job_id


def _job_status(store: LocalStore, job_id: str) -> tuple[str, str | None]:
    with command_transaction(store.factory) as db:
        row = db.get(ExperimentJob, job_id)
        assert row is not None
        return row.status, row.failure


def _run_worker_once(
    root: Path, store: LocalStore, policy: QuotaPolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run the real batch entrypoint for exactly one poll."""
    import batch_worker_main

    monkeypatch.setenv("AFTERLAP_ROOT", str(root))
    monkeypatch.setenv("AFTERLAP_DATABASE_URL", store.url)
    monkeypatch.setenv("AFTERLAP_EXPERIMENT_QUOTA_BYTES", str(policy.experiment_ceiling_bytes))
    monkeypatch.setenv("AFTERLAP_OPERATIONAL_RESERVE_BYTES", str(policy.operational_reserve_bytes))
    assert batch_worker_main.main(["--once", "--wait-for-database", "0", "--poll-interval", "0.1"]) == 0


# --------------------------------------------------------------------------- #
# thresholds
# --------------------------------------------------------------------------- #


def test_the_guard_reads_a_real_tree_and_orders_the_two_thresholds(artefact_root: Paths):
    quota = ArtifactQuota(artefact_root.artifacts, POLICY)

    empty = quota.read()
    assert empty.verdict is QuotaVerdict.ALLOW
    assert empty.accepts_experiment_jobs and empty.accepts_operational_writes
    assert empty.filesystem_free_bytes > 0, "no real free-space reading was taken"

    # Experiment output past the ceiling, still inside the reserve.
    write_filler(artefact_root.trajectories / "run-0001.parquet", CEILING - 512 * 1024)
    write_filler(artefact_root.reports / "bench-0001.json", 1024 * 1024)
    reading = quota.read()
    print(f"\n{reading.verdict.value}: {reading.detail}")
    assert reading.used_bytes == tree_bytes(artefact_root.artifacts)
    assert reading.verdict is QuotaVerdict.STOP_EXPERIMENTS
    assert reading.accepts_experiment_jobs is False
    assert reading.accepts_operational_writes is True, "operational evidence lost its reserve too early"
    assert reading.experiment_bytes == reading.used_bytes, reading.as_dict()
    assert reading.reclaimable_bytes > 0

    # Past the reserve as well: withdrawal, the last resort.
    write_filler(artefact_root.trajectories / "run-0002.parquet", RESERVE)
    beyond = quota.read()
    print(f"{beyond.verdict.value}: {beyond.detail}")
    assert beyond.verdict is QuotaVerdict.WITHDRAW
    assert beyond.accepts_experiment_jobs is False
    assert beyond.accepts_operational_writes is False

    # Discarding recomputable output recovers, which is why it yields first.
    for path in quota.experiment_output_paths():
        shutil.rmtree(path)
    assert quota.read().verdict is QuotaVerdict.ALLOW


def test_an_unclassified_tree_counts_as_evidence_not_as_experiment_output(artefact_root: Paths):
    """Conservative direction: an unknown tree makes the guard trip sooner."""
    quota = ArtifactQuota(artefact_root.artifacts, POLICY)
    write_filler(artefact_root.artifacts / "something-new" / "blob.bin", 2 * 1024 * 1024)
    reading = quota.read()
    assert reading.operational_bytes == reading.used_bytes
    assert reading.experiment_bytes == 0
    assert reading.reclaimable_bytes == 0, "an unclassified tree was offered as reclaimable experiment output"


def test_a_malformed_budget_is_an_error_not_a_silent_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AFTERLAP_EXPERIMENT_QUOTA_BYTES", "two gigabytes")
    with pytest.raises(ValueError, match="not an integer number of bytes"):
        QuotaPolicy.from_environment()

    monkeypatch.setenv("AFTERLAP_EXPERIMENT_QUOTA_BYTES", "0")
    with pytest.raises(ValueError, match="must be positive"):
        QuotaPolicy.from_environment()


# --------------------------------------------------------------------------- #
# the batch worker under a full artefact root
# --------------------------------------------------------------------------- #


def test_a_full_artefact_root_stops_experiment_jobs_and_preserves_evidence(
    artefact_root: Paths, monkeypatch: pytest.MonkeyPatch
):
    store = open_store(artefact_root.artifacts, "afterlap.sqlite3")
    session = start_session(store.factory, spool_root=artefact_root.spool)
    recorder = session.recorder
    assert recorder is not None

    # Operational evidence exists before the disk fills.
    tick = session.advance_until(actionable)
    evidence_before = session.decision_ids()
    assert evidence_before, "no operational evidence existed before the fill"
    export = artefact_root.exports / "session-record.json"
    export.write_text(json.dumps({"session_id": session.session_id, "synthetic": True}), encoding="utf-8")

    job_id = _queue_job(store, manifest_hash="sha256:" + "0" * 64)

    # The thresholds are set *relative to what the running session already
    # occupies*. A fixed 4 MiB ceiling would already be breached by the session
    # database itself, and the drill would then be measuring nothing: the
    # question is what happens when experiment output pushes past a budget,
    # not whether a budget can be chosen too small.
    baseline = tree_bytes(artefact_root.artifacts)
    policy = QuotaPolicy(
        experiment_ceiling_bytes=baseline + 4 * 1024 * 1024,
        operational_reserve_bytes=1024 * 1024,
    )
    print(f"\noperational baseline {baseline} B; ceiling {policy.experiment_ceiling_bytes} B")

    # --- fill the artefact root with real experiment output ----------------- #
    quota = ArtifactQuota(artefact_root.artifacts, policy)
    written = 0
    index = 0
    while quota.read().verdict is QuotaVerdict.ALLOW:
        index += 1
        written += write_filler(artefact_root.trajectories / f"session-{index:04d}.parquet", 1024 * 1024)
        assert index < 64, "the fill loop is not converging on the configured ceiling"
    reading = quota.read()
    print(f"\nfilled {written} B of trajectories; {reading.verdict.value}: {reading.detail}")
    assert reading.verdict is QuotaVerdict.STOP_EXPERIMENTS

    # 1. The batch worker refuses the queued job, and says why.
    _run_worker_once(artefact_root.root, store, policy, monkeypatch)
    status, failure = _job_status(store, job_id)
    assert status == JobStatus.QUEUED.value, (
        f"the worker claimed job {job_id} with the artefact root over its ceiling (status {status})"
    )
    assert failure is None
    assert not list(artefact_root.reports.glob("*.json")), "a report was written under a full root"

    # The admission helper refuses as an exception too, so a caller cannot
    # discard a boolean and proceed.
    with pytest.raises(QuotaExceeded) as refusal:
        quota.admit_experiment_job(job_id)
    assert job_id in str(refusal.value)
    print(f"admission refused: {refusal.value}")

    # 2. Operational evidence is preserved: the rows are intact, the export is
    #    readable, and the session can still extend its audit trail.
    assert session.decision_ids() == evidence_before
    assert json.loads(export.read_text(encoding="utf-8"))["session_id"] == session.session_id
    assert tick.recommendation is not None
    later = session.advance(1.0)
    assert session.decision_ids()[: len(evidence_before)] == evidence_before
    assert len(session.decision_ids()) > len(evidence_before), (
        "the session store stopped accepting operational writes while the reserve was intact"
    )
    assert recorder.status().state.value == "available"
    assert later is not None

    # 3. Pruning the recomputable output re-admits the job — that is what makes
    #    "experiment jobs stop first" a recoverable state and not a dead end.
    for path in quota.experiment_output_paths():
        shutil.rmtree(path, ignore_errors=True)
    artefact_root.ensure()
    assert quota.read().verdict is QuotaVerdict.ALLOW

    _run_worker_once(artefact_root.root, store, policy, monkeypatch)
    status, failure = _job_status(store, job_id)
    print(f"after pruning: job status {status}, failure {failure}")
    assert status != JobStatus.QUEUED.value, "the worker still refused the job with the root emptied"
    # The job was admitted and then failed for the reason the drill set up: its
    # manifest hash is deliberately absent from the manifest store. Being
    # admitted is the claim under test; the failure text proves the admission.
    assert status == JobStatus.FAILED.value, status
    assert failure is not None and "manifest" in failure, failure
