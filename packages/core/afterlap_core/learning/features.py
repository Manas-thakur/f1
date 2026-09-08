"""The frozen ``energy-v1`` observation encoder.

The encoder is driven entirely by
:data:`afterlap_core.feature_manifest.ENERGY_V1`. Field order, unit, offset,
scale and clip range are read from the manifest; this module decides only *which
belief field feeds which manifest entry*, and whether that field is known.

Four rules are structural rather than conventional:

* **Unknown is zero with mask zero.** A null ``ScalarValue`` never becomes a
  number. A genuine known zero is zero with mask **one**, and the two are
  distinguishable to the network for exactly that reason.
* **The rival ``present_flag`` is never masked.** The absence of a rival is
  known information, so an empty slot publishes ``present=0`` with ``mask=1``
  and every other field of that slot masked.
* **No NaN or infinity reaches the network.** A non-finite raw value is treated
  as unknown and counted, not clipped into range.
* **The encoder reads a** :class:`~afterlap_contracts.StateEstimate` **and a
  declared context, never simulator truth.** Mutating hidden state while the
  delivered observations are held fixed leaves the encoded vector byte
  identical; ``tests/learning/test_features.py`` asserts that by bytes.

Pre-clip values and clip counts are retained on :class:`EncodedObservation` for
the out-of-distribution checks the specification requires. Clipping protects the
arithmetic; it does not make an unsupported state supported.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from afterlap_contracts import (
    EligibilityState,
    FeatureManifest,
    FlagState,
    IntervalValue,
    RivalBelief,
    ScalarValue,
    StateEstimate,
)

from ..feature_manifest import (
    ENERGY_V1,
    LOOKAHEAD_OFFSETS_M,
    OBSERVATION_SIZE,
    VALUE_COUNT,
    feature_index,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "EncodedObservation",
    "FeatureContext",
    "FeatureEncoder",
    "HistorySummary",
    "LookaheadSample",
    "RivalSlotView",
    "encode",
]

_RESTRICTIVE_FLAGS = (
    FlagState.YELLOW,
    FlagState.DOUBLE_YELLOW,
    FlagState.SAFETY_CAR,
    FlagState.VIRTUAL_SAFETY_CAR,
    FlagState.RED,
)


@dataclass(frozen=True, slots=True)
class LookaheadSample:
    """One track-geometry preview sample.

    Every field is independently optional. A ceiling that depends on an
    unresolved eligibility is ``None`` and stays masked; it is never predicted as
    a guaranteed permission. ``beyond_finish`` masks the whole sample, because
    track geometry wraps but race completion does not.
    """

    distance_ahead_m: float | None = None
    curvature_inv_m: float | None = None
    grade_rad: float | None = None
    deployment_ceiling_w: float | None = None
    recovery_capacity_w: float | None = None
    beyond_finish: bool = False


@dataclass(frozen=True, slots=True)
class HistorySummary:
    """Engineered short-horizon summaries the estimate does not itself carry."""

    gap_trend_4s: float | None = None
    own_depletion_rate_4s_w: float | None = None
    gap_innovation_magnitude_s: float | None = None
    missed_execution_count_8s: int | None = None
    last_decoded_budget_j: float | None = None
    last_decoded_reserve_target_j: float | None = None
    time_since_instruction_change_s: float | None = None
    instruction_change_count_8s: int | None = None


@dataclass(frozen=True, slots=True)
class FeatureContext:
    """Currently known context that is not part of the published belief.

    Everything here is either a declared configuration value, a resolved rule
    limit or a quantity the controller itself produced. None of it is simulator
    truth.
    """

    track_length_m: float
    limits_deployment_ceiling_w: float | None = None
    limits_recovery_ceiling_w: float | None = None
    limits_recharge_allowance_remaining_j: float | None = None
    thermal_headroom_k: float | None = None
    instruction_hold_remaining_s: float | None = None
    driver_delay_mean_s: float | None = None
    driver_delay_std_s: float | None = None
    wet_flag: bool | None = None
    lookahead: Sequence[LookaheadSample] = ()
    history: HistorySummary = field(default_factory=HistorySummary)

    def __post_init__(self) -> None:
        if self.track_length_m <= 0.0:
            raise ValueError("track length must be positive")
        if self.lookahead and len(self.lookahead) != len(LOOKAHEAD_OFFSETS_M):
            raise ValueError(
                f"the lookahead block has {len(LOOKAHEAD_OFFSETS_M)} fixed samples, got {len(self.lookahead)}"
            )


@dataclass(frozen=True, slots=True)
class RivalSlotView:
    """The belief occupying one stable identity slot, or its absence."""

    belief: RivalBelief | None
    slot: str

    @property
    def present(self) -> bool:
        return self.belief is not None


@dataclass(frozen=True, slots=True)
class EncodedObservation:
    """One encoded tick: the network input plus its out-of-distribution record.

    ``observation`` is ``concat(values[96], known_mask[96])`` as float32.
    ``pre_clip_values`` holds the normalised values *before* clipping, so a
    monitor can see how far out of range a state actually was.
    """

    observation: np.ndarray
    values: np.ndarray
    mask: np.ndarray
    pre_clip_values: np.ndarray
    clipped_indices: tuple[int, ...]
    unknown_indices: tuple[int, ...]
    non_finite_indices: tuple[int, ...]
    feature_hash: str
    revision: str

    @property
    def clip_count(self) -> int:
        return len(self.clipped_indices)

    @property
    def clip_fraction(self) -> float:
        return self.clip_count / float(VALUE_COUNT)

    @property
    def known_mask_fraction(self) -> float:
        return float(self.mask.sum()) / float(VALUE_COUNT)

    def clipped_names(self, manifest: FeatureManifest = ENERGY_V1) -> tuple[str, ...]:
        return tuple(manifest.fields[i].name for i in self.clipped_indices)

    def diagnostics(self) -> dict[str, float | int]:
        """Clip and mask statistics, safe to log every tick."""
        return {
            "clip_count": self.clip_count,
            "clip_fraction": self.clip_fraction,
            "known_mask_fraction": self.known_mask_fraction,
            "unknown_count": len(self.unknown_indices),
            "non_finite_count": len(self.non_finite_indices),
            "max_abs_pre_clip": float(np.max(np.abs(self.pre_clip_values))) if VALUE_COUNT else 0.0,
        }


def _scalar(value: ScalarValue | None) -> float | None:
    """A ``ScalarValue``'s number, or ``None`` when it is unknown."""
    if value is None or value.value is None:
        return None
    return float(value.value)


