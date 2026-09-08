"""Reader for the frozen objective manifest.

``configs/objectives/objective-v1.yaml`` is coordinator-owned and frozen. This
module only *reads* it. No coefficient of the declared trade-off is restated,
defaulted or overridden here: if a value is missing from the document, loading
fails rather than substituting one, because a planner that silently invented a
tail weight would make every comparison under that objective meaningless.

The loaded manifest is dimensionless. ``final_score`` and ``expected_utility``
are never reported as seconds; elapsed time, energy, position and probability
are published as separate physical fields (``contracts/UNITS_TIME.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import load_config
from ..paths import Paths, sha256_json

__all__ = ["ObjectiveManifest", "load_objective"]


def _scalar(document: dict[str, Any], *path: str) -> float:
    """Read ``document[path...]['value']``, failing loudly when it is absent."""
    node: Any = document
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise KeyError(
                f"objective manifest {document.get('id', '<unknown>')!r} does not declare "
                f"{'.'.join(path)}; the planner will not substitute a default for a frozen "
                "objective coefficient"
            )
        node = node[key]
    if not isinstance(node, dict) or "value" not in node:
        raise KeyError(f"objective entry {'.'.join(path)} has no 'value' field")
    return float(node["value"])


@dataclass(frozen=True, slots=True)
class ObjectiveManifest:
    """The declared trade-off, exactly as frozen on disk."""

    objective_id: str
    content_hash: str

    elapsed_second_penalty: float
    instruction_change_penalty: float
    finish_position_penalty: float
    terminal_failure_penalty: float
    potential_reference_time_scale_s: float

    gamma: float
    discount_horizon_s: float

    tail_alpha: float
    lambda_tail: float

    lambda_switch: float
    minimum_dwell_s: float
    improvement_threshold: float

    disagreement_penalty_weight: float

    def __post_init__(self) -> None:
        if not 0.0 < self.tail_alpha < 1.0:
            raise ValueError("tail alpha must lie strictly inside (0, 1)")
        if not 0.0 < self.gamma <= 1.0:
            raise ValueError("gamma must lie in (0, 1]")
        for name in ("lambda_tail", "lambda_switch", "improvement_threshold", "minimum_dwell_s"):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} cannot be negative")

    def discount(self, horizon_s: float) -> float:
        """``gamma ** horizon_s`` at the manifest's one-second policy cadence."""
        return float(self.gamma**horizon_s)


@lru_cache(maxsize=8)
def _load_cached(objective_id: str, root: str | None) -> ObjectiveManifest:
    paths = None if root is None else Paths.default(Path(root))
    document = load_config("objectives", objective_id, paths)
    return ObjectiveManifest(
        objective_id=str(document["id"]),
        content_hash=sha256_json(document),
        elapsed_second_penalty=_scalar(document, "utility", "elapsed_second_penalty"),
        instruction_change_penalty=_scalar(document, "utility", "instruction_change_penalty"),
        finish_position_penalty=_scalar(document, "utility", "finish_position_penalty"),
        terminal_failure_penalty=_scalar(document, "utility", "terminal_failure_penalty"),
        potential_reference_time_scale_s=_scalar(document, "utility", "potential_reference_time_scale_s"),
        gamma=_scalar(document, "discount", "gamma"),
        discount_horizon_s=_scalar(document, "discount", "horizon_s"),
        tail_alpha=_scalar(document, "tail", "alpha"),
        lambda_tail=_scalar(document, "tail", "lambda_tail"),
        lambda_switch=_scalar(document, "switching", "lambda_switch"),
        minimum_dwell_s=_scalar(document, "switching", "minimum_dwell_s"),
        improvement_threshold=_scalar(document, "switching", "improvement_threshold"),
        disagreement_penalty_weight=_scalar(document, "learned_scoring", "disagreement_penalty_weight"),
    )


def load_objective(objective_id: str = "objective-v1", paths: Paths | None = None) -> ObjectiveManifest:
    """Load and cache the frozen objective revision."""
    return _load_cached(objective_id, None if paths is None else str(paths.root))
