"""Feature-encoder tests: masks, units, isolation and clipping."""

from __future__ import annotations

import numpy as np
import pytest

from afterlap_contracts import EligibilityState, Provenance, ScalarValue
from afterlap_core.feature_manifest import ENERGY_V1, OBSERVATION_SIZE, VALUE_COUNT, feature_index
from afterlap_core.learning.features import FeatureContext, FeatureEncoder, LookaheadSample

from .conftest import TRACK_LENGTH_M, context, estimate_with, rival


class TestManifestIdentity:
    def test_encoder_hash_is_the_frozen_feature_hash(self, encoder: FeatureEncoder) -> None:
        assert encoder.feature_hash == ENERGY_V1.content_hash()
        assert encoder.revision == "energy-v1"
        assert encoder.observation_size == OBSERVATION_SIZE == 192

    def test_shape_and_dtype(self, encoder: FeatureEncoder) -> None:
        encoded = encoder.encode(estimate_with(), context())
        assert encoded.observation.shape == (192,)
        assert encoded.observation.dtype == np.float32
        assert encoded.values.shape == (VALUE_COUNT,)
        assert encoded.mask.shape == (VALUE_COUNT,)
        np.testing.assert_array_equal(encoded.observation[:96], encoded.values)
        np.testing.assert_array_equal(encoded.observation[96:], encoded.mask)


class TestUnitsByHand:
    """Hand-built vectors: each value is checked against the manifest's own scale."""

    def test_speed_uses_its_declared_scale(self, encoder: FeatureEncoder) -> None:
        encoded = encoder.encode(estimate_with(speed_mps=75.0), context())
        index = feature_index("own_speed")
        assert ENERGY_V1.fields[index].scale == pytest.approx(100.0)
        assert encoded.values[index] == pytest.approx(0.75)
        assert encoded.mask[index] == 1.0

    def test_temperature_uses_offset_and_scale(self, encoder: FeatureEncoder) -> None:
        encoded = encoder.encode(estimate_with(), context())
        index = feature_index("battery_temperature")
        field = ENERGY_V1.fields[index]
        assert field.offset == pytest.approx(300.0)
        assert encoded.values[index] == pytest.approx((318.0 - 300.0) / 40.0)

    def test_energy_is_scaled_by_the_declared_joule_scale(self, encoder: FeatureEncoder) -> None:
        encoded = encoder.encode(estimate_with(energy_j=2_000_000.0), context())
        index = feature_index("own_energy_mean")
        assert encoded.values[index] == pytest.approx(2_000_000.0 / 4_000_000.0)
        assert encoder.denormalise(encoded, "own_energy_mean") == pytest.approx(2_000_000.0)

    def test_lap_fraction_is_dimensionless(self, encoder: FeatureEncoder) -> None:
        encoded = encoder.encode(estimate_with(), context())
        index = feature_index("lap_fraction")
        assert encoded.values[index] == pytest.approx(1_950.0 / TRACK_LENGTH_M)

    def test_gap_sign_convention(self, encoder: FeatureEncoder) -> None:
        ahead = rival(slot="ahead_1", is_ahead=True, gap_s=0.8)
        behind = rival(slot="behind_1", is_ahead=False, gap_s=-1.2)
        encoded = encoder.encode(estimate_with(rivals=(ahead, behind)), context())
        assert encoded.values[feature_index("rival_ahead_gap_s")] > 0.0
        assert encoded.values[feature_index("rival_behind_gap_s")] < 0.0

    def test_gap_sign_is_corrected_even_when_the_belief_disagrees(self, encoder: FeatureEncoder) -> None:
        behind = rival(slot="behind_1", is_ahead=False, gap_s=+1.2)
        encoded = encoder.encode(estimate_with(rivals=(behind,)), context())
        assert encoded.values[feature_index("rival_behind_gap_s")] < 0.0


