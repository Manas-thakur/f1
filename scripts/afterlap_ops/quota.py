"""Artefact-root disk budget.

``program/ARCHITECTURE.md`` and ``operations/TECHNICAL_SPEC.md`` both
require one behaviour and it is not a warning:

    Disk full -> stop experiment jobs first, preserve operational evidence,
    then withdraw if necessary.

Three orderings are load bearing:

1. **Experiment output yields first.** A benchmark trajectory can be recomputed
   from a frozen scenario and seed. A decision record cannot be recomputed from
   anything, because the state it was made against is gone. So the experiment
   ceiling is the *lower* threshold and batch admission stops there.
2. **Operational evidence keeps a reserve above that ceiling.** Between the
   ceiling and the reserve the session store still commits: an in-flight
   session finishes writing its audit trail rather than being truncated at the
   moment the disk got tight.
3. **Only above the reserve does the session withdraw.** Withdrawal is the last
   resort, and it is a withdrawal of *advice* — the evidence already written
   stays.

The measurement is a real walk of the artefact root plus a real
``shutil.disk_usage`` reading, so a filesystem that is genuinely full trips the
guard even when the configured budget has room. Nothing here estimates.

Classification is by tree, and the two classes are asymmetric on purpose:

* **experiment** — ``trajectories/``, ``reports/``, ``objects/``, ``staging/``:
  derived output, reproducible from a manifest.
* **operational** — the session database, ``spool/``, ``exports/``: evidence,
  reproducible from nothing.

An unrecognised tree counts as operational. That is the conservative direction:
an unclassified file makes the guard trip *sooner*, never later, so a tree
someone adds later cannot quietly consume the reserve.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

DEFAULT_EXPERIMENT_CEILING_BYTES = 2 * 1024**3
"""2 GiB of artefact root before experiment jobs stop being admitted."""

DEFAULT_OPERATIONAL_RESERVE_BYTES = 256 * 1024**2
"""256 MiB held above the ceiling so operational evidence keeps landing."""

EXPERIMENT_TREES: tuple[str, ...] = ("trajectories", "reports", "objects", "staging")
"""Derived output. Recomputable from a frozen scenario, seed and manifest."""

OPERATIONAL_TREES: tuple[str, ...] = ("spool", "exports")
"""Evidence. Not recomputable. The database file at the root counts too."""


class QuotaVerdict(StrEnum):
    """What the artefact root's occupancy permits right now."""

    ALLOW = "allow"
    """Under the experiment ceiling: everything proceeds."""

    STOP_EXPERIMENTS = "stop_experiments"
    """Over the ceiling, inside the reserve: batch jobs stop, sessions write."""

    WITHDRAW = "withdraw"
    """Reserve consumed: operational advice is withdrawn as the last resort."""


class QuotaExceeded(RuntimeError):
    """Raised where a caller wants a refusal to be an exception, not a value."""

    def __init__(self, reading: QuotaReading) -> None:
        super().__init__(reading.detail)
        self.reading = reading


@dataclass(frozen=True, slots=True)
class QuotaPolicy:
    """The two configured thresholds, in bytes of artefact root."""

    experiment_ceiling_bytes: int = DEFAULT_EXPERIMENT_CEILING_BYTES
    operational_reserve_bytes: int = DEFAULT_OPERATIONAL_RESERVE_BYTES

    def __post_init__(self) -> None:
        if self.experiment_ceiling_bytes <= 0:
            raise ValueError("the experiment ceiling must be a positive number of bytes")
        if self.operational_reserve_bytes <= 0:
            raise ValueError("the operational reserve must be a positive number of bytes")

    @property
    def withdraw_at_bytes(self) -> int:
        return self.experiment_ceiling_bytes + self.operational_reserve_bytes

    @classmethod
    def from_environment(cls) -> QuotaPolicy:
        """Read the policy the compose file passes in.

        A malformed value is an error, not a silent fall back to the default: a
        typo in a disk budget is exactly the kind of thing that must not be
        discovered by running out of disk.
        """

        def read(name: str, default: int) -> int:
            raw = os.environ.get(name)
            if raw is None or raw.strip() == "":
                return default
            try:
                value = int(raw)
            except ValueError as exc:
                raise ValueError(f"{name}={raw!r} is not an integer number of bytes") from exc
            if value <= 0:
                raise ValueError(f"{name}={raw!r} must be positive")
            return value

        return cls(
            experiment_ceiling_bytes=read(
                "AFTERLAP_EXPERIMENT_QUOTA_BYTES", DEFAULT_EXPERIMENT_CEILING_BYTES
            ),
            operational_reserve_bytes=read(
                "AFTERLAP_OPERATIONAL_RESERVE_BYTES", DEFAULT_OPERATIONAL_RESERVE_BYTES
            ),
        )


