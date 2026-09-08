"""Typed loaders for the estimation manifests in ``configs/estimation/``.

Every physical number the estimator uses arrives through one of these documents
with a unit, a source and a verification status, so a tuned value can never be
confused with a measured one. The rival mode transition matrix additionally
carries ``transition_matrix_authorship``; the filter refuses to run unless that
field says the matrix is a declared hand-authored prior or an explicitly
estimated one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from afterlap_contracts import RivalIntention
from afterlap_core.config import ConfigDocument, Parameter, load_config, load_yaml

OWN_CAR_CONFIG_ID = "own-car-ekf-v1"
RIVAL_CONFIG_ID = "rival-modes-v1"

#: Canonical mode order. Every matrix and gain vector in this package uses it.
MODE_ORDER: tuple[RivalIntention, ...] = (
    RivalIntention.CONSERVE,
    RivalIntention.NORMAL,
    RivalIntention.ATTACK,
    RivalIntention.DEFEND,
)
MODE_INDEX: dict[RivalIntention, int] = {mode: i for i, mode in enumerate(MODE_ORDER)}


class _Section(BaseModel):
    """Immutable, strictly-validated manifest section."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class MotionNoise(_Section):
    """Process-model parameters of the motion block."""

    acceleration_time_constant_s: Parameter
    drag_per_m: Parameter
    process_jerk_psd: Parameter


class EnergyNoise(_Section):
    """Battery-side integration parameters and the physical operating window."""

    harvest_efficiency: Parameter
    power_model_sigma_w: Parameter
    unobserved_gap_sigma_w: Parameter
    physical_min_j: Parameter
    physical_max_j: Parameter


class MeasurementNoise(_Section):
    """Base measurement 1-sigma values, before clock-uncertainty inflation."""

    speed_sigma_mps: Parameter
    progress_sigma_m: Parameter
    acceleration_sigma_mps2: Parameter
    energy_sigma_j: Parameter
    temperature_sigma_k: Parameter


class InitialUncertainty(_Section):
    """Initial covariance diagonal."""

    progress_sigma_m: Parameter
    speed_sigma_mps: Parameter
    acceleration_sigma_mps2: Parameter
    energy_sigma_j: Parameter


class DiagnosticsConfig(_Section):
    """Residual-alarm and linearisation-step settings."""

    nis_alarm_threshold: Parameter
    nis_smoothing: Parameter
    max_prediction_step_s: Parameter


class OwnCarConfig(ConfigDocument):
    """Loaded ``own-car-ekf-v1.yaml``."""

    motion: MotionNoise
    energy: EnergyNoise
    measurement: MeasurementNoise
    initial: InitialUncertainty
    diagnostics: DiagnosticsConfig

    @model_validator(mode="after")
    def _window_is_ordered(self) -> OwnCarConfig:
        if self.energy.physical_min_j.value >= self.energy.physical_max_j.value:
            raise ValueError("battery physical window must have min < max")
        return self


class ModeGains(_Section):
    """A per-mode gain vector keyed by the intention enum values."""

    conserve: float
    normal: float
    attack: float
    defend: float

    def as_array(self) -> np.ndarray:
        return np.array(
            [self.conserve, self.normal, self.attack, self.defend],
            dtype=np.float64,
        )


class BehaviourConfig(_Section):
    """Pace and power signature of each reactive intention."""

    base_speed_gain_mps: ModeGains
    pressure_speed_gain_mps: ModeGains
    base_power_w: ModeGains
    pressure_power_w: ModeGains
    ambiguity_note: str = Field(min_length=1)


class RivalDynamics(_Section):
    """Bounded process model of a rival's hidden energy and pace bias."""

    deploy_reference_energy_j: Parameter
    pace_bias_sigma_mps: Parameter
    pace_bias_time_constant_s: Parameter
    pace_bias_process_sigma_mps: Parameter
    energy_process_sigma_w: Parameter
    energy_min_j: Parameter
    energy_max_j: Parameter
    prior_energy_min_j: Parameter
    prior_energy_max_j: Parameter
    max_deploy_power_w: Parameter


class RivalLikelihood(_Section):
    """Observation-noise and model-mismatch terms of the particle likelihood."""

    gap_rate_sigma_mps: Parameter
    rival_speed_sigma_mps: Parameter
    gap_measurement_sigma_m: Parameter
    belief_update_interval_s: Parameter
    model_residual_sigma_mps: Parameter
    dropout_variance_growth_per_s: Parameter


class FilterConfig(_Section):
    """Particle count, resampling threshold and mode support floors."""

    particle_count: Parameter
    ess_resample_fraction: Parameter
    mode_weight_floor: Parameter
    min_particles_per_mode: Parameter
    mode_time_constant_s: Parameter

    @property
    def n_particles(self) -> int:
        return round(self.particle_count.value)

    @property
    def min_per_mode(self) -> int:
        return round(self.min_particles_per_mode.value)


