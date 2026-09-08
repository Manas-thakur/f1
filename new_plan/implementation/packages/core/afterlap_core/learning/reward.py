"""Reward revision ``objective-v1``.

Every coefficient is read from the frozen ``configs/objectives/objective-v1.yaml``
through :class:`afterlap_contracts.RewardManifest`, which re-derives and enforces
the failure-penalty bound. Nothing here restates a number from the specification
prose: a reward that quietly diverged from the frozen objective would make every
comparison under that objective meaningless.

The shaping is potential-based::

    Phi(s)   = -remaining_reference_time_s / potential_reference_time_scale_s
    shaping  = gamma * Phi(s') - Phi(s)

with ``Phi`` forced to zero at a **true terminal** state. Under that convention
the shaping telescopes over a whole episode to ``-Phi(s_0)`` plus the discounted
tail, which :mod:`tests.learning.test_reward` verifies numerically rather than
by argument.

Three rules the specification calls out and this module implements literally:

* there is no repeatable positive reward for a pass, so passing and being
  repassed earns nothing;
* unused energy at the finish earns nothing;
* a truncated episode keeps its potential. Zeroing it would tell the critic that
  running out of wall-clock is the same as retiring the car.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from afterlap_contracts import RewardManifest

from ..config import load_config
from ..paths import Paths, sha256_json

__all__ = [
    "REWARD_REVISION",
    "RewardTerms",
    "load_reward_manifest",
    "objective_content_hash",
    "potential",
    "step_reward",
]

REWARD_REVISION = "objective-v1"


def _scalar(document: dict[str, object], *path: str) -> float:
    node: object = document
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise KeyError(
                f"objective manifest {document.get('id', '<unknown>')!r} does not declare "
                f"{'.'.join(path)}; the reward will not substitute a default for a frozen coefficient"
            )
        node = node[key]
    if not isinstance(node, dict) or "value" not in node:
        raise KeyError(f"objective entry {'.'.join(path)} has no 'value' field")
    return float(node["value"])  # type: ignore[arg-type]


@lru_cache(maxsize=8)
def _load_cached(objective_id: str, root: str | None) -> tuple[RewardManifest, str]:
    paths = None if root is None else Paths.default(Path(root))
    document = load_config("objectives", objective_id, paths)
    bounds = document.get("bounds_assumed")
    if not isinstance(bounds, dict):
        raise KeyError(
            f"objective manifest {objective_id!r} declares no 'bounds_assumed' block; the "
            "failure-penalty bound cannot be re-derived without it"
        )
    manifest = RewardManifest(
        revision=str(document["id"]),
        elapsed_second_penalty=_scalar(document, "utility", "elapsed_second_penalty"),
        instruction_change_penalty=_scalar(document, "utility", "instruction_change_penalty"),
        finish_position_penalty=_scalar(document, "utility", "finish_position_penalty"),
        terminal_failure_penalty=_scalar(document, "utility", "terminal_failure_penalty"),
        potential_reference_time_scale_s=_scalar(document, "utility", "potential_reference_time_scale_s"),
        gamma=_scalar(document, "discount", "gamma"),
        maximum_supported_field_size=int(bounds["maximum_supported_field_size"]),
        maximum_charged_instruction_changes_per_s=float(bounds["maximum_charged_instruction_changes_per_s"]),
    )
    return manifest, sha256_json(document)


def load_reward_manifest(objective_id: str = REWARD_REVISION, paths: Paths | None = None) -> RewardManifest:
    """Load the frozen reward revision.

    ``RewardManifest`` re-derives the failure-penalty bound on construction, so a
    document whose penalty no longer dominates the discounted running cost plus
    the worst finish-position cost fails to load at all.
    """
    manifest, _ = _load_cached(objective_id, None if paths is None else str(paths.root))
    return manifest


def objective_content_hash(objective_id: str = REWARD_REVISION, paths: Paths | None = None) -> str:
    """SHA-256 of the objective document the reward was loaded from."""
    _, digest = _load_cached(objective_id, None if paths is None else str(paths.root))
    return digest


def assert_field_size_supported(manifest: RewardManifest, field_size: int) -> None:
    """Refuse a scenario family outside the assumptions the bound was derived from.

    ``ENVIRONMENT_AND_FEATURES.md``: "Reject scenario families outside these
    assumptions until the bound is recomputed."
    """
    if field_size > manifest.maximum_supported_field_size:
        raise ValueError(
            f"scenario declares {field_size} cars, above the {manifest.maximum_supported_field_size} "
            "the failure-penalty bound was derived from; recompute the bound before training on it"
        )


def potential(
    remaining_reference_time_s: float | None,
    manifest: RewardManifest,
    *,
    terminal: bool,
) -> float:
    """``Phi``, the shaping potential.

    Zero at a true terminal state, by definition. ``None`` — no usable reference
    time — is also zero, and the caller records that the shaping term was
    unavailable rather than pretending a number existed.
    """
    if terminal or remaining_reference_time_s is None:
        return 0.0
    return -float(remaining_reference_time_s) / manifest.potential_reference_time_scale_s


@dataclass(frozen=True, slots=True)
class RewardTerms:
    """One transition's reward, decomposed so no component can hide in a total.

    ``total`` is dimensionless. It is not seconds: elapsed time and finish
    position are recorded separately in ``elapsed_s`` and ``finish_position``.
    """

    elapsed_penalty: float
    instruction_penalty: float
    terminal_finish: float
    terminal_failure: float
    shaping: float
    potential_current: float
    potential_next: float
    elapsed_s: float
    instruction_changes: int
    terminated: bool
    truncated: bool
    finish_position: int | None = None
    shaping_available: bool = True

    @property
    def base_reward(self) -> float:
        return self.elapsed_penalty + self.instruction_penalty

    @property
    def terminal_term(self) -> float:
        return self.terminal_finish + self.terminal_failure

    @property
    def total(self) -> float:
        return self.base_reward + self.terminal_term + self.shaping

    def as_dict(self) -> dict[str, float | int | bool | None]:
        return {
            "elapsed_penalty": self.elapsed_penalty,
            "instruction_penalty": self.instruction_penalty,
            "terminal_finish": self.terminal_finish,
            "terminal_failure": self.terminal_failure,
            "shaping": self.shaping,
            "potential_current": self.potential_current,
            "potential_next": self.potential_next,
            "elapsed_s": self.elapsed_s,
            "instruction_changes": self.instruction_changes,
            "terminated": self.terminated,
            "truncated": self.truncated,
            "finish_position": self.finish_position,
            "shaping_available": self.shaping_available,
            "total": self.total,
        }


def step_reward(
    manifest: RewardManifest,
    *,
    elapsed_s: float,
    instruction_changes: int,
    remaining_reference_time_s: float | None,
    next_remaining_reference_time_s: float | None,
    terminated: bool,
    truncated: bool = False,
    finished: bool = False,
    finish_position: int | None = None,
    failed: bool = False,
) -> RewardTerms:
    """Reward for one policy step.

    ``elapsed_s`` is the *actual* simulated time the step consumed. A partial
    final interval at the finish is therefore charged what it really cost, not a
    whole cadence tick.

    ``terminated`` means a true terminal state — a finish or a physical DNF —
    and forces the next potential to zero. ``truncated`` is an external time
    limit: continuation value is real there, so the potential is **retained**.

    Nothing in this function reads the car's remaining energy. Unused finish
    energy earns nothing, and it cannot, because no term depends on it.
    """
    if terminated and truncated:
        raise ValueError("a transition cannot be both terminated and truncated")
    if finished and failed:
        raise ValueError("a transition cannot be both a finish and a physical failure")
    if (finished or failed) and not terminated:
        raise ValueError("a finish or a failure is a terminal state and must set terminated=True")
    if finished and finish_position is None:
        raise ValueError("a finish must record the position it finished in")

    elapsed_penalty = -manifest.elapsed_second_penalty * float(elapsed_s)
    instruction_penalty = -manifest.instruction_change_penalty * int(instruction_changes)

    terminal_finish = 0.0
    if finished:
        assert finish_position is not None
        if finish_position < 1:
            raise ValueError("finish position is one-based")
        terminal_finish = -manifest.finish_position_penalty * (finish_position - 1)
    terminal_failure = -manifest.terminal_failure_penalty if failed else 0.0

    available = remaining_reference_time_s is not None and (
        terminated or next_remaining_reference_time_s is not None
    )
    phi_now = potential(remaining_reference_time_s, manifest, terminal=False)
    phi_next = potential(next_remaining_reference_time_s, manifest, terminal=terminated)
    shaping = manifest.gamma * phi_next - phi_now if available else 0.0

    return RewardTerms(
        elapsed_penalty=elapsed_penalty,
        instruction_penalty=instruction_penalty,
        terminal_finish=terminal_finish,
        terminal_failure=terminal_failure,
        shaping=shaping,
        potential_current=phi_now,
        potential_next=phi_next,
        elapsed_s=float(elapsed_s),
        instruction_changes=int(instruction_changes),
        terminated=terminated,
        truncated=truncated,
        finish_position=finish_position,
        shaping_available=available,
    )


def without_shaping(terms: RewardTerms) -> RewardTerms:
    """The same transition with the shaping term removed.

    Used by the telescoping test and by any diagnostic that needs the unshaped
    return; the shaped and unshaped returns of a complete episode differ by
    exactly ``-Phi(s_0)``.
    """
    return replace(terms, shaping=0.0)