@dataclass(frozen=True, slots=True)
class QuotaReading:
    """One measurement of the artefact root and what it permits."""

    root: Path
    policy: QuotaPolicy
    used_bytes: int
    experiment_bytes: int
    operational_bytes: int
    filesystem_free_bytes: int
    file_count: int
    verdict: QuotaVerdict
    detail: str

    @property
    def accepts_experiment_jobs(self) -> bool:
        return self.verdict is QuotaVerdict.ALLOW

    @property
    def accepts_operational_writes(self) -> bool:
        return self.verdict is not QuotaVerdict.WITHDRAW

    @property
    def reclaimable_bytes(self) -> int:
        """Experiment output that could be pruned to get back under the ceiling."""
        return self.experiment_bytes

    def as_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "verdict": self.verdict.value,
            "detail": self.detail,
            "used_bytes": self.used_bytes,
            "experiment_bytes": self.experiment_bytes,
            "operational_bytes": self.operational_bytes,
            "filesystem_free_bytes": self.filesystem_free_bytes,
            "file_count": self.file_count,
            "experiment_ceiling_bytes": self.policy.experiment_ceiling_bytes,
            "operational_reserve_bytes": self.policy.operational_reserve_bytes,
            "withdraw_at_bytes": self.policy.withdraw_at_bytes,
            "accepts_experiment_jobs": self.accepts_experiment_jobs,
            "accepts_operational_writes": self.accepts_operational_writes,
        }


def _classify(relative: Path) -> str:
    head = relative.parts[0] if relative.parts else ""
    if head in EXPERIMENT_TREES:
        return "experiment"
    if head in OPERATIONAL_TREES:
        return "operational"
    return "operational"


class ArtifactQuota:
    """Measures an artefact root and answers what it currently permits."""

    def __init__(self, root: Path, policy: QuotaPolicy | None = None) -> None:
        self.root = Path(root)
        self.policy = policy or QuotaPolicy()

    def read(self) -> QuotaReading:
        """Walk the root and take a real filesystem free-space reading."""
        experiment = 0
        operational = 0
        count = 0
        root = self.root
        if root.is_dir():
            for dirpath, _dirnames, filenames in os.walk(root):
                here = Path(dirpath)
                for name in filenames:
                    path = here / name
                    try:
                        size = path.stat().st_size
                    except OSError:
                        continue
                    count += 1
                    if _classify(path.relative_to(root)) == "experiment":
                        experiment += size
                    else:
                        operational += size

        used = experiment + operational
        try:
            free = shutil.disk_usage(root if root.is_dir() else root.parent).free
        except OSError:
            free = 0

        verdict, detail = self._decide(used=used, experiment=experiment, free=free)
        return QuotaReading(
            root=root,
            policy=self.policy,
            used_bytes=used,
            experiment_bytes=experiment,
            operational_bytes=operational,
            filesystem_free_bytes=free,
            file_count=count,
            verdict=verdict,
            detail=detail,
        )

    def _decide(self, *, used: int, experiment: int, free: int) -> tuple[QuotaVerdict, str]:
        policy = self.policy

        if free < policy.operational_reserve_bytes // 8:
            return (
                QuotaVerdict.WITHDRAW,
                (
                    f"the filesystem holding {self.root} has {free} B free, below the "
                    f"{policy.operational_reserve_bytes // 8} B floor; operational advice is "
                    "withdrawn because the audit trail cannot be extended"
                ),
            )

        if used >= policy.withdraw_at_bytes:
            return (
                QuotaVerdict.WITHDRAW,
                (
                    f"artefact root {self.root} holds {used} B, past the "
                    f"{policy.withdraw_at_bytes} B withdrawal point "
                    f"(ceiling {policy.experiment_ceiling_bytes} B + reserve "
                    f"{policy.operational_reserve_bytes} B); experiment jobs are already "
                    f"stopped and {experiment} B of experiment output is reclaimable"
                ),
            )

        if used >= policy.experiment_ceiling_bytes:
            return (
                QuotaVerdict.STOP_EXPERIMENTS,
                (
                    f"artefact root {self.root} holds {used} B, at or past the "
                    f"{policy.experiment_ceiling_bytes} B experiment ceiling; new experiment "
                    f"jobs are refused so the {policy.operational_reserve_bytes} B reserve "
                    "stays available for operational evidence. "
                    f"{experiment} B of experiment output is reclaimable"
                ),
            )

        return (
            QuotaVerdict.ALLOW,
            (
                f"artefact root {self.root} holds {used} B of a "
                f"{policy.experiment_ceiling_bytes} B experiment ceiling; "
                f"{free} B free on the filesystem"
            ),
        )

    def admit_experiment_job(self, job_id: str) -> QuotaReading:
        """Refuse a batch job that would write past the ceiling.

        Returns the reading when the job may run, and raises otherwise, so a
        caller cannot accidentally ignore the refusal by discarding a boolean.
        """
        reading = self.read()
        if not reading.accepts_experiment_jobs:
            raise QuotaExceeded(
                QuotaReading(
                    root=reading.root,
                    policy=reading.policy,
                    used_bytes=reading.used_bytes,
                    experiment_bytes=reading.experiment_bytes,
                    operational_bytes=reading.operational_bytes,
                    filesystem_free_bytes=reading.filesystem_free_bytes,
                    file_count=reading.file_count,
                    verdict=reading.verdict,
                    detail=f"experiment job {job_id} refused: {reading.detail}",
                )
            )
        return reading

    def experiment_output_paths(self) -> tuple[Path, ...]:
        """The trees an operator may prune to recover space, in walk order."""
        return tuple(p for name in EXPERIMENT_TREES if (p := self.root / name).is_dir())


__all__ = [
    "DEFAULT_EXPERIMENT_CEILING_BYTES",
    "DEFAULT_OPERATIONAL_RESERVE_BYTES",
    "EXPERIMENT_TREES",
    "OPERATIONAL_TREES",
    "ArtifactQuota",
    "QuotaExceeded",
    "QuotaPolicy",
    "QuotaReading",
    "QuotaVerdict",
]
