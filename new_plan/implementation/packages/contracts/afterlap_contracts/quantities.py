"""Numeric value wrappers that carry provenance, age and uncertainty.

Rule from UNITS_TIME.md: *unknown is null plus a reason, never zero*. These
types make that structurally enforceable — a value cannot be transported
without saying where it came from and how stale it is.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .base import Contract
from .enums import CalibrationStatus, Provenance, Quality


class ScalarValue(Contract):
    """A single SI measurement or estimate with provenance and freshness.

    ``value`` is ``None`` whenever the quantity is unknown; ``quality`` then
    explains why. A consumer must not substitute ``0.0``.
    """

    value: float | None
    unit: str = Field(min_length=1, description="SI unit symbol, e.g. 'J', 'W', 'm', 'm/s', 'K'.")
    provenance: Provenance
    quality: Quality = Quality.VALID
    observed_at_s: float | None = Field(
        default=None,
        description="Session time of the newest observation supporting this value.",
    )
    age_s: float | None = Field(
        default=None, ge=0.0, description="Session-time age of the supporting observation."
    )
    standard_deviation: float | None = Field(
        default=None, ge=0.0, description="1-sigma uncertainty in the same unit as ``value``."
    )
    source_id: str | None = None

    @model_validator(mode="after")
    def _unknown_has_a_reason(self) -> ScalarValue:
        if self.value is None and self.quality is Quality.VALID:
            raise ValueError("a null value cannot be reported as quality=valid; use missing/invalid")
        if self.value is not None and self.quality is Quality.MISSING:
            raise ValueError("quality=missing requires value=None")
        return self

    @property
    def is_known(self) -> bool:
        return self.value is not None

    @classmethod
    def missing(
        cls, unit: str, provenance: Provenance = Provenance.MEASURED, *, source_id: str | None = None
    ) -> ScalarValue:
        """Construct an explicitly unknown quantity."""
        return cls(value=None, unit=unit, provenance=provenance, quality=Quality.MISSING, source_id=source_id)


class IntervalValue(Contract):
    """A bounded belief about a quantity whose point value is not identified.

    ``kind`` distinguishes physical bounds from statistical intervals so a
    consumer never renders a support range as a confidence interval.
    """

    lower: float | None
    upper: float | None
    unit: str = Field(min_length=1)
    kind: Literal["physical_bounds", "quantile", "confidence_interval"]
    coverage: float | None = Field(
        default=None, gt=0.0, lt=1.0, description="Nominal coverage for quantile/confidence kinds."
    )
    provenance: Provenance
    quality: Quality = Quality.VALID
    observed_at_s: float | None = None
    age_s: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def _ordered_and_labelled(self) -> IntervalValue:
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("interval lower bound exceeds upper bound")
        if self.kind in ("quantile", "confidence_interval") and self.coverage is None:
            raise ValueError(f"kind={self.kind} requires an explicit coverage")
        if self.kind == "physical_bounds" and self.coverage is not None:
            raise ValueError("physical_bounds must not claim statistical coverage")
        if self.lower is None and self.upper is None and self.quality is Quality.VALID:
            raise ValueError("an unbounded interval cannot be reported as valid")
        return self

    @property
    def width(self) -> float | None:
        if self.lower is None or self.upper is None:
            return None
        return self.upper - self.lower


class ProbabilityStatement(Contract):
    """A probability that always carries its event definition and calibration state.

    An unavailable probability is ``value=None``; it is never displayed as 0.
    """

    event_definition: str = Field(
        min_length=1,
        description="Precise event, e.g. 'pass_before(checkpoint=attack-exit)'.",
    )
    checkpoint_id: str | None = None
    horizon_s: float | None = Field(default=None, gt=0.0)
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    raw_frequency: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Uncalibrated weighted scenario frequency."
    )
    sample_count: int | None = Field(default=None, ge=0)
    model_version: str | None = None
    calibration_status: CalibrationStatus = CalibrationStatus.UNAVAILABLE

    @model_validator(mode="after")
    def _calibration_consistency(self) -> ProbabilityStatement:
        if self.calibration_status is CalibrationStatus.CALIBRATED and self.value is None:
            raise ValueError("calibrated probability must carry a value")
        if self.value is not None and self.calibration_status is CalibrationStatus.UNAVAILABLE:
            raise ValueError(
                "a probability value must declare calibrated or uncalibrated status, not unavailable"
            )
        if self.checkpoint_id is None and self.horizon_s is None:
            raise ValueError("a probability needs a checkpoint or a horizon to be meaningful")
        return self


class WeightedSample(Contract):
    """One weighted hypothesis from a particle or scenario ensemble."""

    sample_id: str = Field(min_length=1)
    weight: float = Field(ge=0.0)
    values: dict[str, float]


class EnsembleBelief(Contract):
    """A weighted-particle belief used where an interval would be misleading."""

    samples: tuple[WeightedSample, ...] = Field(min_length=1)
    unit: str = Field(min_length=1)
    provenance: Provenance = Provenance.ESTIMATED
    effective_sample_size: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def _weights_positive(self) -> EnsembleBelief:
        total = sum(s.weight for s in self.samples)
        if total <= 0.0:
            raise ValueError("ensemble weights must sum to a positive number")
        return self


__all__ = [
    "EnsembleBelief",
    "IntervalValue",
    "ProbabilityStatement",
    "ScalarValue",
    "WeightedSample",
]