class QuantileConfig(_Section):
    interval_coverage: Parameter


class SlotConfig(_Section):
    """Hysteresis that keeps a rival identity slot from flapping on noise."""

    hysteresis_s: Parameter
    hold_s: Parameter


class RivalConfig(ConfigDocument):
    """Loaded ``rival-modes-v1.yaml``."""

    transition_matrix_authorship: Literal["hand_authored_prior", "estimated_from_synthetic"]
    transition_matrix_note: str = Field(min_length=1)
    mode_order: tuple[str, ...]
    transition_matrix: tuple[tuple[float, ...], ...]
    filter: FilterConfig
    behaviour: BehaviourConfig
    dynamics: RivalDynamics
    likelihood: RivalLikelihood
    quantiles: QuantileConfig
    slots: SlotConfig

    @model_validator(mode="after")
    def _matrix_is_stochastic_and_ordered(self) -> RivalConfig:
        expected = tuple(mode.value for mode in MODE_ORDER)
        if self.mode_order != expected:
            raise ValueError(f"mode_order must be {expected}, got {self.mode_order}")
        if len(self.transition_matrix) != len(MODE_ORDER):
            raise ValueError("transition matrix must have one row per mode")
        for index, row in enumerate(self.transition_matrix):
            if len(row) != len(MODE_ORDER):
                raise ValueError(f"transition matrix row {index} must have one column per mode")
            if any(p < 0.0 for p in row):
                raise ValueError(f"transition matrix row {index} has a negative probability")
            total = sum(row)
            if abs(total - 1.0) > 1e-9:
                raise ValueError(f"transition matrix row {index} sums to {total!r}, not 1.0")
        dynamics = self.dynamics
        if dynamics.energy_min_j.value >= dynamics.energy_max_j.value:
            raise ValueError("rival legal energy range must have min < max")
        if not (
            dynamics.energy_min_j.value
            <= dynamics.prior_energy_min_j.value
            < dynamics.prior_energy_max_j.value
            <= dynamics.energy_max_j.value
        ):
            raise ValueError("the broad energy prior must sit inside the legal energy range")
        if self.filter.n_particles < len(MODE_ORDER) * self.filter.min_per_mode:
            raise ValueError("particle count cannot honour the per-mode support floor")
        return self

    @property
    def unit_transition(self) -> np.ndarray:
        """The hand-authored matrix as float64, rows indexed by :data:`MODE_ORDER`."""
        return np.array(self.transition_matrix, dtype=np.float64)

    @property
    def is_hand_authored(self) -> bool:
        return self.transition_matrix_authorship == "hand_authored_prior"

    def step_transition(self, dt_s: float) -> np.ndarray:
        """Transition matrix for an elapsed ``dt_s``.

        ``(1 - lam) * I + lam * P`` with ``lam = 1 - exp(-dt / tau)``. Every row
        stays a probability vector for any ``dt >= 0``, and ``dt -> 0`` gives the
        identity, so the mode process does not depend on how the caller chose to
        chunk time.
        """
        if dt_s < 0.0:
            raise ValueError("transition interval cannot be negative")
        tau = self.filter.mode_time_constant_s.value
        lam = 1.0 - float(np.exp(-dt_s / tau))
        identity = np.eye(len(MODE_ORDER), dtype=np.float64)
        return (1.0 - lam) * identity + lam * self.unit_transition


def load_own_car_config(config_id: str = OWN_CAR_CONFIG_ID, *, path: Path | None = None) -> OwnCarConfig:
    payload = load_yaml(path) if path is not None else load_config("estimation", config_id)
    return OwnCarConfig.model_validate(payload)


def load_rival_config(config_id: str = RIVAL_CONFIG_ID, *, path: Path | None = None) -> RivalConfig:
    payload = load_yaml(path) if path is not None else load_config("estimation", config_id)
    config = RivalConfig.model_validate(payload)
    if config.transition_matrix_authorship not in ("hand_authored_prior", "estimated_from_synthetic"):
        raise ValueError("the mode transition matrix must declare its authorship")
    return config


__all__ = [
    "MODE_INDEX",
    "MODE_ORDER",
    "OWN_CAR_CONFIG_ID",
    "RIVAL_CONFIG_ID",
    "BehaviourConfig",
    "DiagnosticsConfig",
    "EnergyNoise",
    "FilterConfig",
    "InitialUncertainty",
    "MeasurementNoise",
    "ModeGains",
    "MotionNoise",
    "OwnCarConfig",
    "QuantileConfig",
    "RivalConfig",
    "RivalDynamics",
    "RivalLikelihood",
    "SlotConfig",
    "load_own_car_config",
    "load_rival_config",
]
