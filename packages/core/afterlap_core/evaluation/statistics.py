"""Hierarchical paired bootstrap, distribution summaries and calibration.

Two rules from ``learning/SERVING_AND_EVALUATION.md`` shape this module and
are enforced structurally rather than by convention:

1. **Correlated telemetry frames are not independent trials.** The resampler
   accepts :class:`EvaluationUnit` values only. One unit is one
   ``(scenario, seed)`` episode. A :class:`TelemetryFrameSeries` — many frames
   from a single episode — is a distinct type that the resampler *refuses*; to
   use it you must first state a reduction, which produces one unit. There is
   no argument that makes the bootstrap treat frames as units.

2. **Pairing is preserved.** A unit carries every controller's value for the
   same episode, so a resampled unit always moves both arms of the comparison
   together. There is no code path that resamples one controller's values
   independently of another's.

Calibration follows the same discipline: a set with only positive labels or only
negative labels cannot establish reliability, so it is reported as
:data:`~afterlap_contracts.CalibrationStatus.UNAVAILABLE` with its support
count, never scored.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from afterlap_contracts import BenchmarkComparison, CalibrationReport, CalibrationStatus

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = [
    "BootstrapResult",
    "CalibrationAssessment",
    "CorrelatedSampleError",
    "DistributionSummary",
    "EvaluationUnit",
    "MetricDirection",
    "PairedSample",
    "TelemetryFrameSeries",
    "assess_calibration",
    "brier_score",
    "hierarchical_paired_bootstrap",
    "log_loss",
    "reliability_bins",
    "summarise",
]


class CorrelatedSampleError(ValueError):
    """Raised when correlated observations would be resampled as independent."""


@dataclass(frozen=True, slots=True)
class MetricDirection:
    """Which way is better for one metric, stated once and carried around."""

    metric: str
    unit: str
    higher_is_better: bool

    @property
    def sign(self) -> float:
        return 1.0 if self.higher_is_better else -1.0


ELAPSED_TIME = MetricDirection("elapsed_time_s", "s", higher_is_better=False)
UTILITY = MetricDirection("utility", "1", higher_is_better=True)
ENERGY_AT_CHECKPOINT = MetricDirection("energy_at_checkpoint_j", "J", higher_is_better=True)
FINISH_POSITION = MetricDirection("finish_position", "position", higher_is_better=False)


@dataclass(frozen=True, slots=True)
class TelemetryFrameSeries:
    """Many correlated observations from **one** episode.

    This exists so that correlated data has somewhere honest to live, and so
    that handing it to the resampler is a type error rather than a silent
    inflation of the sample size. Call :meth:`reduce` to state how the episode
    collapses to a single value.
    """

    scenario_id: str
    seed: int
    controller: str
    values: tuple[float, ...]

    def reduce(self, reducer: Callable[[Sequence[float]], float]) -> float:
        """Collapse the episode to one number using an explicit reduction."""
        if not self.values:
            raise ValueError("cannot reduce an empty frame series")
        return float(reducer(self.values))


@dataclass(frozen=True, slots=True)
class EvaluationUnit:
    """One independent trial: a scenario evaluated under one seed.

    ``values`` maps a controller name to that controller's outcome for **this**
    episode, which is what makes the comparison paired. ``missing`` names the
    controllers that produced no value here (a withdrawal, a timeout or an
    unmerged row); they stay visible instead of being dropped.
    """

    scenario_id: str
    seed: int
    family: str
    values: Mapping[str, float]
    missing: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[str, int]:
        return (self.scenario_id, self.seed)

    @classmethod
    def from_frame_series(
        cls,
        *,
        scenario_id: str,
        seed: int,
        family: str,
        series: Mapping[str, TelemetryFrameSeries],
        reducer: Callable[[Sequence[float]], float],
        missing: Sequence[str] = (),
    ) -> EvaluationUnit:
        """Build one unit from per-controller frame series and a stated reduction."""
        for controller, item in series.items():
            if item.scenario_id != scenario_id or item.seed != seed:
                raise CorrelatedSampleError(
                    f"frame series for {controller} belongs to "
                    f"({item.scenario_id}, {item.seed}), not ({scenario_id}, {seed})"
                )
        return cls(
            scenario_id=scenario_id,
            seed=seed,
            family=family,
            values={name: item.reduce(reducer) for name, item in series.items()},
            missing=tuple(missing),
        )


@dataclass(frozen=True, slots=True)
class PairedSample:
    """A validated collection of independent units for one metric."""

    metric: MetricDirection
    units: tuple[EvaluationUnit, ...]

    def __post_init__(self) -> None:
        seen: set[tuple[str, int]] = set()
        for unit in self.units:
            if not isinstance(unit, EvaluationUnit):  # pragma: no cover - type guard
                raise CorrelatedSampleError(
                    "a paired sample holds EvaluationUnit values only; reduce correlated "
                    "telemetry frames to one value per episode first"
                )
            if unit.key in seen:
                raise CorrelatedSampleError(
                    f"scenario {unit.scenario_id} seed {unit.seed} appears more than once. "
                    "Repeated observations of one episode are correlated and must be reduced "
                    "to a single unit before resampling."
                )
            seen.add(unit.key)

    @property
    def scenario_ids(self) -> tuple[str, ...]:
        return tuple(sorted({unit.scenario_id for unit in self.units}))

    @property
    def seed_count(self) -> int:
        return len({unit.seed for unit in self.units})

    def units_by_scenario(self) -> dict[str, tuple[EvaluationUnit, ...]]:
        grouped: dict[str, list[EvaluationUnit]] = {}
        for unit in self.units:
            grouped.setdefault(unit.scenario_id, []).append(unit)
        return {key: tuple(value) for key, value in sorted(grouped.items())}

    def paired_differences(self, controller: str, reference: str) -> tuple[float, ...]:
        """Per-unit ``controller - reference``, over units where both are present."""
        return tuple(
            unit.values[controller] - unit.values[reference]
            for unit in self.units
            if controller in unit.values and reference in unit.values
        )

    def for_family(self, family: str) -> PairedSample:
        return PairedSample(metric=self.metric, units=tuple(u for u in self.units if u.family == family))


@dataclass(frozen=True, slots=True)
class DistributionSummary:
    """The distribution, not only its mean."""

    count: int
    mean: float
    std: float
    minimum: float
    q05: float
    median: float
    q95: float
    maximum: float
    poor_tail_mean: float
    poor_tail_alpha: float
    worst_cases: tuple[tuple[str, int, float], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "mean": self.mean,
            "std": self.std,
            "minimum": self.minimum,
            "q05": self.q05,
            "median": self.median,
            "q95": self.q95,
            "maximum": self.maximum,
            "poor_tail_mean": self.poor_tail_mean,
            "poor_tail_alpha": self.poor_tail_alpha,
            "worst_cases": [
                {"scenario_id": s, "seed": seed, "value": value} for s, seed, value in self.worst_cases
            ],
        }


def summarise(
    sample: PairedSample,
    controller: str,
    reference: str,
    *,
    alpha: float = 0.9,
    worst_k: int = 5,
) -> DistributionSummary:
    """Summarise the paired differences, including the poor tail.

    ``poor_tail_mean`` is the mean of the worst ``1 - alpha`` fraction of units,
    where "worst" is decided by the metric's declared direction. Reporting only
    the mean improvement is what ``TECHNICAL_SPEC.md`` forbids.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must lie in (0, 1)")
    pairs = [
        (unit.scenario_id, unit.seed, unit.values[controller] - unit.values[reference])
        for unit in sample.units
        if controller in unit.values and reference in unit.values
    ]
    if not pairs:
        raise ValueError(f"no unit carries both {controller!r} and {reference!r}")
    values = np.asarray([item[2] for item in pairs], dtype=np.float64)
    sign = sample.metric.sign
    oriented = sign * values
    tail_count = max(1, math.ceil((1.0 - alpha) * values.size))
    worst_indices = np.argsort(oriented)[:tail_count]
    ranking = sorted(pairs, key=lambda item: sign * item[2])
    return DistributionSummary(
        count=int(values.size),
        mean=float(values.mean()),
        std=float(values.std(ddof=1)) if values.size > 1 else 0.0,
        minimum=float(values.min()),
        q05=float(np.quantile(values, 0.05)),
        median=float(np.median(values)),
        q95=float(np.quantile(values, 0.95)),
        maximum=float(values.max()),
        poor_tail_mean=float(values[worst_indices].mean()),
        poor_tail_alpha=alpha,
        worst_cases=tuple(ranking[:worst_k]),
    )


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """A paired bootstrap estimate with everything needed to audit it."""

    controller: str
    reference: str
    metric: MetricDirection
    difference_mean: float
    ci_low: float
    ci_high: float
    coverage: float
    iterations: int
    scenario_count: int
    seed_count: int
    unit_count: int
    interval_excludes_zero: bool
    favours_controller: bool
    interval_widened_to_contain_estimate: bool
    within_scenario_variance: float
    degenerate_seed_variance: bool
    """True when every seed inside every scenario produced the same paired
    difference. The seed level of the hierarchy then contributes no variation,
    and the interval reflects the scenario population alone. This is a property
    of the *fixtures*, not of the estimator, and it must be reported: a package
    with no exogenous disturbance producer will look far more certain than it
    has earned."""

    distribution: DistributionSummary

    def to_contract(self) -> BenchmarkComparison:
        """The frozen contract record for this comparison."""
        return BenchmarkComparison(
            controller=self.controller,
            reference=self.reference,
            metric=self.metric.metric,
            unit=self.metric.unit,
            difference_mean=self.difference_mean,
            ci_low=self.ci_low,
            ci_high=self.ci_high,
            coverage=self.coverage,
            scenario_count=self.scenario_count,
            seed_count=self.seed_count,
            favours_controller=self.favours_controller,
        )