def _sigma(value: ScalarValue | None) -> float | None:
    if value is None or value.standard_deviation is None:
        return None
    return float(value.standard_deviation)


def _interval_half_width(interval: IntervalValue | None) -> float | None:
    if interval is None or interval.lower is None or interval.upper is None:
        return None
    return 0.5 * (interval.upper - interval.lower)


class FeatureEncoder:
    """Encodes a :class:`StateEstimate` plus context into the frozen vector.

    One instance is stateless with respect to episodes; it holds the manifest and
    the per-field normalisation arrays only. Actor and continuation ensemble use
    exactly this object, which is why their inputs cannot drift apart.
    """

    def __init__(self, manifest: FeatureManifest = ENERGY_V1) -> None:
        self._manifest = manifest
        self._offsets = np.array([f.offset for f in manifest.fields], dtype=np.float64)
        self._scales = np.array([f.scale for f in manifest.fields], dtype=np.float64)
        self._clip_low = np.array([f.clip_low for f in manifest.fields], dtype=np.float64)
        self._clip_high = np.array([f.clip_high for f in manifest.fields], dtype=np.float64)
        self._maskable = np.array([f.maskable for f in manifest.fields], dtype=bool)
        self._feature_hash = manifest.content_hash()
        self._index = {f.name: f.index for f in manifest.fields}

    @property
    def manifest(self) -> FeatureManifest:
        return self._manifest

    @property
    def feature_hash(self) -> str:
        """The schema hash that goes into every bundle."""
        return self._feature_hash

    @property
    def revision(self) -> str:
        return self._manifest.revision

    @property
    def observation_size(self) -> int:
        return self._manifest.observation_size

    def encode(self, estimate: StateEstimate, context: FeatureContext) -> EncodedObservation:
        raw: list[float | None] = [None] * VALUE_COUNT

        self._fill_own_car(raw, estimate, context)
        self._fill_lookahead(raw, context)
        self._fill_rival(raw, "ahead", self._slot_for(estimate, ahead=True))
        self._fill_rival(raw, "behind", self._slot_for(estimate, ahead=False))
        self._fill_history(raw, context.history)

        return self._finalise(raw)

    def _finalise(self, raw: Sequence[float | None]) -> EncodedObservation:
        known = np.zeros(VALUE_COUNT, dtype=bool)
        numeric = np.zeros(VALUE_COUNT, dtype=np.float64)
        non_finite: list[int] = []
        for index, value in enumerate(raw):
            if value is None:
                continue
            if not math.isfinite(value):
                non_finite.append(index)
                continue
            known[index] = True
            numeric[index] = value

        normalised = np.where(known, (numeric - self._offsets) / self._scales, 0.0)
        pre_clip = normalised.copy()
        clipped = np.clip(normalised, self._clip_low, self._clip_high)
        clipped_indices = tuple(int(i) for i in np.flatnonzero(known & (clipped != pre_clip)))
        values = np.where(known, clipped, 0.0)

        mask = np.where(self._maskable, known, True)
        unknown_indices = tuple(int(i) for i in np.flatnonzero(~known))

        observation = np.concatenate([values, mask.astype(np.float64)]).astype(np.float32)
        if not np.all(np.isfinite(observation)):  # pragma: no cover - defence in depth
            raise ValueError("the encoder produced a non-finite observation")
        if observation.shape != (OBSERVATION_SIZE,):  # pragma: no cover - shape is structural
            raise ValueError(f"encoded observation has shape {observation.shape}")

        return EncodedObservation(
            observation=observation,
            values=values.astype(np.float32),
            mask=mask.astype(np.float32),
            pre_clip_values=pre_clip,
            clipped_indices=clipped_indices,
            unknown_indices=unknown_indices,
            non_finite_indices=tuple(non_finite),
            feature_hash=self._feature_hash,
            revision=self._manifest.revision,
        )

    def _set(self, raw: list[float | None], name: str, value: float | None) -> None:
        raw[self._index[name]] = value

    def _fill_own_car(
        self, raw: list[float | None], estimate: StateEstimate, context: FeatureContext
    ) -> None:
        own = estimate.own_car
        race = estimate.race_context

        self._set(raw, "own_speed", _scalar(own.speed_mps))
        self._set(raw, "own_acceleration", _scalar(own.acceleration_mps2))

        lap_distance = _scalar(own.lap_distance_m)
        lap_fraction = None
        if lap_distance is not None and context.track_length_m > 0.0:
            lap_fraction = (lap_distance % context.track_length_m) / context.track_length_m
        self._set(raw, "lap_fraction", lap_fraction)

        self._set(raw, "remaining_race_distance", _scalar(race.remaining_distance_m))

        energy = _scalar(own.battery_energy_j)
        energy_sigma = _sigma(own.battery_energy_j)
        if energy is None and own.battery_energy_interval is not None:
            lower = own.battery_energy_interval.lower
            upper = own.battery_energy_interval.upper
            if lower is not None and upper is not None:
                energy = 0.5 * (lower + upper)
                energy_sigma = _interval_half_width(own.battery_energy_interval)
        if not estimate.quality.own_energy_capability:
            energy = None
            energy_sigma = None
        self._set(raw, "own_energy_mean", energy)
        self._set(raw, "own_energy_std", energy_sigma)

        self._set(raw, "battery_temperature", _scalar(own.battery_temperature_k))
        self._set(raw, "thermal_headroom", context.thermal_headroom_k)
        self._set(raw, "recharge_spent_this_lap", _scalar(own.recharge_spent_this_lap_j))
        self._set(raw, "recharge_allowance_remaining", context.limits_recharge_allowance_remaining_j)
        self._set(raw, "observed_electrical_power", _scalar(own.electrical_power_w))
        self._set(raw, "deployment_ceiling", context.limits_deployment_ceiling_w)
        self._set(raw, "recovery_ceiling", context.limits_recovery_ceiling_w)

        self._set(raw, "own_observation_age", max(0.0, estimate.created_at_s - estimate.cutoff_s))
        self._set(raw, "clock_uncertainty", estimate.quality.clock_uncertainty_s)
        self._set(raw, "instruction_hold_remaining", context.instruction_hold_remaining_s)
        self._set(raw, "driver_delay_mean", context.driver_delay_mean_s)
        self._set(raw, "driver_delay_std", context.driver_delay_std_s)
        self._set(raw, "tyre_pace_residual", _scalar(own.tyre_pace_residual_s_per_lap))
        self._set(raw, "completed_laps", float(own.completed_laps))

        self._set(raw, "wet_flag", None if context.wet_flag is None else float(context.wet_flag))
        yellow = None
        if race.flag_known and race.flag_state is not FlagState.UNKNOWN:
            yellow = float(race.flag_state in _RESTRICTIVE_FLAGS)
        self._set(raw, "yellow_flag", yellow)

        eligibility_known = race.eligibility is not EligibilityState.UNKNOWN
        self._set(
            raw,
            "overtake_eligibility",
            float(race.eligibility in (EligibilityState.ELIGIBLE_DETECTED, EligibilityState.ACTIVE))
            if eligibility_known
            else None,
        )
        self._set(raw, "eligibility_known_flag", float(eligibility_known))

    def _fill_lookahead(self, raw: list[float | None], context: FeatureContext) -> None:
        samples = list(context.lookahead) or [LookaheadSample() for _ in LOOKAHEAD_OFFSETS_M]
        for distance, sample in zip(LOOKAHEAD_OFFSETS_M, samples, strict=True):
            label = f"lookahead_{int(distance)}m"
            if sample.beyond_finish:
                continue
            self._set(raw, f"{label}_distance_ahead", sample.distance_ahead_m)
            self._set(raw, f"{label}_curvature", sample.curvature_inv_m)
            self._set(raw, f"{label}_grade", sample.grade_rad)
            self._set(raw, f"{label}_deployment_ceiling", sample.deployment_ceiling_w)
            self._set(raw, f"{label}_recovery_capacity", sample.recovery_capacity_w)

    def _slot_for(self, estimate: StateEstimate, *, ahead: bool) -> RivalSlotView:
        """Resolve a stable identity slot, falling back to the nearest rival.

        The estimator publishes ``ahead_1`` / ``behind_1``; a belief built by
        another route may not, so the nearest rival on the correct side is used
        instead. Either way one slot is one rival, which is what stops two cars
        swapping the same feature block on tiny gap noise.
        """
        slot = "ahead_1" if ahead else "behind_1"
        belief = estimate.rival_in_slot(slot)
        if belief is None:
            belief = estimate.nearest_ahead if ahead else estimate.nearest_behind
        if belief is not None and belief.is_ahead is not ahead:
            belief = None
        return RivalSlotView(belief=belief, slot=slot)

    def _fill_rival(self, raw: list[float | None], slot: str, view: RivalSlotView) -> None:
        prefix = f"rival_{slot}_"
        self._set(raw, f"{prefix}present_flag", float(view.present))
        belief = view.belief
        if belief is None:
            return

        gap = _scalar(belief.gap_s)
        if gap is not None:
            gap = abs(gap) if belief.is_ahead else -abs(gap)
        self._set(raw, f"{prefix}gap_s", gap)
        self._set(raw, f"{prefix}relative_speed", _scalar(belief.relative_speed_mps))

        energy = _scalar(belief.energy_mean_j)
        energy_sigma = _sigma(belief.energy_mean_j)
        if energy is None and belief.energy_interval_j is not None:
            lower = belief.energy_interval_j.lower
            upper = belief.energy_interval_j.upper
            if lower is not None and upper is not None:
                energy = 0.5 * (lower + upper)
        if energy_sigma is None:
            energy_sigma = _interval_half_width(belief.energy_interval_j)
        self._set(raw, f"{prefix}energy_belief_mean", energy)
        self._set(raw, f"{prefix}energy_belief_std", energy_sigma)

        self._set(raw, f"{prefix}pace_bias", _scalar(belief.pace_bias_s_per_lap))
        self._set(raw, f"{prefix}pace_uncertainty", _sigma(belief.pace_bias_s_per_lap))

        intentions = belief.intentions
        self._set(raw, f"{prefix}conserve_probability", intentions.conserve)
        self._set(raw, f"{prefix}normal_probability", intentions.normal)
        self._set(raw, f"{prefix}attack_probability", intentions.attack)
        self._set(raw, f"{prefix}defend_probability", intentions.defend)
        self._set(raw, f"{prefix}observation_age", belief.observation_age_s)

    def _fill_history(self, raw: list[float | None], history: HistorySummary) -> None:
        self._set(raw, "gap_trend_4s", history.gap_trend_4s)
        self._set(raw, "own_depletion_rate_4s", history.own_depletion_rate_4s_w)
        self._set(raw, "gap_innovation_magnitude", history.gap_innovation_magnitude_s)
        self._set(
            raw,
            "missed_execution_count_8s",
            None if history.missed_execution_count_8s is None else float(history.missed_execution_count_8s),
        )
        self._set(raw, "last_decoded_budget", history.last_decoded_budget_j)
        self._set(raw, "last_decoded_reserve_target", history.last_decoded_reserve_target_j)
        self._set(raw, "time_since_instruction_change", history.time_since_instruction_change_s)
        self._set(
            raw,
            "instruction_change_count_8s",
            None
            if history.instruction_change_count_8s is None
            else float(history.instruction_change_count_8s),
        )

    def value_of(self, encoded: EncodedObservation, name: str) -> float:
        return float(encoded.values[self._index[name]])

    def mask_of(self, encoded: EncodedObservation, name: str) -> float:
        return float(encoded.mask[self._index[name]])

    def denormalise(self, encoded: EncodedObservation, name: str) -> float:
        index = self._index[name]
        return float(encoded.values[index] * self._scales[index] + self._offsets[index])


_DEFAULT_ENCODER = FeatureEncoder()


def encode(estimate: StateEstimate, context: FeatureContext) -> EncodedObservation:
    """Encode with the module-level frozen encoder."""
    return _DEFAULT_ENCODER.encode(estimate, context)


def default_encoder() -> FeatureEncoder:
    return _DEFAULT_ENCODER


def index_of(name: str) -> int:
    """Manifest offset of a named field; re-exported so callers need one import."""
    return feature_index(name)


def clip_report(encoded: EncodedObservation, manifest: FeatureManifest = ENERGY_V1) -> Mapping[str, float]:
    """Per-field pre-clip magnitude for the fields that actually clipped."""
    return {manifest.fields[i].name: float(encoded.pre_clip_values[i]) for i in encoded.clipped_indices}
