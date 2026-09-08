"""Offline scoring of estimator quality against privileged labels.

**This module is evaluation only.** Every field named ``truth_*`` belongs to
data layer 4 of ``MODEL_AND_DATA_SPEC.md`` -- privileged evaluation labels -- and
nothing in :mod:`afterlap_core.estimation.own_car`,
:mod:`afterlap_core.estimation.rivals`,
:mod:`afterlap_core.estimation.scenarios` or
:mod:`afterlap_core.estimation.assembly` imports it. Inference cannot reach these
numbers; scoring reads them after the run.

Splitting
---------

Records are split by **scenario**, never by row. Adjacent physics ticks are
almost the same observation, so a random row split leaks a scenario's answer into
its own held-out set and reports a coverage number that means nothing.
:func:`split_by_scenario` hashes the scenario identifier, so a scenario lands
whole in exactly one part. :func:`split_by_row` exists solely to refuse: it
raises :class:`AdjacentRowSplitError` rather than quietly doing the wrong thing.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from afterlap_contracts import RivalIntention
from afterlap_core.rng import derive_seed

#: Two-sided normal quantile for a 90 % interval.
Z_90 = 1.6448536269514722

DEFAULT_SPLIT_NAMES: tuple[str, ...] = ("training", "tuning", "calibration", "final_test")
DEFAULT_SPLIT_FRACTIONS: tuple[float, ...] = (0.5, 0.2, 0.15, 0.15)


class AdjacentRowSplitError(RuntimeError):
    """Raised when someone tries to split evaluation data by row."""


@dataclass(frozen=True, slots=True)
class CalibrationRecord:
    """One scored instant. Truth fields are privileged labels, never features."""

    scenario_id: str
    session_time_s: float
    predicted_speed_mps: float | None = None
    predicted_speed_sigma: float | None = None
    truth_speed_mps: float | None = None
    predicted_progress_m: float | None = None
    predicted_progress_sigma: float | None = None
    truth_progress_m: float | None = None
    predicted_energy_j: float | None = None
    predicted_energy_sigma: float | None = None
    truth_energy_j: float | None = None
    energy_interval_j: tuple[float, float] | None = None
    energy_interval_coverage: float | None = None
    intention_weights: Mapping[RivalIntention, float] | None = None
    truth_intention: RivalIntention | None = None
    energy_truth_is_legitimate: bool = True

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("every calibration record needs a scenario identifier")
        if self.energy_interval_j is not None:
            lower, upper = self.energy_interval_j
            if lower > upper:
                raise ValueError("energy interval lower bound exceeds its upper bound")


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    """One bin of the behaviour-classification reliability diagram."""

    lower: float
    upper: float
    count: int
    mean_predicted: float
    empirical_frequency: float


@dataclass(frozen=True, slots=True)
class CoverageResult:
    """Empirical coverage of an interval with its nominal target."""

    nominal: float
    empirical: float | None
    covered: int
    total: int

    @property
    def gap(self) -> float | None:
        return None if self.empirical is None else self.empirical - self.nominal


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    """Measured estimator quality on one split.

    Every figure carries its own sample count. A metric with no supporting
    samples is ``None``, never zero.
    """

    split_name: str
    scenario_count: int
    record_count: int
    speed_rmse_mps: float | None = None
    speed_sample_count: int = 0
    progress_rmse_m: float | None = None
    progress_sample_count: int = 0
    energy_rmse_j: float | None = None
    energy_mae_j: float | None = None
    energy_sample_count: int = 0
    energy_truth_withheld_count: int = 0
    speed_interval_coverage: CoverageResult | None = None
    progress_interval_coverage: CoverageResult | None = None
    energy_interval_coverage: CoverageResult | None = None
    rival_energy_interval_coverage: CoverageResult | None = None
    mean_normalised_innovation_squared: float | None = None
    behaviour_brier_score: float | None = None
    behaviour_sample_count: int = 0
    behaviour_reliability: tuple[ReliabilityBin, ...] = ()
    behaviour_minimum_true_class_weight: float | None = None
    per_scenario: Mapping[str, float] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def as_lines(self) -> tuple[str, ...]:
        """Human-readable summary for a handoff or a report artefact."""
        lines = [
            f"split={self.split_name} scenarios={self.scenario_count} records={self.record_count}",
        ]
        if self.speed_rmse_mps is not None:
            lines.append(f"speed RMSE = {self.speed_rmse_mps:.4f} m/s (n={self.speed_sample_count})")
        if self.progress_rmse_m is not None:
            lines.append(f"progress RMSE = {self.progress_rmse_m:.4f} m (n={self.progress_sample_count})")
        if self.energy_rmse_j is not None:
            lines.append(
                f"energy RMSE = {self.energy_rmse_j:.1f} J, MAE = {self.energy_mae_j:.1f} J "
                f"(n={self.energy_sample_count})"
            )
        elif self.energy_truth_withheld_count:
            lines.append(
                f"energy error unavailable: {self.energy_truth_withheld_count} record(s) had no "
                "legitimate energy truth"
            )
        for label, coverage in (
            ("speed", self.speed_interval_coverage),
            ("progress", self.progress_interval_coverage),
            ("own energy", self.energy_interval_coverage),
            ("rival energy", self.rival_energy_interval_coverage),
        ):
            if coverage is not None and coverage.empirical is not None:
                lines.append(
                    f"{label} {coverage.nominal:.0%} interval empirical coverage = "
                    f"{coverage.empirical:.4f} ({coverage.covered}/{coverage.total})"
                )
        if self.mean_normalised_innovation_squared is not None:
            lines.append(f"mean NIS = {self.mean_normalised_innovation_squared:.4f} (target 1.0)")
        if self.behaviour_brier_score is not None:
            lines.append(
                f"behaviour Brier = {self.behaviour_brier_score:.4f} (n={self.behaviour_sample_count}), "
                f"minimum true-class weight = {self.behaviour_minimum_true_class_weight:.4f}"
            )
        return tuple(lines)


def scenario_ids(records: Iterable[CalibrationRecord]) -> tuple[str, ...]:
    return tuple(sorted({record.scenario_id for record in records}))


def split_by_scenario(
    records: Sequence[CalibrationRecord],
    *,
    fractions: Sequence[float] = DEFAULT_SPLIT_FRACTIONS,
    names: Sequence[str] = DEFAULT_SPLIT_NAMES,
    seed: int = 0,
) -> dict[str, tuple[CalibrationRecord, ...]]:
    """Assign whole scenarios to disjoint parts.

    The part is a deterministic function of the scenario identifier and the seed,
    so the same scenario always lands in the same part and no record from a
    scenario can appear in two parts.
    """
    if len(fractions) != len(names):
        raise ValueError("split fractions and names must have the same length")
    if any(f < 0.0 for f in fractions):
        raise ValueError("split fractions cannot be negative")
    total = sum(fractions)
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"split fractions must sum to 1.0, got {total!r}")
    boundaries: list[float] = []
    running = 0.0
    for fraction in fractions:
        running += fraction
        boundaries.append(running)
    parts: dict[str, list[CalibrationRecord]] = {name: [] for name in names}
    for record in records:
        draw = (derive_seed(seed, "scenario-split", record.scenario_id) % 10_000_000) / 10_000_000.0
        for name, boundary in zip(names, boundaries, strict=True):
            if draw < boundary:
                parts[name].append(record)
                break
        else:  # pragma: no cover - float guard
            parts[names[-1]].append(record)
    return {name: tuple(items) for name, items in parts.items()}


def split_by_row(*_args: object, **_kwargs: object) -> None:
    """Refuse to split evaluation data by row.

    Adjacent physics ticks are near-duplicates. A row split puts a scenario on
    both sides of the boundary, and every held-out number computed afterwards --
    RMSE, coverage, calibration -- is optimistic by an unknown amount. Use
    :func:`split_by_scenario`.
    """
    raise AdjacentRowSplitError(
        "evaluation data must be split by scenario, not by row: adjacent rows are "
        "near-duplicates and a row split leaks a scenario into its own held-out set. "
        "Use split_by_scenario()."
    )


def _rmse(errors: Sequence[float]) -> float | None:
    if not errors:
        return None
    return math.sqrt(sum(e * e for e in errors) / len(errors))


def _coverage(hits: int, total: int, nominal: float) -> CoverageResult:
    empirical = None if total == 0 else hits / total
    return CoverageResult(nominal=nominal, empirical=empirical, covered=hits, total=total)


def evaluate(
    records: Sequence[CalibrationRecord],
    *,
    split_name: str = "unnamed",
    nominal_coverage: float = 0.9,
    reliability_bins: int = 5,
) -> CalibrationReport:
    """Score one split. Reported numbers are measured, never assumed."""
    if not 0.0 < nominal_coverage < 1.0:
        raise ValueError("nominal coverage must lie strictly between 0 and 1")
    z = _normal_quantile(0.5 + nominal_coverage / 2.0)

    speed_errors: list[float] = []
    progress_errors: list[float] = []
    energy_errors: list[float] = []
    nis_values: list[float] = []
    withheld = 0
    speed_hits = speed_total = 0
    progress_hits = progress_total = 0
    energy_hits = energy_total = 0
    rival_hits = rival_total = 0
    brier: list[float] = []
    true_class_weights: list[float] = []
    per_scenario_speed: dict[str, list[float]] = {}

    for record in records:
        if record.predicted_speed_mps is not None and record.truth_speed_mps is not None:
            error = record.predicted_speed_mps - record.truth_speed_mps
            speed_errors.append(error)
            per_scenario_speed.setdefault(record.scenario_id, []).append(error)
            if record.predicted_speed_sigma:
                nis_values.append((error / record.predicted_speed_sigma) ** 2)
                speed_total += 1
                if abs(error) <= z * record.predicted_speed_sigma:
                    speed_hits += 1
        if record.predicted_progress_m is not None and record.truth_progress_m is not None:
            error = record.predicted_progress_m - record.truth_progress_m
            progress_errors.append(error)
            if record.predicted_progress_sigma:
                progress_total += 1
                if abs(error) <= z * record.predicted_progress_sigma:
                    progress_hits += 1
        if record.truth_energy_j is not None and not record.energy_truth_is_legitimate:
            withheld += 1
        elif record.predicted_energy_j is not None and record.truth_energy_j is not None:
            error = record.predicted_energy_j - record.truth_energy_j
            energy_errors.append(error)
            if record.predicted_energy_sigma:
                energy_total += 1
                if abs(error) <= z * record.predicted_energy_sigma:
                    energy_hits += 1
        elif record.truth_energy_j is None and record.predicted_energy_j is not None:
            withheld += 1
        if (
            record.energy_interval_j is not None
            and record.truth_energy_j is not None
            and record.energy_truth_is_legitimate
        ):
            lower, upper = record.energy_interval_j
            rival_total += 1
            if lower <= record.truth_energy_j <= upper:
                rival_hits += 1
        if record.intention_weights is not None and record.truth_intention is not None:
            weights = {mode: float(record.intention_weights.get(mode, 0.0)) for mode in RivalIntention}
            score = sum(
                (weight - (1.0 if mode is record.truth_intention else 0.0)) ** 2
                for mode, weight in weights.items()
            )
            brier.append(score)
            true_class_weights.append(weights[record.truth_intention])

    report = CalibrationReport(
        split_name=split_name,
        scenario_count=len(scenario_ids(records)),
        record_count=len(records),
        speed_rmse_mps=_rmse(speed_errors),
        speed_sample_count=len(speed_errors),
        progress_rmse_m=_rmse(progress_errors),
        progress_sample_count=len(progress_errors),
        energy_rmse_j=_rmse(energy_errors),
        energy_mae_j=(None if not energy_errors else sum(abs(e) for e in energy_errors) / len(energy_errors)),
        energy_sample_count=len(energy_errors),
        energy_truth_withheld_count=withheld,
        speed_interval_coverage=_coverage(speed_hits, speed_total, nominal_coverage),
        progress_interval_coverage=_coverage(progress_hits, progress_total, nominal_coverage),
        energy_interval_coverage=_coverage(energy_hits, energy_total, nominal_coverage),
        rival_energy_interval_coverage=_coverage(rival_hits, rival_total, nominal_coverage),
        mean_normalised_innovation_squared=(None if not nis_values else sum(nis_values) / len(nis_values)),
        behaviour_brier_score=None if not brier else sum(brier) / len(brier),
        behaviour_sample_count=len(brier),
        behaviour_reliability=_reliability(records, reliability_bins),
        behaviour_minimum_true_class_weight=(None if not true_class_weights else min(true_class_weights)),
        per_scenario={
            scenario: math.sqrt(sum(e * e for e in errors) / len(errors))
            for scenario, errors in sorted(per_scenario_speed.items())
        },
        notes=("Split by scenario. Energy error is reported only where a legitimate label exists.",),
    )
    return report


def _reliability(records: Sequence[CalibrationRecord], bins: int) -> tuple[ReliabilityBin, ...]:
    """Reliability diagram of the weight assigned to the true intention."""
    if bins <= 0:
        raise ValueError("reliability bins must be positive")
    buckets: list[list[tuple[float, float]]] = [[] for _ in range(bins)]
    for record in records:
        if record.intention_weights is None or record.truth_intention is None:
            continue
        for mode in RivalIntention:
            predicted = float(record.intention_weights.get(mode, 0.0))
            outcome = 1.0 if mode is record.truth_intention else 0.0
            index = min(bins - 1, int(predicted * bins))
            buckets[index].append((predicted, outcome))
    result: list[ReliabilityBin] = []
    for index, bucket in enumerate(buckets):
        lower = index / bins
        upper = (index + 1) / bins
        if not bucket:
            result.append(
                ReliabilityBin(
                    lower=lower, upper=upper, count=0, mean_predicted=math.nan, empirical_frequency=math.nan
                )
            )
            continue
        mean_predicted = sum(p for p, _ in bucket) / len(bucket)
        frequency = sum(o for _, o in bucket) / len(bucket)
        result.append(
            ReliabilityBin(
                lower=lower,
                upper=upper,
                count=len(bucket),
                mean_predicted=mean_predicted,
                empirical_frequency=frequency,
            )
        )
    return tuple(result)


def _normal_quantile(probability: float) -> float:
    """Inverse standard normal CDF via bisection on ``erf``.

    Bisection rather than a rational approximation because the tolerance is then
    explicit and the function has no magic constants to get wrong.
    """
    if not 0.0 < probability < 1.0:
        raise ValueError("probability must lie strictly between 0 and 1")
    low, high = -12.0, 12.0
    for _ in range(200):
        middle = 0.5 * (low + high)
        cdf = 0.5 * (1.0 + math.erf(middle / math.sqrt(2.0)))
        if cdf < probability:
            low = middle
        else:
            high = middle
    return 0.5 * (low + high)


__all__ = [
    "DEFAULT_SPLIT_FRACTIONS",
    "DEFAULT_SPLIT_NAMES",
    "Z_90",
    "AdjacentRowSplitError",
    "CalibrationRecord",
    "CalibrationReport",
    "CoverageResult",
    "ReliabilityBin",
    "evaluate",
    "scenario_ids",
    "split_by_row",
    "split_by_scenario",
]
