"""The continuous segment-energy schedule, solved with CasADi/IPOPT.

``handoffs/decisions.md`` D-02: acados publishes no Windows wheel, so CasADi with
its bundled IPOPT is the active continuous solver for this release. The identity
of the solver is recorded on every candidate so a later acados build is a visible
change and not a silent one. If CasADi cannot be imported or its IPOPT plugin is
missing, :class:`SolverUnavailable` is raised and the planner reports
``PlanningStatus.SOLVER_UNAVAILABLE`` — it never substitutes an unconstrained
heuristic and calls that a solve.

Decision variables
------------------

``e_i`` battery energy deployed over segment ``i`` (leaving the battery), ``h_i``
battery energy gained over segment ``i`` (``handoffs/decisions.md`` D-01), the
CVaR auxiliary ``eta``, and one ``xi_w`` per scenario. Near-term control is **one
shared vector**: every scenario is evaluated against the same ``e`` and ``h``, so
no allocation can be chosen after seeing an unobserved future. Replanning, not
the solver, supplies later feedback.

Energies are scaled to megajoules inside the solver. The marginal value of a
joule is around ``1e-6`` utility units, so an unscaled formulation puts the whole
gradient below IPOPT's convergence tolerance and any feasible point looks
optimal. Every constraint row is likewise normalised to order one.

Hard constraints
----------------

============================  ==============================================
Applicable electrical curve   ``e_i / dt_i <= C_reg(v)`` — a box bound, since
                              ``C_reg`` is constant at the frame's held speed
Thermal derate                ``e_i / dt_i <= derate * C_reg(v)`` — same box
Profile realism               ``e_i / dt_i <= profile_fraction * C_reg(v)``
Battery operating range       floor and ceiling at every segment, using a
                              conservative interior envelope
Recharge ledger               ``sum(h / eta_charge) <= allowance`` per lap, on
                              the **charge** bus, resetting at a rollover
Ramp                          ``|dP| / execution_window <= max_ramp`` at entry
                              and at every profile transition
Corridor speed floor          harvest may not drive the surrogate speed below
                              the configured floor (enforced as a bound, so it
                              holds at every iterate and not only at the answer)
Action timing                 lead time and execution window, enforced when the
                              frame is built; an infeasible corridor never
                              reaches the solver
Terminal energy target        ``E_T >= target`` when the caller sets one
============================  ==============================================

A finite scenario ensemble checks sampled uncertainty only. It is not universal
robustness, and the ensemble size is published with the decision.
"""

from __future__ import annotations

import importlib
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from .config import PlannerConfig
from .objective import ObjectiveManifest
from .scenarios import PlanScenario
from .segments import PlanFrame
from .surrogate import SurrogateWeights, cvar, scenario_losses

__all__ = [
    "ENERGY_SCALE_J",
    "AllocationSolution",
    "SolverDeadlineExpired",
    "SolverUnavailable",
    "solve_allocation",
    "solver_identity",
]

ENERGY_SCALE_J = 1.0e6
"""Solver energy unit. One megajoule, so decision variables are order one."""

_NEUTRAL_ALLOWANCE_J = 1.0e9
"""Stand-in for "the pack declares no per-lap recharge allowance".

Three orders of magnitude above any harvest the frame can bound, so the row is
inactive, while still small enough that the constraint stays well scaled.
"""

_NEUTRAL_RAMP_W = 1.0e9
"""Stand-in for "the pack declares no power-change limit"."""

_SOLVER_CACHE: dict[tuple[int, int, int, float], Any] = {}


class SolverUnavailable(RuntimeError):
    """The continuous solver backend is not usable in this environment."""


class SolverDeadlineExpired(RuntimeError):
    """No decision budget remained when a solve was requested."""


def _casadi() -> Any:
    """Import the solver backend lazily.

    ``importlib`` rather than a plain ``import casadi`` for two reasons: the
    dependency is genuinely optional (a deployment without it reports
    ``SOLVER_UNAVAILABLE`` rather than failing to start), and the shipped CasADi
    type stub does not type-check, so a static import would make the planner's
    own type check fail on a third-party file.
    """
    try:
        return importlib.import_module("casadi")
    except Exception as exc:  # pragma: no cover - exercised only without casadi
        raise SolverUnavailable(f"casadi is not importable: {exc}") from exc


@lru_cache(maxsize=1)
def solver_identity() -> str:
    """Human-readable identity of the active continuous solver backend."""
    try:
        casadi = _casadi()
    except SolverUnavailable as exc:
        return f"unavailable: {exc}"
    return f"casadi-{casadi.__version__}/ipopt"


