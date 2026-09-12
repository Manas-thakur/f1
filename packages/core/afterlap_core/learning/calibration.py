"""The probability calibrator that did not exist.

``planning/rollout.py`` computes ``pass_before`` and ``ahead_at`` as weighted
scenario frequencies and stamps every one ``calibration_status=uncalibrated``,
with the module docstring stating the reason plainly: *no calibrator exists
yet*. A raw ensemble frequency is a forecast, not a calibrated probability, and
publishing one as the other is the defect that gate was protecting against.

This module is the missing piece. It fits a monotone map from raw ensemble
frequency to observed outcome rate and refuses to produce one when the evidence
cannot support it.

Why isotonic regression
-----------------------

The map is fitted by pool-adjacent-violators, which gives the least-squares
monotone fit with no functional form assumed. Monotonicity is the property that
matters operationally: the planner ranks candidates partly by these
probabilities, and a calibration step that could reorder two forecasts would
change which plan is recommended for reasons unrelated to the evidence. A
logistic (Platt) scaling would also be monotone but would impose a shape the
scenario ensemble has no reason to follow.

What it refuses to do
---------------------

* **It refuses to calibrate a single-class set.** If every observed outcome is a
  pass, or none is, no map can be identified: the fit would collapse to a
  constant and report a perfect Brier score. This is reported as unavailable
  with its support count, reusing the same judgement
  :func:`afterlap_core.evaluation.statistics.assess_calibration` already
  applies.
* **It refuses thin evidence.** Below ``min_support`` labelled samples the fit
  is not published, because a monotone step function through a handful of points
  reproduces them exactly and says nothing about the next one.
* **It does not silently extrapolate.** A raw frequency outside the fitted
  domain is clamped to the nearest fitted end *and flagged as clamped*, so a
  forecast from a regime the calibration set never covered is visible rather
  than confident.
* **It never marks itself frozen.** ``frozen_before_final_test`` is set by the
  operator who freezes it, not by the fit that produced it, exactly as
  ``SupportThresholds`` already works.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np

from afterlap_contracts import CalibrationReport, CalibrationStatus

from ..paths import sha256_json

__all__ = [
    "CALIBRATOR_SCHEMA",
    "CalibratedProbability",
    "CalibrationFit",
    "CalibrationSample",
    "CalibratorStatus",
    "ProbabilityCalibrator",
    "fit_calibrator",
    "isotonic_fit",
]

CALIBRATOR_SCHEMA = "afterlap.learning.calibrator/1"
DEFAULT_MIN_SUPPORT = 30
DEFAULT_BINS = 10


class CalibratorStatus:
    """Why a calibrated probability came out the way it did."""

    CALIBRATED = "calibrated"
    NO_CALIBRATOR = "no_calibrator"
    NOT_FROZEN = "thresholds_not_frozen"
    EVENT_NOT_CALIBRATED = "event_not_calibrated"
    OUT_OF_DOMAIN = "raw_frequency_outside_fitted_domain"
    INSUFFICIENT_SUPPORT = "insufficient_support"
    SINGLE_CLASS = "single_class_calibration_set"
    NON_FINITE = "non_finite_raw_frequency"


@dataclass(frozen=True, slots=True)
class CalibrationSample:
    """One forecast paired with what actually happened.

    ``episode_id`` exists so a split can be taken by episode. Two forecasts from
    the same episode are correlated, and splitting between them would imply an
    independence the data does not have.
    """

    event_definition: str
    raw_frequency: float
    outcome: int
    episode_id: str
    scenario_id: str
    checkpoint_id: str | None = None
    sample_count: int | None = None
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.raw_frequency <= 1.0:
            raise ValueError(f"a raw frequency must lie in [0, 1], got {self.raw_frequency}")
        if self.outcome not in (0, 1):
            raise ValueError(f"an outcome label must be 0 or 1, got {self.outcome}")


@dataclass(frozen=True, slots=True)
class CalibratedProbability:
    """A calibrated probability, or an explicit refusal to produce one.

    ``value`` is ``None`` whenever the calibration could not be applied. It is
    never 0.0 as a stand-in for "unknown".
    """

    value: float | None
    raw_frequency: float
    status: str
    detail: str = ""
    clamped: bool = False
    support_count: int | None = None
    calibrator_id: str | None = None

    @property
    def calibrated(self) -> bool:
        return self.value is not None and self.status == CalibratorStatus.CALIBRATED

    @property
    def contract_status(self) -> CalibrationStatus:
        """What a :class:`ProbabilityStatement` may declare about this value."""
        return CalibrationStatus.CALIBRATED if self.calibrated else CalibrationStatus.UNCALIBRATED

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "raw_frequency": self.raw_frequency,
            "status": self.status,
            "detail": self.detail,
            "clamped": self.clamped,
            "support_count": self.support_count,
            "calibrator_id": self.calibrator_id,
        }


def isotonic_fit(
    x: np.ndarray, y: np.ndarray, weights: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Least-squares monotone non-decreasing fit by pool-adjacent-violators.

    Returns ``(knots_x, knots_y)`` describing a step function, deduplicated so
    the stored map is the minimal one that reproduces the fit. Ties in ``x`` are
    pooled before the sweep, because two identical forecasts must receive the
    same calibrated value.
    """
    order = np.argsort(x, kind="stable")
    xs = np.asarray(x, dtype=np.float64)[order]
    ys = np.asarray(y, dtype=np.float64)[order]
    ws = np.ones_like(xs) if weights is None else np.asarray(weights, dtype=np.float64)[order]
    if np.any(ws <= 0.0):
        raise ValueError("calibration weights must be positive")

    grouped_x: list[float] = []
    grouped_y: list[float] = []
    grouped_w: list[float] = []
    index = 0
    while index < xs.size:
        stop = index
        while stop + 1 < xs.size and xs[stop + 1] == xs[index]:
            stop += 1
        block_w = float(ws[index : stop + 1].sum())
        grouped_x.append(float(xs[index]))
        grouped_y.append(float((ys[index : stop + 1] * ws[index : stop + 1]).sum() / block_w))
        grouped_w.append(block_w)
        index = stop + 1

    values = list(grouped_y)
    counts = list(grouped_w)
    starts = list(range(len(values)))
    position = 0
    while position < len(values) - 1:
        if values[position] <= values[position + 1] + 1e-15:
            position += 1
            continue
        total = counts[position] + counts[position + 1]
        pooled = (values[position] * counts[position] + values[position + 1] * counts[position + 1]) / total
        values[position] = pooled
        counts[position] = total
        del values[position + 1]
        del counts[position + 1]
        del starts[position + 1]
        if position > 0:
            position -= 1

    knots_x: list[float] = []
    knots_y: list[float] = []
    for block, start in enumerate(starts):
        end = starts[block + 1] if block + 1 < len(starts) else len(grouped_x)
        for offset in range(start, end):
            knots_x.append(grouped_x[offset])
            knots_y.append(float(np.clip(values[block], 0.0, 1.0)))

    unique_x: list[float] = []
    unique_y: list[float] = []
    for value_x, value_y in zip(knots_x, knots_y, strict=True):
        if unique_x and value_x == unique_x[-1]:
            unique_y[-1] = value_y
            continue
        unique_x.append(value_x)
        unique_y.append(value_y)
    return np.asarray(unique_x, dtype=np.float64), np.asarray(unique_y, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class _EventMap:
    """The fitted monotone map for one event definition."""

    event_definition: str
    knots_x: tuple[float, ...]
    knots_y: tuple[float, ...]
    support_count: int
    report: CalibrationReport

    def apply(self, raw: float) -> tuple[float, bool]:
        xs = np.asarray(self.knots_x, dtype=np.float64)
        ys = np.asarray(self.knots_y, dtype=np.float64)
        clamped = bool(raw < xs[0] - 1e-12 or raw > xs[-1] + 1e-12)
        value = float(np.interp(raw, xs, ys))
        return float(np.clip(value, 0.0, 1.0)), clamped

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_definition": self.event_definition,
            "knots_x": list(self.knots_x),
            "knots_y": list(self.knots_y),
            "support_count": self.support_count,
            "report": self.report.model_dump(mode="json"),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> _EventMap:
        return cls(
            event_definition=str(payload["event_definition"]),
            knots_x=tuple(float(v) for v in payload["knots_x"]),
            knots_y=tuple(float(v) for v in payload["knots_y"]),
            support_count=int(payload["support_count"]),
            report=CalibrationReport.model_validate(payload["report"]),
        )


@dataclass(frozen=True, slots=True)
class ProbabilityCalibrator:
    """A frozen per-event monotone calibration map.

    One map per event definition. ``pass_before`` and ``ahead_at`` are different
    events with different base rates, and one shared map would be a claim that
    they miscalibrate identically.
    """

    maps: dict[str, _EventMap]
    forecaster_version: str
    method: str = "isotonic_pav"
    min_support: int = DEFAULT_MIN_SUPPORT
    frozen_before_final_test: bool = False
    fitted_at: str = ""
    unavailable_events: dict[str, str] = field(default_factory=dict)

    @property
    def calibrator_id(self) -> str:
        return f"calibrator/{self.method}/{self.content_hash()[7:23]}"

    @property
    def event_definitions(self) -> tuple[str, ...]:
        return tuple(sorted(self.maps))

    def report_for(self, event_definition: str) -> CalibrationReport | None:
        entry = self.maps.get(event_definition)
        return None if entry is None else entry.report

    def apply(self, event_definition: str, raw_frequency: float) -> CalibratedProbability:
        """Calibrate one forecast, or say why it was not calibrated."""
        if not np.isfinite(raw_frequency):
            return CalibratedProbability(
                value=None,
                raw_frequency=float(raw_frequency),
                status=CalibratorStatus.NON_FINITE,
                detail="the raw frequency was not finite",
                calibrator_id=self.calibrator_id,
            )
        if not self.frozen_before_final_test:
            return CalibratedProbability(
                value=None,
                raw_frequency=float(raw_frequency),
                status=CalibratorStatus.NOT_FROZEN,
                detail=(
                    "this calibrator is not frozen before a final test, so its output is not "
                    "published as a calibrated probability"
                ),
                calibrator_id=self.calibrator_id,
            )
        entry = self.maps.get(event_definition)
        if entry is None:
            reason = self.unavailable_events.get(
                event_definition, "this event definition was not part of the calibration set"
            )
            return CalibratedProbability(
                value=None,
                raw_frequency=float(raw_frequency),
                status=CalibratorStatus.EVENT_NOT_CALIBRATED,
                detail=reason,
                calibrator_id=self.calibrator_id,
            )
        if entry.support_count < self.min_support:
            return CalibratedProbability(
                value=None,
                raw_frequency=float(raw_frequency),
                status=CalibratorStatus.INSUFFICIENT_SUPPORT,
                detail=(
                    f"{entry.support_count} labelled sample(s) is below the declared minimum "
                    f"{self.min_support}"
                ),
                support_count=entry.support_count,
                calibrator_id=self.calibrator_id,
            )
        value, clamped = entry.apply(float(raw_frequency))
        return CalibratedProbability(
            value=value,
            raw_frequency=float(raw_frequency),
            status=CalibratorStatus.CALIBRATED,
            detail=(
                "clamped to the nearest fitted end; the calibration set did not cover this forecast range"
                if clamped
                else ""
            ),
            clamped=clamped,
            support_count=entry.support_count,
            calibrator_id=self.calibrator_id,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": CALIBRATOR_SCHEMA,
            "status": "available",
            "method": self.method,
            "forecaster_version": self.forecaster_version,
            "min_support": self.min_support,
            "frozen_before_final_test": self.frozen_before_final_test,
            "fitted_at": self.fitted_at,
            "events": {name: entry.as_dict() for name, entry in sorted(self.maps.items())},
            "unavailable_events": dict(sorted(self.unavailable_events.items())),
        }

    def content_hash(self) -> str:
        payload = self.as_dict()
        payload.pop("fitted_at", None)
        return sha256_json(payload)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ProbabilityCalibrator | None:
        """Rebuild a calibrator, or ``None`` for the unavailable placeholder.

        ``serving.write_bundle`` writes ``{"status": "unavailable", ...}`` when
        no calibration set exists. That is a valid bundle, so this returns
        ``None`` rather than raising: the caller falls back to the uncalibrated
        frequency and says so.
        """
        if payload.get("schema") != CALIBRATOR_SCHEMA:
            return None
        if payload.get("status") != "available":
            return None
        events = payload.get("events") or {}
        return cls(
            maps={str(name): _EventMap.from_dict(entry) for name, entry in events.items()},
            forecaster_version=str(payload.get("forecaster_version", "unknown")),
            method=str(payload.get("method", "isotonic_pav")),
            min_support=int(payload.get("min_support", DEFAULT_MIN_SUPPORT)),
            frozen_before_final_test=bool(payload.get("frozen_before_final_test", False)),
            fitted_at=str(payload.get("fitted_at", "")),
            unavailable_events={str(k): str(v) for k, v in (payload.get("unavailable_events") or {}).items()},
        )


@dataclass(frozen=True, slots=True)
class CalibrationFit:
    """The fitted calibrator plus the evidence for and against it."""

    calibrator: ProbabilityCalibrator | None
    before: dict[str, dict[str, Any]]
    after: dict[str, dict[str, Any]]
    refusals: dict[str, str]
    sample_count: int
    episode_count: int
    holdout_episode_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "calibrator": None if self.calibrator is None else self.calibrator.as_dict(),
            "calibrator_id": None if self.calibrator is None else self.calibrator.calibrator_id,
            "sample_count": self.sample_count,
            "episode_count": self.episode_count,
            "holdout_episode_count": self.holdout_episode_count,
            "before": self.before,
            "after": self.after,
            "refusals": self.refusals,
            "note": (
                "`before` scores the raw ensemble frequency and `after` scores the calibrated "
                "value on held-out episodes. A calibrator that does not improve `before` is "
                "reported, not hidden."
            ),
        }