class TestMasks:
    def test_unknown_is_zero_with_mask_zero(self, encoder: FeatureEncoder) -> None:
        encoded = encoder.encode(estimate_with(speed_mps=None), context())
        index = feature_index("own_speed")
        assert encoded.values[index] == 0.0
        assert encoded.mask[index] == 0.0

    def test_known_zero_is_zero_with_mask_one(self, encoder: FeatureEncoder) -> None:
        encoded = encoder.encode(estimate_with(acceleration_mps2=0.0), context())
        index = feature_index("own_acceleration")
        assert encoded.values[index] == 0.0
        assert encoded.mask[index] == 1.0

    def test_a_known_zero_and_an_unknown_are_distinguishable(self, encoder: FeatureEncoder) -> None:
        known = encoder.encode(estimate_with(acceleration_mps2=0.0), context())
        unknown = encoder.encode(estimate_with(acceleration_mps2=None), context())
        index = feature_index("own_acceleration")
        assert known.values[index] == unknown.values[index] == 0.0
        assert known.mask[index] != unknown.mask[index]

    def test_absent_rival_is_present_zero_with_mask_one(self, encoder: FeatureEncoder) -> None:
        encoded = encoder.encode(estimate_with(rivals=()), context())
        present = feature_index("rival_ahead_present_flag")
        assert encoded.values[present] == 0.0
        assert encoded.mask[present] == 1.0
        for name in ("gap_s", "relative_speed", "energy_belief_mean", "conserve_probability"):
            index = feature_index(f"rival_ahead_{name}")
            assert encoded.values[index] == 0.0
            assert encoded.mask[index] == 0.0

    def test_present_flag_is_never_maskable_in_the_manifest(self) -> None:
        for slot in ("ahead", "behind"):
            field = ENERGY_V1.fields[feature_index(f"rival_{slot}_present_flag")]
            assert field.maskable is False

    def test_present_rival_sets_the_flag_and_the_summaries(self, encoder: FeatureEncoder) -> None:
        encoded = encoder.encode(
            estimate_with(rivals=(rival(slot="ahead_1", is_ahead=True, gap_s=0.9),)), context()
        )
        assert encoded.values[feature_index("rival_ahead_present_flag")] == 1.0
        assert encoded.mask[feature_index("rival_ahead_energy_belief_mean")] == 1.0
        assert encoded.mask[feature_index("rival_ahead_energy_belief_std")] == 1.0

    def test_missing_rival_energy_prior_is_masked_not_zeroed(self, encoder: FeatureEncoder) -> None:
        without = rival(slot="ahead_1", is_ahead=True, gap_s=0.9, energy_known=False)
        encoded = encoder.encode(estimate_with(rivals=(without,)), context())
        assert encoded.values[feature_index("rival_ahead_present_flag")] == 1.0
        assert encoded.mask[feature_index("rival_ahead_energy_belief_mean")] == 0.0
        assert encoded.values[feature_index("rival_ahead_energy_belief_mean")] == 0.0
        assert encoded.mask[feature_index("rival_ahead_gap_s")] == 1.0

    def test_unresolved_eligibility_masks_the_value_but_not_the_known_flag(
        self, encoder: FeatureEncoder
    ) -> None:
        encoded = encoder.encode(estimate_with(eligibility=EligibilityState.UNKNOWN), context())
        value = feature_index("overtake_eligibility")
        known = feature_index("eligibility_known_flag")
        assert encoded.mask[value] == 0.0
        assert encoded.mask[known] == 1.0
        assert encoded.values[known] == 0.0

        resolved = encoder.encode(estimate_with(eligibility=EligibilityState.ACTIVE), context())
        assert resolved.mask[value] == 1.0
        assert resolved.values[value] == 1.0
        assert resolved.values[known] == 1.0

    def test_unknown_flag_state_masks_the_yellow_flag(self, encoder: FeatureEncoder) -> None:
        encoded = encoder.encode(estimate_with(flag_known=False), context())
        assert encoded.mask[feature_index("yellow_flag")] == 0.0

    def test_no_energy_capability_masks_energy_even_with_a_value(self, encoder: FeatureEncoder) -> None:
        estimate = estimate_with(energy_j=2_000_000.0, energy_capability=False)
        encoded = encoder.encode(estimate, context())
        assert encoded.mask[feature_index("own_energy_mean")] == 0.0
        assert encoded.values[feature_index("own_energy_mean")] == 0.0

    def test_lookahead_beyond_the_finish_is_masked(self, encoder: FeatureEncoder) -> None:
        samples = tuple(
            LookaheadSample(
                distance_ahead_m=float(offset),
                curvature_inv_m=0.001,
                grade_rad=0.0,
                beyond_finish=offset > 500,
            )
            for offset in (100, 250, 500, 750, 1000, 1500, 2000, 3000)
        )
        encoded = encoder.encode(estimate_with(), context(lookahead=samples))
        assert encoded.mask[feature_index("lookahead_500m_curvature")] == 1.0
        assert encoded.mask[feature_index("lookahead_750m_curvature")] == 0.0
        assert encoded.values[feature_index("lookahead_3000m_grade")] == 0.0

    def test_an_empty_context_masks_every_optional_field(self, encoder: FeatureEncoder) -> None:
        encoded = encoder.encode(estimate_with(), FeatureContext(track_length_m=TRACK_LENGTH_M))
        for name in (
            "thermal_headroom",
            "instruction_hold_remaining",
            "driver_delay_mean",
            "wet_flag",
            "deployment_ceiling",
            "lookahead_100m_curvature",
            "gap_trend_4s",
        ):
            assert encoded.mask[feature_index(name)] == 0.0, name