@dataclass(frozen=True, slots=True)
class AllocationSolution:
    """One solved schedule with everything needed to audit it."""

    deploy_j: tuple[float, ...]
    harvest_j: tuple[float, ...]
    eta: float
    xi: tuple[float, ...]
    scenario_losses: tuple[float, ...]
    expected_utility: float
    cvar_loss: float
    corridor_time_s: float
    terminal_energy_j: float
    objective_value: float
    solver_status: str
    iterations: int
    duration_ms: float
    converged: bool
    deadline_exceeded: bool


# --------------------------------------------------------------------------- #
# symbolic problem
# --------------------------------------------------------------------------- #


def _build_problem(casadi: Any, n: int, w: int, config: PlannerConfig) -> Any:
    """Symbolic NLP for one ``(segments, scenarios)`` shape.

    Every datum is a symbolic parameter, so the compiled solver is reused across
    candidates and across invocations; only the parameter vector changes. That
    keeps the per-candidate cost to the solve itself rather than to code
    generation.
    """
    ca = casadi
    deploy_hat = ca.SX.sym("deploy_mj", n)
    harvest_hat = ca.SX.sym("harvest_mj", n)
    eta = ca.SX.sym("eta")
    xi = ca.SX.sym("xi", w)
    x = ca.vertcat(deploy_hat, harvest_hat, eta, xi)

    seg_length = ca.SX.sym("seg_length_m", n)
    seg_cube = ca.SX.sym("seg_speed_cubed", n)
    seg_beta = ca.SX.sym("seg_beta", n)
    seg_duration = ca.SX.sym("seg_duration_s", n)
    seg_ramp_budget = ca.SX.sym("seg_ramp_budget_w", n)
    seg_lap_allowance = ca.SX.sym("seg_lap_allowance_mj", n)
    lap_mask = ca.SX.sym("lap_mask", n * n)
    globals_ = ca.SX.sym("globals", 11)
    weights_ = ca.SX.sym("weights", 8)
    scen_p = ca.SX.sym("scenario_weight", w)
    scen_reserve = ca.SX.sym("scenario_reserve_mj", w)
    scen_pace = ca.SX.sym("scenario_pace_s", w)
    p = ca.vertcat(
        seg_length,
        seg_cube,
        seg_beta,
        seg_duration,
        seg_ramp_budget,
        seg_lap_allowance,
        lap_mask,
        globals_,
        weights_,
        scen_p,
        scen_reserve,
        scen_pace,
    )

    energy0_hat = globals_[0]
    floor_hat = globals_[1]
    ceiling_hat = globals_[2]
    energy_scale = globals_[3]
    charge_eff = globals_[4]
    drive_eff = globals_[5]
    zeta = globals_[6]
    target_hat = globals_[7]
    current_power = globals_[8]
    baseline_time = globals_[9]
    lambda_tail = globals_[10]

    w_time = weights_[0]
    w_pos = weights_[1]
    v_rate_mj = weights_[2]
    tau = weights_[3]
    counter_rate_mj = weights_[4]
    counter_scale_hat = weights_[5]
    advantage0 = weights_[6]
    alpha = weights_[7]

    # --- surrogate dynamics (joules, so beta keeps its physical units) ------
    net_j = energy_scale * (drive_eff * deploy_hat - zeta * harvest_hat / charge_eff)
    cubes = seg_cube + seg_beta * net_j
    corridor_time = ca.sum1(seg_length * cubes ** (-1.0 / 3.0))
    terminal_hat = energy0_hat + ca.sum1(harvest_hat) - ca.sum1(deploy_hat)

    constraints: list[Any] = []

    running = energy0_hat
    for index in range(n):
        constraints.append(running - deploy_hat[index] - floor_hat)
        constraints.append(ceiling_hat - (running + harvest_hat[index]))
        running = running + harvest_hat[index] - deploy_hat[index]

    for index in range(n):
        spent = ca.SX(0)
        for other in range(n):
            spent = spent + lap_mask[index * n + other] * harvest_hat[other] / charge_eff
        constraints.append(seg_lap_allowance[index] - spent)

    power = energy_scale * deploy_hat / seg_duration
    constraints.append(1.0 - (power[0] - current_power) / seg_ramp_budget[0])
    constraints.append(1.0 + (power[0] - current_power) / seg_ramp_budget[0])
    for index in range(n - 1):
        delta = power[index + 1] - power[index]
        constraints.append(1.0 - delta / seg_ramp_budget[index + 1])
        constraints.append(1.0 + delta / seg_ramp_budget[index + 1])

    constraints.append(terminal_hat - target_hat)

    losses: list[Any] = []
    for index in range(w):
        excess = (scen_reserve[index] - terminal_hat) / counter_scale_hat
        deficit_hat = ca.log(1.0 + ca.exp(excess)) * counter_scale_hat
        advantage = (
            advantage0 + (baseline_time - corridor_time) - scen_pace[index] - counter_rate_mj * deficit_hat
        )
        behind = 1.0 / (1.0 + ca.exp(advantage / tau))
        losses.append(w_time * corridor_time + w_pos * behind - v_rate_mj * terminal_hat)

    expected = ca.SX(0)
    tail = ca.SX(0)
    for index in range(w):
        expected = expected + scen_p[index] * losses[index]
        tail = tail + scen_p[index] * xi[index]
        constraints.append(xi[index] - losses[index] + eta)
    objective = expected + lambda_tail * (eta + tail / (1.0 - alpha))

    problem = {"x": x, "f": objective, "g": ca.vertcat(*constraints), "p": p}
    options = {
        "print_time": False,
        "ipopt.print_level": config.solver.print_level,
        "ipopt.sb": "yes",
        "ipopt.max_iter": config.solver.max_iterations,
        "ipopt.tol": config.solver.tolerance,
        "ipopt.acceptable_tol": config.solver.tolerance * 1.0e3,
    }
    return ca.nlpsol(f"afterlap_planner_{n}_{w}", "ipopt", problem, options)


