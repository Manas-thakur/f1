"""The smooth continuous model the solver differentiates.

Written once, in ordinary arithmetic, so that the CasADi formulation and the
plain-Python evaluation used for scoring and testing are the *same* function.
Only ``exp`` and ``log`` are injected; everything else is ``+``, ``*`` and
``**``, which CasADi symbols and Python floats both support. A test asserts the
two evaluations agree to float tolerance, so a future edit cannot let the
objective the solver minimises drift away from the objective that is reported.

Physical model
--------------

Over a segment of length ``L`` traversed at held speed ``v``, deploying ``e``
joules **out of the battery** and recovering ``h`` joules **into** it produces a
net propulsive energy at the wheels of::

    u = eta_drive * e - zeta * h / eta_charge

``zeta`` is the harvest opportunity coefficient: the share of recovered
mechanical energy that would otherwise have driven the car. Spread over the
baseline traversal time ``L / v`` this is an average extra propulsive power
``u * v / L``. Against the cubic drag law ``P = k v^3`` the segment settles at::

    v_new = (v^3 + beta * u)^(1/3),   beta = v / (k * L)
    t(e, h) = L * (v^3 + beta * u)^(-1/3)

This is smooth, strictly convex in ``e`` and gives diminishing returns, which is
what a linear "joules buy seconds" model gets wrong. It is a reduced model: it
ignores corner limits, traction and the driver's braking envelope, all of which
the full simulator applies during re-simulation. The two are expected to
disagree, and the disagreement is recorded rather than hidden.

Continuation and the counterattack
----------------------------------

Energy left at the end of the detailed horizon is valued analytically at the
marginal rate it would buy time at the reference speed, discounted by
``gamma ** horizon_s`` and tapered to exactly zero at the true finish. It is a
rate, not a fixed reserve, so nothing rewards arriving at the flag with a full
battery.

The rival's counterattack responds to *our* terminal reserve. A plan that empties
the battery to complete a pass hands the rival a reserve advantage, and the
smooth deficit term gives that advantage back to it in seconds inside the same
horizon. That is why a greedy pass is valued through the whole defined horizon
instead of being credited as permanent progress.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from afterlap_contracts import StateEstimate

from .config import PlannerConfig
from .objective import ObjectiveManifest
from .scenarios import PlanScenario
from .segments import PlanFrame

__all__ = [
    "SurrogateWeights",
    "build_weights",
    "cvar",
    "scenario_losses",
    "terminal_energy",
]


@dataclass(frozen=True, slots=True)
class SurrogateWeights:
    """Every scalar the loss needs, derived once per planner invocation."""

    elapsed_second_penalty: float
    position_penalty: float
    energy_value_rate: float
    """Utility per terminal joule. ``gamma**H * w_time * marginal_rate * availability``."""
    gap_logistic_scale_s: float
    counterattack_rate_s_per_j: float
    counterattack_energy_scale_j: float
    initial_advantage_s: float
    """Our lead in seconds at the observation cutoff. Negative when we are behind."""
    discount: float
    marginal_time_per_joule_s: float
    """``eta_drive / (3 k v_ref^3)``: seconds bought by the first joule at the reference speed."""


def build_weights(
    frame: PlanFrame,
    estimate: StateEstimate,
    objective: ObjectiveManifest,
    config: PlannerConfig,
) -> SurrogateWeights:
    """Derive the loss weights from the frozen objective and the planner config."""
    surrogate = config.surrogate
    drag = surrogate.drag_constant_kg_per_m
    reference_speed = frame.speed_mps
    marginal = frame.drivetrain_efficiency / (3.0 * drag * reference_speed**3)
    discount = objective.discount(frame.horizon_s)

    ahead = estimate.nearest_ahead
    behind = estimate.nearest_behind
    if ahead is not None and ahead.gap_s.value is not None:
        advantage_s = -abs(float(ahead.gap_s.value))
    elif behind is not None and behind.gap_s.value is not None:
        advantage_s = abs(float(behind.gap_s.value))
    else:
        advantage_s = 0.0

    # With nobody believed to be in contention there is no position to win or
    # lose inside the horizon, so the position and counterattack terms are zero
    # rather than a smooth guess about a rival that is not there.
    contested = ahead is not None or behind is not None

    return SurrogateWeights(
        elapsed_second_penalty=objective.elapsed_second_penalty,
        position_penalty=(
            discount * objective.finish_position_penalty * float(surrogate.position_persistence.value)
            if contested
            else 0.0
        ),
        energy_value_rate=(
            discount * objective.elapsed_second_penalty * marginal * frame.continuation_availability
        ),
        gap_logistic_scale_s=float(surrogate.gap_logistic_scale_s.value),
        counterattack_rate_s_per_j=(float(surrogate.counterattack_rate_s_per_j.value) if contested else 0.0),
        counterattack_energy_scale_j=float(surrogate.counterattack_energy_scale_j.value),
        initial_advantage_s=advantage_s,
        discount=discount,
        marginal_time_per_joule_s=marginal,
    )


def _segment_cubes(
    frame: PlanFrame,
    deploy: Sequence[Any],
    harvest: Sequence[Any],
) -> list[Any]:
    """``v^3 + beta * u`` per segment. Must stay above ``min_speed^3``."""
    cubes: list[Any] = []
    for segment in frame.segments:
        net = (
            frame.drivetrain_efficiency * deploy[segment.index]
            - frame.harvest_opportunity_coefficient * harvest[segment.index] / frame.charge_efficiency
        )
        cubes.append(segment.speed_mps**3 + segment.beta * net)
    return cubes


def corridor_time(frame: PlanFrame, deploy: Sequence[Any], harvest: Sequence[Any]) -> Any:
    """Traversal time of the whole corridor under one allocation."""
    total: Any = 0.0
    for segment, cube in zip(frame.segments, _segment_cubes(frame, deploy, harvest), strict=True):
        total = total + segment.length_m * cube ** (-1.0 / 3.0)
    return total


def terminal_energy(frame: PlanFrame, deploy: Sequence[Any], harvest: Sequence[Any]) -> Any:
    """Battery energy at the end of the detailed horizon.

    ``deploy`` leaves the battery and ``harvest`` is battery gain, so the ledger
    is a plain sum with no bus conversion (``handoffs/decisions.md`` D-01).
    """
    total: Any = frame.initial_energy_j
    for index in range(len(frame.segments)):
        total = total + harvest[index] - deploy[index]
    return total


def scenario_losses(
    frame: PlanFrame,
    scenarios: Sequence[PlanScenario],
    weights: SurrogateWeights,
    deploy: Sequence[Any],
    harvest: Sequence[Any],
    *,
    exp_fn: Callable[[Any], Any] = math.exp,
    log_fn: Callable[[Any], Any] = math.log,
) -> tuple[list[Any], Any, Any]:
    """Per-scenario loss, plus the corridor time and terminal energy behind it.

    The allocation is a single shared vector: the same ``deploy``/``harvest`` is
    evaluated in every scenario. The planner therefore cannot pick an action
    after seeing an unobserved future — non-anticipativity is structural here,
    not a constraint that could be forgotten.
    """
    time_s = corridor_time(frame, deploy, harvest)
    energy_j = terminal_energy(frame, deploy, harvest)
    baseline_s = frame.baseline_time_s
    scale = weights.counterattack_energy_scale_j

    losses: list[Any] = []
    for scenario in scenarios:
        excess = (scenario.rival_reserve_j - energy_j) / scale
        deficit_j = log_fn(1.0 + exp_fn(excess)) * scale
        advantage_s = (
            weights.initial_advantage_s
            + (baseline_s - time_s)
            - scenario.rival_pace_gain_s
            - weights.counterattack_rate_s_per_j * deficit_j
        )
        behind = 1.0 / (1.0 + exp_fn(advantage_s / weights.gap_logistic_scale_s))
        losses.append(
            weights.elapsed_second_penalty * time_s
            + weights.position_penalty * behind
            - weights.energy_value_rate * energy_j
        )
    return losses, time_s, energy_j


def cvar(
    losses: Sequence[float],
    probabilities: Sequence[float],
    alpha: float,
) -> tuple[float, float, tuple[float, ...]]:
    """Conditional value at risk by the auxiliary-variable formulation.

    Returns ``(cvar, eta, xi)`` where ``eta`` is the optimal auxiliary variable
    and ``xi[w] = max(0, loss[w] - eta)``. Minimising
    ``eta + sum p_w xi_w / (1 - alpha)`` over ``eta`` puts the optimum at the
    ``alpha`` quantile of the loss distribution, which is what the solver's
    auxiliary variables reproduce.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must lie strictly inside (0, 1)")
    if len(losses) != len(probabilities):
        raise ValueError("each loss needs exactly one probability")
    order = sorted(range(len(losses)), key=lambda i: losses[i])
    cumulative = 0.0
    eta = losses[order[-1]]
    for index in order:
        cumulative += probabilities[index]
        if cumulative >= alpha:
            eta = losses[index]
            break
    xi = tuple(max(0.0, loss - eta) for loss in losses)
    value = eta + sum(p * x for p, x in zip(probabilities, xi, strict=True)) / (1.0 - alpha)
    return value, eta, xi