def _assess(
    predictions: np.ndarray, labels: np.ndarray, *, event_definition: str, bins: int, min_support: int
) -> dict[str, Any]:
    from ..evaluation.statistics import assess_calibration

    return assess_calibration(
        predictions,
        labels,
        event_definition=event_definition,
        bins=bins,
        min_support=min_support,
    ).as_dict()


def _report(
    predictions: np.ndarray, labels: np.ndarray, *, event_definition: str, bins: int, min_support: int
) -> CalibrationReport:
    from ..evaluation.statistics import assess_calibration

    return assess_calibration(
        predictions,
        labels,
        event_definition=event_definition,
        bins=bins,
        min_support=min_support,
    ).report


def fit_calibrator(
    samples: list[CalibrationSample],
    *,
    forecaster_version: str,
    seed: int = 0,
    holdout_fraction: float = 0.3,
    min_support: int = DEFAULT_MIN_SUPPORT,
    bins: int = DEFAULT_BINS,
) -> CalibrationFit:
    """Fit one monotone map per event, and score it on held-out episodes.

    The split is **by episode**, never by sample: several forecasts from one
    episode share its realisation, and splitting between them would let the fit
    see the outcome it is later scored against.

    A calibrator is returned only for the events that could actually be fitted.
    Every other event lands in ``refusals`` with its reason, and applying the
    calibrator to it yields ``value=None``.
    """
    if not samples:
        raise ValueError("cannot fit a calibrator with no samples")

    episodes = sorted({sample.episode_id for sample in samples})
    if len(episodes) < 2:
        raise ValueError(
            "a held-out calibration split needs at least two episodes; a calibrator scored on "
            "the episodes it was fitted on reports its own training error"
        )
    rng = np.random.default_rng(seed)
    shuffled = list(episodes)
    rng.shuffle(shuffled)
    holdout_count = max(1, round(len(shuffled) * holdout_fraction))
    holdout = set(shuffled[:holdout_count])
    fit_ids = set(shuffled[holdout_count:])
    if not fit_ids:  # pragma: no cover - guarded by the length check
        raise ValueError("the split left no fitting episodes")

    maps: dict[str, _EventMap] = {}
    refusals: dict[str, str] = {}
    before: dict[str, dict[str, Any]] = {}
    after: dict[str, dict[str, Any]] = {}

    for event in sorted({sample.event_definition for sample in samples}):
        fit_rows = [s for s in samples if s.event_definition == event and s.episode_id in fit_ids]
        holdout_rows = [s for s in samples if s.event_definition == event and s.episode_id in holdout]
        if len(fit_rows) < min_support:
            refusals[event] = (
                f"{len(fit_rows)} fitting sample(s) is below the declared minimum {min_support}; "
                "no map was fitted and this event stays uncalibrated"
            )
            continue

        x = np.asarray([s.raw_frequency for s in fit_rows], dtype=np.float64)
        y = np.asarray([float(s.outcome) for s in fit_rows], dtype=np.float64)
        w = np.asarray([s.weight for s in fit_rows], dtype=np.float64)
        positives = int(y.sum())
        if positives in (0, y.size):
            refusals[event] = (
                f"all {y.size} fitting outcomes are the same class; no monotone map can be "
                "identified and a constant fit would report a perfect score"
            )
            continue

        knots_x, knots_y = isotonic_fit(x, y, w)
        if not holdout_rows:
            refusals[event] = (
                "the episode split left no held-out sample for this event; a map scored on its "
                "own fitting set is not evidence"
            )
            continue

        holdout_x = np.asarray([s.raw_frequency for s in holdout_rows], dtype=np.float64)
        holdout_y = np.asarray([float(s.outcome) for s in holdout_rows], dtype=np.float64)
        calibrated = np.clip(np.interp(holdout_x, knots_x, knots_y), 0.0, 1.0)

        before[event] = _assess(
            holdout_x, holdout_y, event_definition=event, bins=bins, min_support=min_support
        )
        after[event] = _assess(
            calibrated, holdout_y, event_definition=event, bins=bins, min_support=min_support
        )
        maps[event] = _EventMap(
            event_definition=event,
            knots_x=tuple(float(v) for v in knots_x),
            knots_y=tuple(float(v) for v in knots_y),
            support_count=len(fit_rows),
            report=_report(calibrated, holdout_y, event_definition=event, bins=bins, min_support=min_support),
        )

    calibrator = (
        ProbabilityCalibrator(
            maps=maps,
            forecaster_version=forecaster_version,
            min_support=min_support,
            frozen_before_final_test=False,
            fitted_at=datetime.now(UTC).isoformat(),
            unavailable_events=refusals,
        )
        if maps
        else None
    )
    return CalibrationFit(
        calibrator=calibrator,
        before=before,
        after=after,
        refusals=refusals,
        sample_count=len(samples),
        episode_count=len(fit_ids),
        holdout_episode_count=len(holdout),
    )