def _solver_for(n: int, w: int, config: PlannerConfig) -> Any:
    key = (n, w, config.solver.max_iterations, config.solver.tolerance)
    cached = _SOLVER_CACHE.get(key)
    if cached is None:
        cached = _build_problem(_casadi(), n, w, config)
        _SOLVER_CACHE[key] = cached
    return cached


def _pack(
    frame: PlanFrame,
    scenarios: list[PlanScenario],
    weights: SurrogateWeights,
    objective: ObjectiveManifest,
) -> list[float]:
    """Flatten the frame, weights and ensemble into the parameter vector."""
    scale = ENERGY_SCALE_J
    n = len(frame.segments)
    allowance = (
        _NEUTRAL_ALLOWANCE_J
        if frame.recharge_allowance_per_lap_j is None
        else frame.recharge_allowance_per_lap_j
    )
    ramp = _NEUTRAL_RAMP_W if frame.max_power_ramp_w_per_s is None else frame.max_power_ramp_w_per_s
    first_lap = frame.segments[0].lap_index
    target = frame.terminal_target_energy_j
    if target is None:
        target = frame.energy_floor_j

    values: list[float] = []
    values += [s.length_m for s in frame.segments]
    values += [s.speed_mps**3 for s in frame.segments]
    values += [s.beta for s in frame.segments]
    values += [s.duration_s for s in frame.segments]
    values += [max(ramp * s.execution_window_s, 1.0) for s in frame.segments]
    values += [
        (allowance - (frame.recharge_used_this_lap_j if s.lap_index == first_lap else 0.0)) / scale
        for s in frame.segments
    ]
    for a in frame.segments:
        for b in frame.segments:
            values.append(1.0 if (b.lap_index == a.lap_index and b.index <= a.index) else 0.0)

    values += [
        frame.initial_energy_j / scale,
        frame.energy_floor_j / scale,
        frame.energy_ceiling_j / scale,
        scale,
        frame.charge_efficiency,
        frame.drivetrain_efficiency,
        frame.harvest_opportunity_coefficient,
        target / scale,
        frame.current_power_w,
        frame.baseline_time_s,
        objective.lambda_tail,
    ]
    values += [
        weights.elapsed_second_penalty,
        weights.position_penalty,
        weights.energy_value_rate * scale,
        weights.gap_logistic_scale_s,
        weights.counterattack_rate_s_per_j * scale,
        weights.counterattack_energy_scale_j / scale,
        weights.initial_advantage_s,
        objective.tail_alpha,
    ]
    values += [s.weight for s in scenarios]
    values += [s.rival_reserve_j / scale for s in scenarios]
    values += [s.rival_pace_gain_s for s in scenarios]
    assert len(values) == 6 * n + n * n + 19 + 3 * len(scenarios)
    return values


def _harvest_bound_j(frame: PlanFrame, index: int) -> float:
    """Harvest bound tightened so the surrogate speed can never leave the corridor.

    Only harvesting lowers the modelled speed, so bounding it is enough; the
    speed floor then holds at every iterate the solver visits rather than only at
    the point it converges to.
    """
    segment = frame.segments[index]
    slack = segment.speed_mps**3 - frame.min_speed_mps**3
    if frame.harvest_opportunity_coefficient <= 0.0 or segment.beta <= 0.0:
        return segment.max_harvest_j
    limit = slack * frame.charge_efficiency / (segment.beta * frame.harvest_opportunity_coefficient)
    return max(0.0, min(segment.max_harvest_j, limit))


