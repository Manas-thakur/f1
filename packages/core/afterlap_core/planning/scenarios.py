"""Weighted rival scenarios and the sampling protocol the planner consumes.

The planner never reaches into a belief filter. It consumes a small structural
protocol, :class:`RivalScenarioView`, so that the estimation module's
``sample_scenarios`` can satisfy it without either module importing the other.
Until that is wired, :func:`scenarios_from_estimate` builds a **deterministic
quadrature** over the belief carried by the ``StateEstimate`` itself.

Two properties matter and are tested:

1. An unobserved rival reserve **widens** the ensemble. It is never collapsed to
   a point value, and it is never replaced by zero. When nothing at all is known
   the nodes span the declared physical battery window and the decision carries
   ``ReasonCode.RIVAL_ENERGY_UNKNOWN``.
2. Sampling is deterministic given ``(estimate, seed)``. Two planner invocations
   on the same estimate compare like for like rather than being re-randomised.

A finite ensemble checks sampled uncertainty only. It is not universal
robustness, and the scenario count is published with every decision.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from afterlap_contracts import ReasonCode, RivalIntention, StateEstimate

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .config import PlannerConfig

__all__ = [
    "PlanScenario",
    "RivalScenarioView",
    "ScenarioEnsembleView",
    "ScenarioSample",
    "scenarios_from_estimate",
    "scenarios_from_views",
]


@runtime_checkable
class RivalScenarioView(Protocol):
    """One weighted rival future, as the planner needs to read it.

    ``afterlap_core.estimation.scenarios.ScenarioTrajectory`` satisfies this
    structurally; the planner does not import it.

    ``energy_j``, ``speed_offset_mps`` and ``modes`` are aligned sequences of the
    same length as ``times_s``, with index ``0`` at the observation cutoff and
    index ``-1`` at the end of the sampled horizon. Energies are **battery**
    joules; a speed offset is metres per second relative to the reference pace.
    """

    @property
    def scenario_id(self) -> str: ...

    @property
    def weight(self) -> float: ...

    @property
    def times_s(self) -> Sequence[float]: ...

    @property
    def energy_j(self) -> Sequence[float]: ...

    @property
    def speed_offset_mps(self) -> Sequence[float]: ...

    @property
    def modes(self) -> Sequence[RivalIntention]: ...


@runtime_checkable
class ScenarioEnsembleView(Protocol):
    """A bundle of weighted futures for one rival."""

    @property
    def car_id(self) -> str: ...

    @property
    def trajectories(self) -> Sequence[RivalScenarioView]: ...

    @property
    def horizon_s(self) -> float: ...

    @property
    def step_s(self) -> float: ...


@dataclass(frozen=True, slots=True)
class PlanScenario:
    """One weighted opponent hypothesis, in the terms the optimiser uses.

    ``rival_reserve_j`` is the rival's stored **battery** energy available for a
    counterattack at the end of the detailed horizon. ``rival_pace_gain_s`` is
    the time it gains over the corridor from its intention alone, before any
    counterattack response to our reserve.
    """

    scenario_id: str
    weight: float
    rival_reserve_j: float
    rival_pace_gain_s: float
    intention: RivalIntention
    energy_known: bool
    source: str

    def __post_init__(self) -> None:
        if self.weight < 0.0:
            raise ValueError("a scenario weight cannot be negative")
        if self.rival_reserve_j < 0.0:
            raise ValueError("a rival reserve cannot be negative; unknown is widened, never zeroed")


@dataclass(frozen=True, slots=True)
class ScenarioSample:
    """The ensemble the planner actually used, plus how it was obtained."""

    scenarios: tuple[PlanScenario, ...]
    reason_codes: tuple[ReasonCode, ...]
    source: str
    energy_spread_j: float
    """Weighted standard deviation of ``rival_reserve_j``. Widening is visible here."""
    energy_support: str = ""
    """How the rival-energy nodes were derived, including any coverage widening.

    Recorded so a decision record can never present a widened optimistic
    interval as if it were a calibrated bound.
    """

    @property
    def weights(self) -> tuple[float, ...]:
        return tuple(s.weight for s in self.scenarios)

    @property
    def count(self) -> int:
        return len(self.scenarios)


def _normalise(scenarios: list[PlanScenario]) -> tuple[PlanScenario, ...]:
    total = sum(s.weight for s in scenarios)
    if total <= 0.0:
        raise ValueError("scenario weights must sum to a positive number")
    return tuple(
        PlanScenario(
            scenario_id=s.scenario_id,
            weight=s.weight / total,
            rival_reserve_j=s.rival_reserve_j,
            rival_pace_gain_s=s.rival_pace_gain_s,
            intention=s.intention,
            energy_known=s.energy_known,
            source=s.source,
        )
        for s in scenarios
    )


def _spread(scenarios: Sequence[PlanScenario]) -> float:
    total = sum(s.weight for s in scenarios)
    if total <= 0.0:
        return 0.0
    mean = sum(s.weight * s.rival_reserve_j for s in scenarios) / total
    variance = sum(s.weight * (s.rival_reserve_j - mean) ** 2 for s in scenarios) / total
    return float(variance**0.5)


def _energy_nodes(
    estimate: StateEstimate,
    config: PlannerConfig,
    battery_max_j: float,
) -> tuple[list[float], bool, tuple[ReasonCode, ...], str]:
    """Quadrature nodes for the rival's stored energy, and how they were derived.

    Three cases, in decreasing order of information, each strictly wider than the
    one above it:

    * a mean with a standard deviation — nodes at the configured quantiles of a
      normal belief;
    * only an interval — nodes at the configured quantiles of the interval,
      **widened** by ``interval_coverage_widening``. The estimation module labels
      its rival-energy interval 90 % and measures 0.7885 coverage
      (``handoffs/A05.md``), so the interval is treated as optimistic at its own
      label. The widening is a conservative margin, not a correction: A05
      attributes the shortfall to bias, and the disclosed coverage of the
      underlying belief is unchanged by anything done here;
    * nothing — nodes spanning the declared physical battery window, which is
      the widest thing that can honestly be said, plus
      ``ReasonCode.RIVAL_ENERGY_UNKNOWN``.

    A ``physical_bounds`` interval is a support, not a statistical statement, so
    it is used as given and never widened past the physics.
    """
    settings = config.scenarios
    quantiles = settings.energy_quantiles
    rival = estimate.nearest_ahead or estimate.nearest_behind
    if rival is None:
        return [], True, (), "no rival in contention"

    mean = rival.energy_mean_j
    if mean is not None and mean.value is not None and mean.standard_deviation:
        centre = float(mean.value)
        sigma = float(mean.standard_deviation)
        offsets = [_normal_quantile(q) for q in quantiles]
        return (
            [max(0.0, centre + o * sigma) for o in offsets],
            True,
            (),
            f"normal belief, mean {centre:.0f} J, sigma {sigma:.0f} J",
        )

    interval = rival.energy_interval_j
    if interval is not None and interval.lower is not None and interval.upper is not None:
        low, high = float(interval.lower), float(interval.upper)
        statistical = interval.kind in ("quantile", "confidence_interval")
        if not statistical:
            return (
                [low + q * (high - low) for q in quantiles],
                False,
                (ReasonCode.RIVAL_ENERGY_UNKNOWN,),
                f"{interval.kind} range {low:.0f}-{high:.0f} J; the reserve is not identified",
            )
        widening = float(settings.interval_coverage_widening.value)
        centre = 0.5 * (low + high)
        half = 0.5 * (high - low) * widening
        low, high = max(0.0, centre - half), min(battery_max_j, centre + half)
        label = (
            f"{interval.kind} interval"
            + (f" labelled {interval.coverage:.2f} coverage" if interval.coverage else "")
            + f", half-width widened by {widening:.2f} (measured coverage is below the label)"
        )
        return [low + q * (high - low) for q in quantiles], True, (), label

    widening = settings.unknown_energy_widening
    low = 0.0
    high = battery_max_j * widening
    return (
        [low + q * (high - low) for q in quantiles],
        False,
        (ReasonCode.RIVAL_ENERGY_UNKNOWN,),
        "unobserved: nodes span the declared physical battery window",
    )


def _normal_quantile(probability: float) -> float:
    """Standard-normal inverse CDF (Acklam's rational approximation).

    Accurate to about ``1.15e-9`` in absolute value over ``(0, 1)``, which is far
    tighter than the belief this is applied to. It is here so that a quantile
    node set is a genuine quantile rather than an invented spread.
    """
    if not 0.0 < probability < 1.0:
        raise ValueError("a quantile probability must lie strictly inside (0, 1)")
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00)
    low, high = 0.02425, 1.0 - 0.02425
    if probability < low:
        q = math.sqrt(-2.0 * _log(probability))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if probability > high:
        q = math.sqrt(-2.0 * _log(1.0 - probability))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    q = probability - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    )


def _log(value: float) -> float:
    from math import log

    return log(value)


def _intentions(estimate: StateEstimate, config: PlannerConfig) -> list[tuple[RivalIntention, float]]:
    rival = estimate.nearest_ahead or estimate.nearest_behind
    if rival is None:
        return [(RivalIntention.NORMAL, 1.0)]
    weights = rival.intentions.as_mapping()
    ordered = sorted(weights.items(), key=lambda item: (-item[1], item[0].value))
    kept = ordered[: config.scenarios.max_intentions]
    total = sum(weight for _, weight in kept)
    if total <= 0.0:
        return [(RivalIntention.NORMAL, 1.0)]
    return [(intention, weight / total) for intention, weight in kept]


def scenarios_from_estimate(
    estimate: StateEstimate,
    config: PlannerConfig,
    *,
    battery_max_j: float,
    count: int | None = None,
    seed: int = 0,
) -> ScenarioSample:
    """Deterministic quadrature over the rival belief carried by ``estimate``.

    This is the baseline sampler. It is used whenever no external scenario
    source is supplied, and it stays available afterwards so a learned or
    filtered ensemble can never remove the validated reference.
    """
    limit = count if count is not None else config.budgets.max_scenarios
    nodes, energy_known, reasons, support = _energy_nodes(estimate, config, battery_max_j)
    intentions = _intentions(estimate, config)
    settings = config.scenarios

    if not nodes:
        scenario = PlanScenario(
            scenario_id=f"baseline-no-rival-{seed}",
            weight=1.0,
            rival_reserve_j=0.0,
            rival_pace_gain_s=0.0,
            intention=RivalIntention.NORMAL,
            energy_known=True,
            source="planner-baseline-quadrature",
        )
        return ScenarioSample(
            scenarios=(scenario,),
            reason_codes=reasons,
            source="planner-baseline-quadrature",
            energy_spread_j=0.0,
            energy_support=support,
        )

    built: list[PlanScenario] = []
    for intention, intention_weight in intentions:
        paired = zip(nodes, settings.energy_quantile_weights, strict=True)
        for index, (node, node_weight) in enumerate(paired):
            built.append(
                PlanScenario(
                    scenario_id=f"baseline-{intention.value}-q{index}-{seed}",
                    weight=intention_weight * node_weight,
                    rival_reserve_j=max(0.0, node),
                    rival_pace_gain_s=settings.pace_gain_s(intention),
                    intention=intention,
                    energy_known=energy_known,
                    source="planner-baseline-quadrature",
                )
            )
    built.sort(key=lambda s: (-s.weight, s.scenario_id))
    kept = _normalise(built[:limit])
    return ScenarioSample(
        scenarios=kept,
        reason_codes=reasons,
        source="planner-baseline-quadrature",
        energy_spread_j=_spread(kept),
        energy_support=support,
    )


def scenarios_from_views(
    views: Sequence[RivalScenarioView],
    config: PlannerConfig,
    *,
    count: int | None = None,
    source: str = "estimation-ensemble",
) -> ScenarioSample:
    """Adapt an externally sampled ensemble into the planner's normalised form.

    The terminal element of each trajectory supplies the counterattack reserve;
    the trajectory's final mode supplies the pace bias. Nothing is re-randomised
    here, so a paired experiment that fixes the ensemble fixes the planner input.
    """
    limit = count if count is not None else config.budgets.max_scenarios
    built: list[PlanScenario] = []
    for view in views:
        energies = list(view.energy_j)
        modes = list(view.modes)
        if not energies or not modes:
            raise ValueError(f"scenario {view.scenario_id!r} carries no sampled trajectory")
        intention = modes[-1]
        built.append(
            PlanScenario(
                scenario_id=view.scenario_id,
                weight=float(view.weight),
                rival_reserve_j=max(0.0, float(energies[-1])),
                rival_pace_gain_s=config.scenarios.pace_gain_s(intention),
                intention=intention,
                energy_known=True,
                source=source,
            )
        )
    if not built:
        raise ValueError("an external scenario ensemble must contain at least one trajectory")
    built.sort(key=lambda s: (-s.weight, s.scenario_id))
    kept = _normalise(built[:limit])
    return ScenarioSample(
        scenarios=kept,
        reason_codes=(),
        source=source,
        energy_spread_j=_spread(kept),
        energy_support=(
            "externally sampled trajectories; the terminal energy of each is used as "
            "the counterattack reserve, and its coverage is the sampler's to disclose"
        ),
    )
