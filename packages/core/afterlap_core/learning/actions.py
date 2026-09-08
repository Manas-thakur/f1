"""The two-dimensional bounded preference action.

``Box(-1, 1, shape=(2,))``. ``a[0]`` decodes to a deployment energy budget over
the fixed ten-second preference window; ``a[1]`` decodes to an energy target at
the next declared tactical checkpoint. Both use the specification's formula::

    lower + (a + 1) / 2 * (upper - lower)

These are **soft preferences**. They are not wheel torque and they are not
constraints. The planner penalises deviation from them, still generates its own
baseline candidates, and still returns a plan the independent checker passed. A
preference therefore cannot buy an illegal plan, and it cannot remove the
validated reference.

Bounds come from the current energy belief, the applicable rule limits and the
window, and every set of bounds is logged with the reason it came out that way:

* if the bounds **collapse** — a reachable range of zero width — the decode
  returns the fixed value and says so;
* if they are **invalid or unknown** — no usable energy capability, no resolved
  ceiling, a non-finite action — learned preferences are disabled for that tick
  and the caller takes the validated baseline capability path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import numpy as np
from gymnasium import spaces

from ..feature_manifest import ACTION_SIZE, PREFERENCE_WINDOW_S

if TYPE_CHECKING:
    from afterlap_contracts import ApplicableLimits, StateEstimate

__all__ = [
    "ACTION_HIGH",
    "ACTION_LOW",
    "ActionBounds",
    "BoundsStatus",
    "DecodedPreferences",
    "action_space",
    "compute_bounds",
    "decode_action",
]

ACTION_LOW = -1.0
ACTION_HIGH = 1.0

_COLLAPSE_TOLERANCE_J = 1.0
"""Below this width a range is treated as a single reachable value, not a range."""


def action_space() -> spaces.Box:
    """The frozen Gymnasium action space."""
    return spaces.Box(
        low=ACTION_LOW,
        high=ACTION_HIGH,
        shape=(ACTION_SIZE,),
        dtype=np.float32,
    )


class BoundsStatus(StrEnum):
    """Why a bound came out the way it did. Always logged with the bounds."""

    OK = "ok"
    COLLAPSED = "collapsed"
    ENERGY_UNAVAILABLE = "energy_unavailable"
    LIMITS_UNAVAILABLE = "limits_unavailable"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ActionBounds:
    """The decode range for one tick, with its provenance.

    ``budget_*`` is deployment energy leaving the battery over the fixed
    preference window. ``reserve_*`` is battery energy at the next declared
    tactical checkpoint. Both are joules, battery-side, matching decision D-01.
    """

    budget_lower_j: float
    budget_upper_j: float
    reserve_lower_j: float
    reserve_upper_j: float
    window_s: float
    checkpoint_interval_s: float
    budget_status: BoundsStatus
    reserve_status: BoundsStatus
    detail: str = ""

    @property
    def usable(self) -> bool:
        """True when a learned preference can be decoded at all."""
        return self.budget_status in (BoundsStatus.OK, BoundsStatus.COLLAPSED) and self.reserve_status in (
            BoundsStatus.OK,
            BoundsStatus.COLLAPSED,
        )

    @property
    def budget_width_j(self) -> float:
        return self.budget_upper_j - self.budget_lower_j

    @property
    def reserve_width_j(self) -> float:
        return self.reserve_upper_j - self.reserve_lower_j

    def as_dict(self) -> dict[str, float | str]:
        return {
            "budget_lower_j": self.budget_lower_j,
            "budget_upper_j": self.budget_upper_j,
            "reserve_lower_j": self.reserve_lower_j,
            "reserve_upper_j": self.reserve_upper_j,
            "window_s": self.window_s,
            "checkpoint_interval_s": self.checkpoint_interval_s,
            "budget_status": self.budget_status.value,
            "reserve_status": self.reserve_status.value,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class DecodedPreferences:
    """The decoded soft preferences, or an explicit refusal to produce them."""

    budget_j: float | None
    reserve_target_j: float | None
    bounds: ActionBounds
    learned_enabled: bool
    reason: str
    raw_action: tuple[float, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "budget_j": self.budget_j,
            "reserve_target_j": self.reserve_target_j,
            "learned_enabled": self.learned_enabled,
            "reason": self.reason,
            "raw_action": list(self.raw_action),
            "bounds": self.bounds.as_dict(),
        }


def _unusable(
    window_s: float,
    checkpoint_interval_s: float,
    status: BoundsStatus,
    detail: str,
) -> ActionBounds:
    return ActionBounds(
        budget_lower_j=0.0,
        budget_upper_j=0.0,
        reserve_lower_j=0.0,
        reserve_upper_j=0.0,
        window_s=window_s,
        checkpoint_interval_s=checkpoint_interval_s,
        budget_status=status,
        reserve_status=status,
        detail=detail,
    )


def compute_bounds(
    estimate: StateEstimate,
    limits: ApplicableLimits | None,
    *,
    window_s: float = PREFERENCE_WINDOW_S,
    checkpoint_interval_s: float,
    discharge_efficiency: float = 1.0,
) -> ActionBounds:
    """Derive the reachable decode range from belief, limits and the window.

    The budget's lower bound is zero, as the specification fixes. Its upper bound
    is a *conservative reachable expenditure estimate*: the smaller of what the
    deployment ceiling can pass in the window and what is actually above the
    battery floor. It is deliberately not the ceiling alone, because a ceiling
    the battery cannot supply is not a reachable expenditure.

    The reserve range is the declared battery operating window, narrowed to what
    the checkpoint interval can physically reach from the current energy.
    """
    if window_s <= 0.0 or checkpoint_interval_s <= 0.0:
        return _unusable(
            window_s,
            checkpoint_interval_s,
            BoundsStatus.INVALID,
            "the preference window and checkpoint interval must both be positive",
        )
    if limits is None:
        return _unusable(
            window_s,
            checkpoint_interval_s,
            BoundsStatus.LIMITS_UNAVAILABLE,
            "no resolved rule context, so no applicable deployment or recovery ceiling",
        )
    if not estimate.quality.own_energy_capability or not estimate.own_car.has_energy_capability:
        return _unusable(
            window_s,
            checkpoint_interval_s,
            BoundsStatus.ENERGY_UNAVAILABLE,
            "own stored energy is not observable, so no reachable expenditure can be bounded",
        )

    energy_j = estimate.own_car.battery_energy_j.value
    assert energy_j is not None
    floor_j = limits.battery_energy_min_j
    ceiling_j = limits.battery_energy_max_j
    deploy_w = limits.deployment_ceiling_w
    recover_w = limits.recovery_ceiling_w

    if floor_j is None or ceiling_j is None or deploy_w is None:
        return _unusable(
            window_s,
            checkpoint_interval_s,
            BoundsStatus.LIMITS_UNAVAILABLE,
            "the applicable limits do not resolve the battery window or the deployment ceiling",
        )
    if ceiling_j <= floor_j:
        return _unusable(
            window_s, checkpoint_interval_s, BoundsStatus.INVALID, "the battery operating window is empty"
        )
    if discharge_efficiency <= 0.0:
        return _unusable(
            window_s, checkpoint_interval_s, BoundsStatus.INVALID, "discharge efficiency must be positive"
        )

    available_j = max(0.0, float(energy_j) - float(floor_j))
    ceiling_reachable_j = float(deploy_w) * window_s / discharge_efficiency
    budget_upper = min(available_j, ceiling_reachable_j)
    budget_status = BoundsStatus.OK
    if budget_upper <= _COLLAPSE_TOLERANCE_J:
        budget_upper = 0.0
        budget_status = BoundsStatus.COLLAPSED

    max_gain_j = 0.0 if recover_w is None else max(0.0, float(recover_w)) * checkpoint_interval_s
    max_loss_j = max(0.0, float(deploy_w)) * checkpoint_interval_s / discharge_efficiency
    reserve_lower = max(float(floor_j), float(energy_j) - max_loss_j)
    reserve_upper = min(float(ceiling_j), float(energy_j) + max_gain_j)
    reserve_status = BoundsStatus.OK
    if reserve_upper < reserve_lower:
        reserve_lower = max(float(floor_j), min(float(energy_j), float(ceiling_j)))
        reserve_upper = reserve_lower
        reserve_status = BoundsStatus.COLLAPSED
    elif reserve_upper - reserve_lower <= _COLLAPSE_TOLERANCE_J:
        reserve_upper = reserve_lower
        reserve_status = BoundsStatus.COLLAPSED

    detail_parts = [
        f"available above floor {available_j:.0f} J",
        f"ceiling over {window_s:.1f} s window {ceiling_reachable_j:.0f} J",
        f"reachable checkpoint interval {checkpoint_interval_s:.1f} s",
    ]
    return ActionBounds(
        budget_lower_j=0.0,
        budget_upper_j=budget_upper,
        reserve_lower_j=reserve_lower,
        reserve_upper_j=reserve_upper,
        window_s=window_s,
        checkpoint_interval_s=checkpoint_interval_s,
        budget_status=budget_status,
        reserve_status=reserve_status,
        detail="; ".join(detail_parts),
    )


def _affine(action: float, lower: float, upper: float) -> float:
    return lower + (action + 1.0) / 2.0 * (upper - lower)


def decode_action(
    action: np.ndarray | list[float] | tuple[float, ...], bounds: ActionBounds
) -> DecodedPreferences:
    """Decode a raw SAC action into bounded soft preferences.

    The raw action is kept on the result. Replay stores *this* vector as the
    agent action; the projected budget and the executed profile are diagnostic
    fields. Substituting the executed control would train the critic on the
    wrong action semantics.
    """
    array = np.asarray(action, dtype=np.float64).reshape(-1)
    raw = tuple(float(v) for v in array)

    if array.shape != (ACTION_SIZE,):
        return DecodedPreferences(
            budget_j=None,
            reserve_target_j=None,
            bounds=bounds,
            learned_enabled=False,
            reason=f"action has shape {array.shape}, expected ({ACTION_SIZE},)",
            raw_action=raw,
        )
    if not np.all(np.isfinite(array)):
        return DecodedPreferences(
            budget_j=None,
            reserve_target_j=None,
            bounds=bounds,
            learned_enabled=False,
            reason="action contains a non-finite component",
            raw_action=raw,
        )
    if not bounds.usable:
        return DecodedPreferences(
            budget_j=None,
            reserve_target_j=None,
            bounds=bounds,
            learned_enabled=False,
            reason=(
                f"bounds unusable ({bounds.budget_status.value}/{bounds.reserve_status.value}): "
                f"{bounds.detail}"
            ),
            raw_action=raw,
        )

    clipped = np.clip(array, ACTION_LOW, ACTION_HIGH)
    budget = _affine(float(clipped[0]), bounds.budget_lower_j, bounds.budget_upper_j)
    reserve = _affine(float(clipped[1]), bounds.reserve_lower_j, bounds.reserve_upper_j)

    if not (math.isfinite(budget) and math.isfinite(reserve)):  # pragma: no cover - defence in depth
        return DecodedPreferences(
            budget_j=None,
            reserve_target_j=None,
            bounds=bounds,
            learned_enabled=False,
            reason="decoded preference was not finite",
            raw_action=raw,
        )

    reasons: list[str] = []
    if bounds.budget_status is BoundsStatus.COLLAPSED:
        reasons.append("budget range collapsed to its fixed value")
    if bounds.reserve_status is BoundsStatus.COLLAPSED:
        reasons.append("reserve range collapsed to its fixed value")

    return DecodedPreferences(
        budget_j=budget,
        reserve_target_j=reserve,
        bounds=bounds,
        learned_enabled=True,
        reason="; ".join(reasons) if reasons else "decoded within reachable bounds",
        raw_action=raw,
    )