def solve_allocation(
    frame: PlanFrame,
    scenarios: tuple[PlanScenario, ...],
    weights: SurrogateWeights,
    objective: ObjectiveManifest,
    config: PlannerConfig,
    *,
    remaining_deadline_s: float,
    warm_start: tuple[tuple[float, ...], tuple[float, ...]] | None = None,
) -> AllocationSolution:
    """Solve one candidate's schedule inside the remaining decision budget.

    ``remaining_deadline_s`` is checked before the solve starts and again on
    return. A solve that overran is reported with ``deadline_exceeded=True`` and
    the planner discards it: a late answer is not an answer. IPOPT's own
    ``max_cpu_time`` is deliberately not set per call, because that option is
    fixed at construction and varying it would rebuild the compiled solver on
    every invocation.
    """
    if not frame.segments:
        raise ValueError("cannot optimise an empty frame")
    if not scenarios:
        raise ValueError("cannot optimise against an empty scenario ensemble")
    if remaining_deadline_s <= 0.0:
        raise SolverDeadlineExpired("no decision budget remained before the solve started")

    ca = _casadi()
    ordered = list(scenarios)
    n = len(frame.segments)
    w = len(ordered)
    scale = ENERGY_SCALE_J
    solver = _solver_for(n, w, config)

    deploy_cap = [segment.max_deploy_j / scale for segment in frame.segments]
    harvest_cap = [_harvest_bound_j(frame, index) / scale for index in range(n)]
    big = max(1.0, abs(frame.energy_ceiling_j) / scale) * 1.0e3
    lbx = [0.0] * n + [0.0] * n + [-big] + [0.0] * w
    ubx = deploy_cap + harvest_cap + [big] + [big] * w

    rows = 2 * n + n + 2 + 2 * (n - 1) + 1 + w
    lbg = [0.0] * rows
    ubg = [float("inf")] * rows

    if warm_start is not None and len(warm_start[0]) == n and len(warm_start[1]) == n:
        start_deploy = [min(max(v / scale, 0.0), deploy_cap[i]) for i, v in enumerate(warm_start[0])]
        start_harvest = [min(max(v / scale, 0.0), harvest_cap[i]) for i, v in enumerate(warm_start[1])]
    else:
        start_deploy = [0.25 * cap for cap in deploy_cap]
        start_harvest = [0.25 * cap for cap in harvest_cap]
    x0 = start_deploy + start_harvest + [0.0] + [0.0] * w

    started = time.perf_counter()
    try:
        result = solver(
            x0=x0,
            p=_pack(frame, ordered, weights, objective),
            lbx=lbx,
            ubx=ubx,
            lbg=lbg,
            ubg=ubg,
        )
    except RuntimeError as exc:  # pragma: no cover - IPOPT internal failure
        raise SolverUnavailable(f"the continuous solve failed: {exc}") from exc
    duration_s = time.perf_counter() - started

    stats = solver.stats()
    status = str(stats.get("return_status", "unknown"))
    iterations = int(stats.get("iter_count", 0) or 0)
    raw = [float(v) for v in ca.DM(result["x"]).full().ravel()]
    deploy = tuple(min(max(0.0, raw[i]), deploy_cap[i]) * scale for i in range(n))
    harvest = tuple(min(max(0.0, raw[n + i]), harvest_cap[i]) * scale for i in range(n))

    losses, corridor_time_s, terminal_energy_j = scenario_losses(frame, ordered, weights, deploy, harvest)
    numeric_losses = tuple(float(value) for value in losses)
    probabilities = [s.weight for s in ordered]
    expected = sum(p * loss for p, loss in zip(probabilities, numeric_losses, strict=True))
    cvar_value, _, _ = cvar(numeric_losses, probabilities, objective.tail_alpha)

    return AllocationSolution(
        deploy_j=deploy,
        harvest_j=harvest,
        eta=raw[2 * n],
        xi=tuple(raw[2 * n + 1 :]),
        scenario_losses=numeric_losses,
        expected_utility=expected,
        cvar_loss=cvar_value,
        corridor_time_s=float(corridor_time_s),
        terminal_energy_j=float(terminal_energy_j),
        objective_value=float(ca.DM(result["f"])),
        solver_status=status,
        iterations=iterations,
        duration_ms=duration_s * 1000.0,
        converged=status in ("Solve_Succeeded", "Solved_To_Acceptable_Level"),
        deadline_exceeded=duration_s > remaining_deadline_s,
    )