class TestNumericalSafety:
    def test_no_nan_or_infinity_reaches_the_network(self, encoder: FeatureEncoder) -> None:
        encoded = encoder.encode(estimate_with(), context())
        assert np.all(np.isfinite(encoded.observation))

    def test_a_non_finite_raw_value_becomes_unknown_and_is_counted(self, encoder: FeatureEncoder) -> None:
        estimate = estimate_with()
        broken = estimate.own_car.model_copy(
            update={"speed_mps": ScalarValue(value=float("inf"), unit="m/s", provenance=Provenance.SIMULATED)}
        )
        encoded = encoder.encode(estimate.model_copy(update={"own_car": broken}), context())
        index = feature_index("own_speed")
        assert np.all(np.isfinite(encoded.observation))
        assert encoded.mask[index] == 0.0
        assert encoded.values[index] == 0.0
        assert index in encoded.non_finite_indices

    def test_clipping_is_applied_and_the_pre_clip_value_is_logged(self, encoder: FeatureEncoder) -> None:
        encoded = encoder.encode(estimate_with(speed_mps=900.0), context())
        index = feature_index("own_speed")
        assert encoded.values[index] == pytest.approx(5.0)
        assert encoded.pre_clip_values[index] == pytest.approx(9.0)
        assert index in encoded.clipped_indices
        assert encoded.clip_count == 1
        assert "own_speed" in encoded.clipped_names()

    def test_clip_diagnostics_are_reported(self, encoder: FeatureEncoder) -> None:
        encoded = encoder.encode(estimate_with(speed_mps=900.0), context())
        diagnostics = encoded.diagnostics()
        assert diagnostics["clip_count"] == 1
        assert 0.0 < diagnostics["clip_fraction"] < 1.0
        assert diagnostics["max_abs_pre_clip"] >= 9.0

    def test_an_in_range_encoding_clips_nothing(self, encoder: FeatureEncoder) -> None:
        encoded = encoder.encode(estimate_with(), context())
        assert encoded.clip_count == 0
        assert encoded.clipped_indices == ()


class TestTruthMutation:
    """Altering hidden simulator state leaves the encoded vector byte-identical."""

    def test_encoding_depends_only_on_the_estimate_and_context(self, encoder: FeatureEncoder) -> None:
        estimate = estimate_with(rivals=(rival(slot="ahead_1", is_ahead=True, gap_s=0.9),))
        first = encoder.encode(estimate, context())
        second = encoder.encode(estimate, context())
        assert first.observation.tobytes() == second.observation.tobytes()

    def test_mutating_hidden_simulator_truth_changes_nothing(self) -> None:
        from afterlap_core.learning.env import AfterlapEnv

        env = AfterlapEnv(scenario_id="two-straight-counterattack")
        observation, _ = env.reset(seed=5, options={"scenario_seed": 11})
        before = observation.tobytes()
        encoded_before = env.encoded
        assert encoded_before is not None

        world = env.simulator.world
        ego = "own"
        for car_id, state in world.cars.items():
            if car_id == ego:
                continue
            state.battery_energy_j = 42.0
            state.battery_temperature_k = 400.0
            state.recharge_ledger_j = 12_345.0
        for car_id, ledger in world.ledgers.items():
            if car_id != ego:
                ledger.energy_j = 42.0

        tick = env.tick
        assert tick is not None
        again = env.encoder.encode(tick.estimate, tick.feature_context)
        assert again.observation.tobytes() == before

    def test_a_second_encoder_instance_agrees_byte_for_byte(self) -> None:
        estimate = estimate_with(rivals=(rival(slot="behind_1", is_ahead=False, gap_s=-1.0),))
        left = FeatureEncoder().encode(estimate, context())
        right = FeatureEncoder().encode(estimate, context())
        assert left.observation.tobytes() == right.observation.tobytes()
        assert left.feature_hash == right.feature_hash
