"""Shared fixtures for the learning tests.

Everything here is synthetic and deterministic. Nothing is a measurement, and
nothing produced by these fixtures may be presented as a trained model.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import numpy as np
import pytest

from afterlap_contracts import (
    SCHEMA_VERSION,
    ApplicableLimits,
    EligibilityState,
    FlagState,
    IntentionWeights,
    IntervalValue,
    Provenance,
    RewardManifest,
    RivalBelief,
    ScalarValue,
    StateEstimate,
    fixtures,
)
from afterlap_core.learning.config import EnvConfig, ValueConfig, load_env_config, load_value_config
from afterlap_core.learning.features import (
    FeatureContext,
    FeatureEncoder,
    HistorySummary,
    LookaheadSample,
)
from afterlap_core.learning.reward import load_reward_manifest

if TYPE_CHECKING:
    from pathlib import Path

TRACK_LENGTH_M = 5_200.0
"""``configs/tracks/test-loop.yaml``. A synthetic sketch, not a surveyed circuit."""

SMOKE_SCENARIO = "two-straight-counterattack"
"""The scenario whose declared starting state gives a resolvable permission."""


@pytest.fixture(scope="session")
def encoder() -> FeatureEncoder:
    return FeatureEncoder()


@pytest.fixture(scope="session")
def reward() -> RewardManifest:
    return load_reward_manifest()


@pytest.fixture(scope="session")
def env_config() -> EnvConfig:
    return load_env_config()


@pytest.fixture(scope="session")
def value_config() -> ValueConfig:
    return load_value_config()


@pytest.fixture
def fast_env_config(env_config: EnvConfig) -> EnvConfig:
    """A short episode limit so an environment test finishes quickly.

    Only the step cap changes. The cadence, the planner mode, the reward and the
    feature contract are the shipped ones, so a test still exercises the real
    environment revision.
    """
    return dataclasses.replace(env_config, max_episode_steps=8)


@pytest.fixture
def limits() -> ApplicableLimits:
    return ApplicableLimits(
        deployment_ceiling_w=350_000.0,
        recovery_ceiling_w=350_000.0,
        battery_energy_min_j=0.0,
        battery_energy_max_j=4_000_000.0,
        recharge_allowance_remaining_j=8_000_000.0,
        max_power_ramp_w_per_s=700_000.0,
        thermal_derate_factor=1.0,
    )


@pytest.fixture
def estimate() -> StateEstimate:
    """The frozen contract fixture: energy known, both rival slots occupied."""
    return fixtures.state_estimate()


def context(**overrides: object) -> FeatureContext:
    """A fully populated feature context, so a test can mask one field at a time."""
    base: dict[str, object] = {
        "track_length_m": TRACK_LENGTH_M,
        "limits_deployment_ceiling_w": 350_000.0,
        "limits_recovery_ceiling_w": 350_000.0,
        "limits_recharge_allowance_remaining_j": 8_000_000.0,
        "thermal_headroom_k": 12.0,
        "instruction_hold_remaining_s": 1.5,
        "driver_delay_mean_s": 0.35,
        "driver_delay_std_s": 0.0,
        "wet_flag": False,
        "lookahead": tuple(
            LookaheadSample(
                distance_ahead_m=float(offset),
                curvature_inv_m=0.001,
                grade_rad=0.0,
                deployment_ceiling_w=350_000.0,
                recovery_capacity_w=350_000.0,
            )
            for offset in (100, 250, 500, 750, 1000, 1500, 2000, 3000)
        ),
        "history": HistorySummary(
            gap_trend_4s=0.05,
            own_depletion_rate_4s_w=120_000.0,
            gap_innovation_magnitude_s=0.01,
            missed_execution_count_8s=0,
            last_decoded_budget_j=500_000.0,
            last_decoded_reserve_target_j=1_200_000.0,
            time_since_instruction_change_s=2.0,
            instruction_change_count_8s=1,
        ),
    }
    base.update(overrides)
    return FeatureContext(**base)  # type: ignore[arg-type]


@pytest.fixture
def feature_context() -> FeatureContext:
    return context()


@pytest.fixture
def empty_context() -> FeatureContext:
    """Everything optional absent, so masks can be checked at their floor."""
    return FeatureContext(track_length_m=TRACK_LENGTH_M)


def rival(
    *,
    slot: str,
    is_ahead: bool,
    gap_s: float,
    energy_known: bool = True,
    pace_known: bool = True,
) -> RivalBelief:
    return RivalBelief(
        car_id=f"car-{slot}",
        slot=slot,
        is_ahead=is_ahead,
        gap_s=ScalarValue(
            value=gap_s,
            unit="s",
            provenance=Provenance.ESTIMATED,
            observed_at_s=12.0,
            age_s=0.2,
            standard_deviation=0.05,
        ),
        gap_m=ScalarValue(value=gap_s * 70.0, unit="m", provenance=Provenance.ESTIMATED),
        relative_speed_mps=ScalarValue(value=0.0, unit="m/s", provenance=Provenance.ESTIMATED),
        energy_interval_j=(
            IntervalValue(
                lower=1_000_000.0,
                upper=3_000_000.0,
                unit="J",
                kind="quantile",
                coverage=0.9,
                provenance=Provenance.ESTIMATED,
            )
            if energy_known
            else None
        ),
        energy_mean_j=(
            ScalarValue(
                value=2_000_000.0,
                unit="J",
                provenance=Provenance.ESTIMATED,
                standard_deviation=400_000.0,
            )
            if energy_known
            else None
        ),
        pace_bias_s_per_lap=(
            ScalarValue(value=0.0, unit="s", provenance=Provenance.ESTIMATED, standard_deviation=0.2)
            if pace_known
            else None
        ),
        intentions=IntentionWeights(conserve=0.25, normal=0.25, attack=0.25, defend=0.25),
        observation_age_s=0.2,
    )


def estimate_with(
    *,
    rivals: tuple[RivalBelief, ...] = (),
    energy_j: float | None = 2_400_000.0,
    energy_capability: bool = True,
    eligibility: EligibilityState = EligibilityState.ELIGIBLE_DETECTED,
    flag_known: bool = True,
    remaining_distance_m: float | None = 2_000.0,
    speed_mps: float | None = 70.0,
    acceleration_mps2: float | None = 0.0,
) -> StateEstimate:
    """Build a hand-controlled estimate so a single field can be made unknown."""
    base = fixtures.state_estimate(energy_j=energy_j, with_rivals=False)
    own = base.own_car.model_copy(
        update={
            "speed_mps": (
                base.own_car.speed_mps.model_copy(update={"value": speed_mps})
                if speed_mps is not None
                else ScalarValue.missing("m/s", Provenance.SIMULATED)
            ),
            "acceleration_mps2": (
                base.own_car.acceleration_mps2.model_copy(update={"value": acceleration_mps2})
                if acceleration_mps2 is not None
                else ScalarValue.missing("m/s^2", Provenance.ESTIMATED)
            ),
        }
    )
    race = base.race_context.model_copy(
        update={
            "eligibility": eligibility,
            "flag_known": flag_known,
            "flag_state": FlagState.GREEN if flag_known else FlagState.UNKNOWN,
            "remaining_distance_m": (
                base.race_context.remaining_distance_m.model_copy(update={"value": remaining_distance_m})
                if remaining_distance_m is not None
                else ScalarValue.missing("m", Provenance.CONFIGURED)
            ),
        }
    )
    quality = base.quality.model_copy(update={"own_energy_capability": energy_capability})
    return StateEstimate(
        schema_version=SCHEMA_VERSION,
        session_id=base.session_id,
        revision=base.revision,
        cutoff_s=base.cutoff_s,
        created_at_s=base.created_at_s,
        own_car=own,
        rival_beliefs=rivals,
        race_context=race,
        quality=quality,
        contributing_event_ids=base.contributing_event_ids,
    )


@pytest.fixture
def bundle_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "bundle"
    directory.mkdir()
    return directory


def constant_actor_state(size: int = 192) -> dict[str, object]:
    """A tiny, deterministic tensor payload standing in for actor weights.

    Labelled synthetic: it is never a trained actor and it is never presented as
    one. It exists so the bundle hashing and loading path can be tested without
    a training run.
    """
    import torch

    generator = torch.Generator().manual_seed(0)
    return {
        "synthetic.linear.weight": torch.randn(4, size, generator=generator),
        "synthetic.linear.bias": torch.zeros(4),
    }


def uniform_policy(seed: int = 0):
    """A named frozen controller: uniform random preferences."""
    rng = np.random.default_rng(seed)

    def policy(_observation: np.ndarray) -> np.ndarray:
        return rng.uniform(-1.0, 1.0, size=2).astype(np.float32)

    return policy


def zero_policy(_observation: np.ndarray) -> np.ndarray:
    """A named frozen controller: the midpoint of every decoded range."""
    return np.zeros(2, dtype=np.float32)