def hierarchical_paired_bootstrap(
    sample: PairedSample | Sequence[Any],
    controller: str,
    reference: str,
    *,
    iterations: int = 4000,
    coverage: float = 0.95,
    seed: int = 20260908,
    alpha: float = 0.9,
) -> BootstrapResult:
    """Resample scenarios, then seeds within scenarios, preserving pairing.

    The two-level resample reflects the two independent sources of variation the
    plan names — the scenario population and the training seed — and it never
    resamples anything finer. Passing a raw sequence of anything other than a
    validated :class:`PairedSample` is refused, because that is the shape a
    caller reaches for when they are about to resample telemetry frames.
    """
    if not isinstance(sample, PairedSample):
        raise CorrelatedSampleError(
            "hierarchical_paired_bootstrap takes a PairedSample of EvaluationUnit values. "
            "A bare sequence of observations cannot be shown to be independent, and "
            "resampling correlated telemetry frames as trials inflates the sample size."
        )
    if not 0.0 < coverage < 1.0:
        raise ValueError("coverage must lie in (0, 1)")
    if iterations < 1:
        raise ValueError("the bootstrap needs at least one iteration")

    grouped = {
        scenario: tuple(unit for unit in units if controller in unit.values and reference in unit.values)
        for scenario, units in sample.units_by_scenario().items()
    }
    grouped = {scenario: units for scenario, units in grouped.items() if units}
    if not grouped:
        raise ValueError(f"no unit carries both {controller!r} and {reference!r}")

    scenarios = tuple(grouped)
    differences = {
        scenario: np.asarray(
            [unit.values[controller] - unit.values[reference] for unit in units], dtype=np.float64
        )
        for scenario, units in grouped.items()
    }
    all_values = np.concatenate([differences[s] for s in scenarios])
    point_estimate = float(all_values.mean())

    rng = np.random.default_rng(seed)
    replicates = np.empty(iterations, dtype=np.float64)
    scenario_count = len(scenarios)
    for index in range(iterations):
        drawn = rng.integers(0, scenario_count, size=scenario_count)
        pieces: list[np.ndarray] = []
        for position in drawn:
            values = differences[scenarios[position]]
            picks = rng.integers(0, values.size, size=values.size)
            pieces.append(values[picks])
        replicates[index] = float(np.concatenate(pieces).mean())

    tail = 0.5 * (1.0 - coverage)
    raw_low = float(np.quantile(replicates, tail))
    raw_high = float(np.quantile(replicates, 1.0 - tail))
    low = min(raw_low, point_estimate)
    high = max(raw_high, point_estimate)
    widened = (low, high) != (raw_low, raw_high)

    sign = sample.metric.sign
    excludes_zero = low > 0.0 or high < 0.0
    favours = excludes_zero and (sign * point_estimate > 0.0)

    within = [float(values.var()) for values in differences.values() if values.size > 1]
    within_variance = float(np.mean(within)) if within else 0.0
    degenerate = bool(within) and within_variance == 0.0

    return BootstrapResult(
        controller=controller,
        reference=reference,
        metric=sample.metric,
        difference_mean=point_estimate,
        ci_low=low,
        ci_high=high,
        coverage=coverage,
        iterations=iterations,
        scenario_count=scenario_count,
        seed_count=len({unit.seed for units in grouped.values() for unit in units}),
        unit_count=int(all_values.size),
        interval_excludes_zero=excludes_zero,
        favours_controller=favours,
        interval_widened_to_contain_estimate=widened,
        within_scenario_variance=within_variance,
        degenerate_seed_variance=degenerate,
        distribution=summarise(sample, controller, reference, alpha=alpha),
    )


