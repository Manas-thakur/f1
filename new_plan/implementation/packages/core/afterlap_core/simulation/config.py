"""Simulator configuration documents.

Every physical number is a :class:`~afterlap_core.config.Parameter` carrying a
unit, a source and a verification status. The shipped fixtures are all
``synthetic_assumption``: they make the simulator executable and they are not a
model of any real car, circuit or race. Nothing in this module can promote a
value to ``measured``; only a calibration run against real measurements could,
and no such measurements exist in this package.
"""

from __future__ import annotations

from bisect import bisect_right
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from afterlap_contracts import DeploymentProfile, Provenance

from ..config import ConfigDocument, Parameter, load_config
from ..paths import Paths


class _Frozen(BaseModel):
    """Immutable, strict base for nested configuration records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- #
# Track
# --------------------------------------------------------------------------- #


class TrackCheckpoint(_Frozen):
    """A named location on the centreline with a stable identifier.

    Checkpoint ids are frozen before any result is produced; evaluation compares
    branches at these ids, never at an ad-hoc distance.
    """

    id: str = Field(min_length=1)
    s_m: Parameter
    description: str | None = None


class TrackSegment(_Frozen):
    """One centreline breakpoint.

    Values between breakpoints are interpolated with a smoothstep so curvature
    is continuous and has a continuous first derivative at the nodes; a raw
    piecewise-constant curvature would inject impulsive lateral demand.
    """

    s_m: Parameter
    curvature_inv_m: Parameter
    grade_rad: Parameter
    width_m: Parameter
    mu: Parameter


class _TrackTables:
    """Vectorised interpolation tables derived from a :class:`TrackConfig`."""

    __slots__ = (
        "curvature",
        "curvature_list",
        "grade",
        "grade_list",
        "length_m",
        "mu",
        "mu_list",
        "s",
        "s_list",
        "width",
        "width_list",
    )

    def __init__(self, track: TrackConfig) -> None:
        length = float(track.length_m.value)
        nodes = sorted(track.segments, key=lambda seg: seg.s_m.value)
        self.length_m = length
        # Periodic closure: append the first node shifted by one lap.
        self.s_list = [float(seg.s_m.value) for seg in nodes] + [length]
        self.curvature_list = self._closed([float(seg.curvature_inv_m.value) for seg in nodes])
        self.grade_list = self._closed([float(seg.grade_rad.value) for seg in nodes])
        self.width_list = self._closed([float(seg.width_m.value) for seg in nodes])
        self.mu_list = self._closed([float(seg.mu.value) for seg in nodes])
        self.s = np.asarray(self.s_list, dtype=np.float64)
        self.curvature = np.asarray(self.curvature_list, dtype=np.float64)
        self.grade = np.asarray(self.grade_list, dtype=np.float64)
        self.width = np.asarray(self.width_list, dtype=np.float64)
        self.mu = np.asarray(self.mu_list, dtype=np.float64)

    @staticmethod
    def _closed(values: list[float]) -> list[float]:
        return [*values, values[0]]

    def evaluate(self, table: np.ndarray, s_m: np.ndarray) -> np.ndarray:
        """Vectorised smoothstep interpolation with periodic wrap."""
        s = np.asarray(s_m, dtype=np.float64) % self.length_m
        index = np.clip(np.searchsorted(self.s, s, side="right") - 1, 0, len(self.s) - 2)
        span = self.s[index + 1] - self.s[index]
        t = np.where(span > 0.0, (s - self.s[index]) / np.where(span > 0.0, span, 1.0), 0.0)
        weight = t * t * (3.0 - 2.0 * t)
        return table[index] + weight * (table[index + 1] - table[index])

    def evaluate_scalar(self, values: list[float], s_m: float) -> float:
        """Scalar fast path. Identical arithmetic to :meth:`evaluate`."""
        s = s_m % self.length_m
        index = min(max(bisect_right(self.s_list, s) - 1, 0), len(self.s_list) - 2)
        low = self.s_list[index]
        span = self.s_list[index + 1] - low
        t = (s - low) / span if span > 0.0 else 0.0
        weight = t * t * (3.0 - 2.0 * t)
        return values[index] + weight * (values[index + 1] - values[index])


_TABLE_CACHE: dict[int, tuple[TrackConfig, _TrackTables]] = {}


def _tables_for(track: TrackConfig) -> _TrackTables:
    """Interpolation tables for a track document.

    Keyed by object identity with the document itself held alongside, so a
    reused ``id`` can never return another track's tables. ``lru_cache`` is
    deliberately not used: hashing a Pydantic document on every physics
    evaluation dominated the measured step cost.
    """
    entry = _TABLE_CACHE.get(id(track))
    if entry is not None and entry[0] is track:
        return entry[1]
    if len(_TABLE_CACHE) > 32:
        _TABLE_CACHE.clear()
    tables = _TrackTables(track)
    _TABLE_CACHE[id(track)] = (track, tables)
    return tables


class TrackConfig(ConfigDocument):
    """Centreline geometry, grip envelope and named locations for one circuit."""

    length_m: Parameter
    segments: tuple[TrackSegment, ...] = Field(min_length=2)
    checkpoints: tuple[TrackCheckpoint, ...] = ()
    timing_line_s_m: Parameter
    geometry_provenance: str = Field(
        default="synthetic_sketch",
        description="How the centreline was obtained. Never 'surveyed' for a synthetic fixture.",
    )
    lateral_geometry_surveyed: bool = False

    @model_validator(mode="after")
    def _consistent_geometry(self) -> TrackConfig:
        length = self.length_m.value
        if length <= 0.0:
            raise ValueError("track length must be positive")
        positions = [seg.s_m.value for seg in self.segments]
        if positions != sorted(positions) or len(set(positions)) != len(positions):
            raise ValueError("track segments must have strictly increasing s_m")
        if positions[0] != 0.0:
            raise ValueError("the first track segment must start at s_m = 0")
        if positions[-1] >= length:
            raise ValueError("every segment breakpoint must lie inside [0, length)")
        ids = [cp.id for cp in self.checkpoints]
        if len(set(ids)) != len(ids):
            raise ValueError("checkpoint ids must be unique")
        for checkpoint in self.checkpoints:
            if not 0.0 <= checkpoint.s_m.value < length:
                raise ValueError(f"checkpoint {checkpoint.id} lies outside the lap")
        if not 0.0 <= self.timing_line_s_m.value < length:
            raise ValueError("the timing line must lie inside the lap")
        if self.lateral_geometry_surveyed and self.synthetic:
            raise ValueError("a synthetic track cannot claim surveyed lateral geometry")
        return self

    # -- interpolated queries ------------------------------------------------ #

    def curvature_at(self, s_m: float) -> float:
        """Signed centreline curvature (1/m); positive turns left."""
        tables = _tables_for(self)
        return tables.evaluate_scalar(tables.curvature_list, s_m)

    def grade_at(self, s_m: float) -> float:
        """Road grade in radians; positive is uphill in the direction of travel."""
        tables = _tables_for(self)
        return tables.evaluate_scalar(tables.grade_list, s_m)

    def mu_at(self, s_m: float) -> float:
        """Peak grip coefficient of the surface envelope."""
        tables = _tables_for(self)
        return tables.evaluate_scalar(tables.mu_list, s_m)

    def width_at(self, s_m: float) -> float:
        """Usable track width in metres."""
        tables = _tables_for(self)
        return tables.evaluate_scalar(tables.width_list, s_m)

    def curvature_array(self, s_m: np.ndarray) -> np.ndarray:
        tables = _tables_for(self)
        return np.asarray(tables.evaluate(tables.curvature, s_m), dtype=np.float64)

    def mu_array(self, s_m: np.ndarray) -> np.ndarray:
        tables = _tables_for(self)
        return np.asarray(tables.evaluate(tables.mu, s_m), dtype=np.float64)

    def width_array(self, s_m: np.ndarray) -> np.ndarray:
        tables = _tables_for(self)
        return np.asarray(tables.evaluate(tables.width, s_m), dtype=np.float64)

    def checkpoint(self, checkpoint_id: str) -> TrackCheckpoint:
        for candidate in self.checkpoints:
            if candidate.id == checkpoint_id:
                return candidate
        raise KeyError(f"track {self.id} has no checkpoint {checkpoint_id!r}")

    @property
    def checkpoint_ids(self) -> tuple[str, ...]:
        return tuple(cp.id for cp in self.checkpoints)

    @property
    def length(self) -> float:
        return float(self.length_m.value)


# --------------------------------------------------------------------------- #
# Car
# --------------------------------------------------------------------------- #


class PowerMapPoint(_Frozen):
    """One breakpoint of the internal-combustion shaft-power map."""

    speed_mps: Parameter
    power_w: Parameter


class CarConfig(ConfigDocument):
    """Mass, aerodynamic, powertrain, electrical and thermal parameters."""

    mass_kg: Parameter
    cda_m2: Parameter
    cla_m2: Parameter
    crr: Parameter
    air_density_kgpm3: Parameter

    ice_power_map: tuple[PowerMapPoint, ...] = Field(min_length=2)
    max_tractive_power_w: Parameter
    max_tractive_force_n: Parameter
    drivetrain_efficiency: Parameter
    max_brake_force_n: Parameter

    eta_discharge: Parameter
    eta_charge: Parameter
    battery_energy_min_j: Parameter
    battery_energy_max_j: Parameter
    max_deploy_power_w: Parameter
    max_harvest_power_w: Parameter
    aux_load_w: Parameter
    regen_enabled: bool = True
    regen_share: Parameter

    c_th_j_per_k: Parameter
    h_w_per_k: Parameter
    ambient_temperature_k: Parameter
    derate_start_temperature_k: Parameter
    derate_end_temperature_k: Parameter

    length_m: Parameter
    width_m: Parameter

    @model_validator(mode="after")
    def _consistent_car(self) -> CarConfig:
        if self.battery_energy_min_j.value >= self.battery_energy_max_j.value:
            raise ValueError("battery energy window is empty")
        if not 0.0 < self.eta_discharge.value <= 1.0:
            raise ValueError("eta_discharge must be in (0, 1]")
        if not 0.0 < self.eta_charge.value <= 1.0:
            raise ValueError("eta_charge must be in (0, 1]")
        if self.derate_end_temperature_k.value <= self.derate_start_temperature_k.value:
            raise ValueError("derate end temperature must exceed the start temperature")
        speeds = [point.speed_mps.value for point in self.ice_power_map]
        if speeds != sorted(speeds) or len(set(speeds)) != len(speeds):
            raise ValueError("the ICE power map needs strictly increasing speed breakpoints")
        if self.mass_kg.value <= 0.0:
            raise ValueError("mass must be positive")
        return self

    def ice_power_at(self, speed_mps: float) -> float:
        """Piecewise-linear shaft power with flat extrapolation at both ends."""
        points = self.ice_power_map
        if speed_mps <= points[0].speed_mps.value:
            return float(points[0].power_w.value)
        if speed_mps >= points[-1].speed_mps.value:
            return float(points[-1].power_w.value)
        for low, high in pairwise(points):
            if low.speed_mps.value <= speed_mps <= high.speed_mps.value:
                span = high.speed_mps.value - low.speed_mps.value
                frac = 0.0 if span == 0.0 else (speed_mps - low.speed_mps.value) / span
                return float(low.power_w.value + frac * (high.power_w.value - low.power_w.value))
        return float(points[-1].power_w.value)

    @property
    def downforce_factor_inv_m(self) -> float:
        """``0.5 * rho * ClA / m`` — the 1/m coefficient in the corner-speed law."""
        return 0.5 * self.air_density_kgpm3.value * self.cla_m2.value / self.mass_kg.value


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


class DriverConfig(_Frozen):
    """Human execution model: how late and how imprecisely an action lands."""

    reaction_delay_mean_s: Parameter
    reaction_delay_std_s: Parameter
    execution_jitter_s: Parameter
    line_tracking_gain: Parameter
    braking_envelope_fraction: Parameter

    @model_validator(mode="after")
    def _bounded(self) -> DriverConfig:
        if self.reaction_delay_mean_s.value < 0.0 or self.reaction_delay_std_s.value < 0.0:
            raise ValueError("reaction delay parameters must be non-negative")
        if not 0.0 < self.braking_envelope_fraction.value <= 1.0:
            raise ValueError("braking envelope fraction must be in (0, 1]")
        if self.line_tracking_gain.value <= 0.0:
            raise ValueError("line tracking gain must be positive")
        return self


# --------------------------------------------------------------------------- #
# Scenario
# --------------------------------------------------------------------------- #


class InitialCarState(_Frozen):
    """Initial physical state of one car."""

    progress_m: Parameter
    speed_mps: Parameter
    energy_j: Parameter
    temperature_k: Parameter
    lateral_d_m: Parameter
    profile: DeploymentProfile = DeploymentProfile.NEUTRAL


class PolicySpec(_Frozen):
    """Which frozen opponent policy drives a rival, and with what preferences."""

    kind: str = Field(pattern="^(conserve|normal|attack|defend)$")
    params: dict[str, Parameter] = Field(default_factory=dict)


class ObservationConfig(_Frozen):
    """Sensor pipeline: delay, noise, quantisation and channel availability.

    ``expose_rival_energy=False`` removes the field entirely rather than sending
    a zero or a null: a controller must not be able to distinguish "hidden" from
    "measured as zero".
    """

    delay_s: Parameter
    noise_sigma: dict[str, Parameter] = Field(default_factory=dict)
    quantisation: dict[str, Parameter] = Field(default_factory=dict)
    expose_rival_energy: bool = False
    energy_channel_available: bool = True
    energy_provenance: Provenance = Provenance.SIMULATED
    noise_time_bin_s: Parameter

    @model_validator(mode="after")
    def _non_negative(self) -> ObservationConfig:
        if self.delay_s.value < 0.0:
            raise ValueError("observation delay must be non-negative")
        if self.noise_time_bin_s.value <= 0.0:
            raise ValueError("the noise time bin must be positive")
        for name, sigma in self.noise_sigma.items():
            if sigma.value < 0.0:
                raise ValueError(f"noise sigma for {name} must be non-negative")
        return self


class ScenarioConfig(ConfigDocument):
    """A reproducible initial condition plus its observation and opponent setup."""

    track_id: str = Field(min_length=1)
    cars: dict[str, str] = Field(min_length=1, description="car_id -> car config id")
    ego_car_id: str = Field(min_length=1)
    initial_states: dict[str, InitialCarState]
    drivers: dict[str, DriverConfig]
    opponent_policies: dict[str, PolicySpec] = Field(default_factory=dict)
    observation: ObservationConfig
    seed: int = Field(ge=0)
    evaluation_checkpoints: tuple[str, ...] = ()
    retention_checkpoint_id: str | None = None
    duration_s: Parameter
    gap_ahead_s: Parameter | None = Field(
        default=None,
        description="Provenance of the initial spacing; validated against the initial states.",
    )
    rule_pack: str = "synthetic-pack-v1-unreviewed"
    status_note: str | None = None

    @model_validator(mode="after")
    def _consistent_scenario(self) -> ScenarioConfig:
        car_ids = set(self.cars)
        if self.ego_car_id not in car_ids:
            raise ValueError("ego_car_id must name one of the configured cars")
        if set(self.initial_states) != car_ids:
            raise ValueError("every car needs exactly one initial state")
        if set(self.drivers) != car_ids:
            raise ValueError("every car needs exactly one driver configuration")
        rivals = car_ids - {self.ego_car_id}
        if set(self.opponent_policies) != rivals:
            raise ValueError("every rival needs exactly one opponent policy")
        if self.duration_s.value <= 0.0:
            raise ValueError("scenario duration must be positive")
        if self.gap_ahead_s is not None:
            self._check_gap()
        return self

    def _check_gap(self) -> None:
        """The declared spacing must agree with the declared initial states.

        This keeps the fixture self-describing: the human-readable gap in the
        scenario document cannot silently drift away from the progress values
        the simulator actually starts from.
        """
        assert self.gap_ahead_s is not None
        ego = self.initial_states[self.ego_car_id]
        rivals = [
            state
            for car_id, state in self.initial_states.items()
            if car_id != self.ego_car_id and state.progress_m.value > ego.progress_m.value
        ]
        if not rivals:
            raise ValueError("gap_ahead_s declared but no car starts ahead of the ego car")
        nearest = min(rivals, key=lambda state: state.progress_m.value)
        speed = ego.speed_mps.value
        if speed <= 0.0:
            raise ValueError("gap_ahead_s requires a positive ego speed to be meaningful")
        implied = (nearest.progress_m.value - ego.progress_m.value) / speed
        if abs(implied - self.gap_ahead_s.value) > 1e-6:
            raise ValueError(
                f"declared gap_ahead_s={self.gap_ahead_s.value} disagrees with the initial "
                f"states, which imply {implied}"
            )

    @property
    def rival_ids(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.cars) - {self.ego_car_id}))

    @property
    def car_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.cars))


class ScenarioBundle(_Frozen):
    """A scenario resolved together with the documents it references."""

    scenario: ScenarioConfig
    track: TrackConfig
    car_configs: dict[str, CarConfig]

    @property
    def bundle_hash(self) -> str:
        from ..paths import sha256_json

        return sha256_json(
            {
                "scenario": self.scenario.config_hash,
                "track": self.track.config_hash,
                "cars": {car_id: cfg.config_hash for car_id, cfg in sorted(self.car_configs.items())},
            }
        )


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def load_track(track_id: str, paths: Paths | None = None) -> TrackConfig:
    return TrackConfig.model_validate(load_config("tracks", track_id, paths))


def load_car(car_id: str, paths: Paths | None = None) -> CarConfig:
    return CarConfig.model_validate(load_config("cars", car_id, paths))


def load_scenario(scenario_id: str, paths: Paths | None = None) -> ScenarioConfig:
    return ScenarioConfig.model_validate(load_config("scenarios", scenario_id, paths))


def load_bundle(scenario: str | ScenarioConfig, paths: Paths | None = None) -> ScenarioBundle:
    """Resolve a scenario and every document it references."""
    config = load_scenario(scenario, paths) if isinstance(scenario, str) else scenario
    track = load_track(config.track_id, paths)
    car_configs = {car_id: load_car(cfg_id, paths) for car_id, cfg_id in config.cars.items()}
    missing = [cp for cp in config.evaluation_checkpoints if cp not in track.checkpoint_ids]
    if missing:
        raise ValueError(f"scenario {config.id} evaluates unknown checkpoints {missing}")
    if config.retention_checkpoint_id and config.retention_checkpoint_id not in track.checkpoint_ids:
        raise ValueError(f"scenario {config.id} names an unknown retention checkpoint")
    return ScenarioBundle(scenario=config, track=track, car_configs=car_configs)


def configs_root(paths: Paths | None = None) -> Path:
    return (paths or Paths.default()).configs


def parameter_provenance(document: ConfigDocument) -> dict[str, Any]:
    """Flatten every parameter's verification status for a provenance report."""
    report: dict[str, Any] = {}

    def walk(prefix: str, payload: Any) -> None:
        if isinstance(payload, dict):
            if {"value", "unit", "source", "verification"} <= set(payload):
                report[prefix] = {
                    "unit": payload["unit"],
                    "source": payload["source"],
                    "verification": payload["verification"],
                }
                return
            for key, value in payload.items():
                walk(f"{prefix}.{key}" if prefix else str(key), value)
        elif isinstance(payload, list):
            for index, value in enumerate(payload):
                walk(f"{prefix}[{index}]", value)

    walk("", document.model_dump(mode="json"))
    return report


__all__ = [
    "CarConfig",
    "DriverConfig",
    "InitialCarState",
    "ObservationConfig",
    "PolicySpec",
    "PowerMapPoint",
    "ScenarioBundle",
    "ScenarioConfig",
    "TrackCheckpoint",
    "TrackConfig",
    "TrackSegment",
    "configs_root",
    "load_bundle",
    "load_car",
    "load_scenario",
    "load_track",
    "parameter_provenance",
]