_EPS = 1e-15


def brier_score(predictions: Sequence[float] | np.ndarray, labels: Sequence[int] | np.ndarray) -> float:
    """Mean squared error of a probability forecast against a binary label."""
    p = np.asarray(predictions, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64)
    if p.size != y.size:
        raise ValueError("predictions and labels must have the same length")
    if p.size == 0:
        raise ValueError("the Brier score is undefined for an empty set")
    return float(np.mean((p - y) ** 2))


def log_loss(predictions: Sequence[float] | np.ndarray, labels: Sequence[int] | np.ndarray) -> float:
    """Binary cross entropy, with the predictions clipped away from 0 and 1."""
    p = np.clip(np.asarray(predictions, dtype=np.float64), _EPS, 1.0 - _EPS)
    y = np.asarray(labels, dtype=np.float64)
    if p.size != y.size:
        raise ValueError("predictions and labels must have the same length")
    if p.size == 0:
        raise ValueError("the log loss is undefined for an empty set")
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def reliability_bins(
    predictions: Sequence[float] | np.ndarray,
    labels: Sequence[int] | np.ndarray,
    *,
    bins: int = 10,
) -> tuple[tuple[int, ...], tuple[float, ...], tuple[float, ...]]:
    """Equal-width reliability bins. Empty bins are omitted, never zero-filled."""
    if bins < 1:
        raise ValueError("a reliability diagram needs at least one bin")
    p = np.asarray(predictions, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64)
    edges = np.linspace(0.0, 1.0, bins + 1)
    index = np.clip(np.digitize(p, edges[1:-1], right=False), 0, bins - 1)
    counts: list[int] = []
    predicted: list[float] = []
    observed: list[float] = []
    for bucket in range(bins):
        mask = index == bucket
        size = int(mask.sum())
        if size == 0:
            continue
        counts.append(size)
        predicted.append(float(p[mask].mean()))
        observed.append(float(y[mask].mean()))
    return tuple(counts), tuple(predicted), tuple(observed)


@dataclass(frozen=True, slots=True)
class CalibrationAssessment:
    """A calibration verdict plus the reason when it could not be scored."""

    report: CalibrationReport
    sufficient: bool
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_definition": self.report.event_definition,
            "status": self.report.status.value,
            "brier_score": self.report.brier_score,
            "log_loss": self.report.log_loss,
            "support_count": self.report.support_count,
            "sufficient": self.sufficient,
            "reason": self.reason,
        }


def assess_calibration(
    predictions: Sequence[float] | np.ndarray,
    labels: Sequence[int] | np.ndarray,
    *,
    event_definition: str,
    bins: int = 10,
    min_support: int = 10,
    max_reliability_gap: float = 0.1,
) -> CalibrationAssessment:
    """Score a probability forecast, or explain why it cannot be scored.

    A set with only positives or only negatives carries no information about
    reliability: every threshold separates it perfectly and the Brier score
    measures only the forecaster's average level. Such a set is reported as
    ``UNAVAILABLE`` with its support count and a stated reason, and no number is
    emitted for it.

    When the set *is* scorable the verdict still depends on the evidence: the
    largest gap between predicted and observed frequency across the populated
    bins must stay within ``max_reliability_gap`` for the status to be
    ``CALIBRATED``. Otherwise the scores are reported under ``UNCALIBRATED``,
    which is a result, not a failure to produce one.
    """
    p = np.asarray(predictions, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64)
    if p.size != y.size:
        raise ValueError("predictions and labels must have the same length")
    if np.any((p < 0.0) | (p > 1.0)):
        raise ValueError("probabilities must lie in [0, 1]")
    if np.any((y != 0.0) & (y != 1.0)):
        raise ValueError("labels must be binary 0/1")

    support = int(p.size)

    def unavailable(reason: str) -> CalibrationAssessment:
        return CalibrationAssessment(
            report=CalibrationReport(
                event_definition=event_definition,
                status=CalibrationStatus.UNAVAILABLE,
                support_count=support,
            ),
            sufficient=False,
            reason=reason,
        )

    if support == 0:
        return unavailable("no labelled samples")
    positives = int(y.sum())
    if positives == 0:
        return unavailable(
            f"all {support} labels are negative; a single-class set cannot establish reliability"
        )
    if positives == support:
        return unavailable(
            f"all {support} labels are positive; a single-class set cannot establish reliability"
        )
    if support < min_support:
        return unavailable(f"support {support} is below the declared minimum of {min_support}")

    counts, predicted, observed = reliability_bins(p, y, bins=bins)
    gap = max(abs(a - b) for a, b in zip(predicted, observed, strict=True))
    calibrated = gap <= max_reliability_gap
    return CalibrationAssessment(
        report=CalibrationReport(
            event_definition=event_definition,
            status=CalibrationStatus.CALIBRATED if calibrated else CalibrationStatus.UNCALIBRATED,
            brier_score=brier_score(p, y),
            log_loss=log_loss(p, y),
            bin_counts=counts,
            bin_predicted=predicted,
            bin_observed=observed,
            support_count=support,
        ),
        sufficient=True,
        reason=None
        if calibrated
        else f"largest reliability gap {gap:.3f} exceeds the declared limit {max_reliability_gap:.3f}",
    )


__all__ += ["ELAPSED_TIME", "ENERGY_AT_CHECKPOINT", "FINISH_POSITION", "UTILITY"]
