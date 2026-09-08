"""The energy-v1 feature contract must match the specification exactly.

The offsets and field order below are transcribed from the table in
``learning/ENVIRONMENT_AND_FEATURES.md``. If the manifest and the
specification disagree, this file is the place the disagreement surfaces —
before a model is trained against the wrong 96 numbers.
"""

from __future__ import annotations

import pytest

from afterlap_core.feature_manifest import (
    ACTION_SIZE,
    ENERGY_V1,
    FEATURE_REVISION,
    LOOKAHEAD_OFFSETS_M,
    OBSERVATION_SIZE,
    VALUE_COUNT,
    build_feature_manifest,
    feature_index,
    feature_names,
)

SPEC_OWN_CAR_ORDER = [
    "own_speed",
    "own_acceleration",
    "lap_fraction",
    "remaining_race_distance",
    "own_energy_mean",
    "own_energy_std",
    "battery_temperature",
    "thermal_headroom",
    "recharge_spent_this_lap",
    "recharge_allowance_remaining",
    "observed_electrical_power",
    "deployment_ceiling",
    "recovery_ceiling",
    "own_observation_age",
    "clock_uncertainty",
    "instruction_hold_remaining",
    "driver_delay_mean",
    "driver_delay_std",
    "tyre_pace_residual",
    "completed_laps",
    "wet_flag",
    "yellow_flag",
    "overtake_eligibility",
    "eligibility_known_flag",
]

SPEC_RIVAL_ORDER = [
    "gap_s",
    "relative_speed",
    "energy_belief_mean",
    "energy_belief_std",
    "pace_bias",
    "pace_uncertainty",
    "conserve_probability",
    "normal_probability",
    "attack_probability",
    "defend_probability",
    "observation_age",
    "present_flag",
]

SPEC_HISTORY_ORDER = [
    "gap_trend_4s",
    "own_depletion_rate_4s",
    "gap_innovation_magnitude",
    "missed_execution_count_8s",
    "last_decoded_budget",
    "last_decoded_reserve_target",
    "time_since_instruction_change",
    "instruction_change_count_8s",
]


def test_shape_matches_the_specification():
    assert VALUE_COUNT == 96
    assert OBSERVATION_SIZE == 192, "values plus an equal-length known-mask block"
    assert ACTION_SIZE == 2
    assert ENERGY_V1.revision == FEATURE_REVISION == "energy-v1"
    assert ENERGY_V1.policy_interval_s == 1.0
    assert ENERGY_V1.preference_window_s == 10.0
    assert len(ENERGY_V1.fields) == 96


def test_own_car_block_is_offsets_zero_to_twentythree_in_order():
    names = feature_names()[0:24]
    assert list(names) == SPEC_OWN_CAR_ORDER


def test_lookahead_block_is_eight_samples_of_five_fields():
    assert LOOKAHEAD_OFFSETS_M == (100, 250, 500, 750, 1000, 1500, 2000, 3000)
    block = feature_names()[24:64]
    assert len(block) == 40

    for sample, distance in enumerate(LOOKAHEAD_OFFSETS_M):
        base = sample * 5
        prefix = f"lookahead_{int(distance)}m"
        assert block[base] == f"{prefix}_distance_ahead"
        assert block[base + 1] == f"{prefix}_curvature"
        assert block[base + 2] == f"{prefix}_grade"
        assert block[base + 3] == f"{prefix}_deployment_ceiling"
        assert block[base + 4] == f"{prefix}_recovery_capacity"


@pytest.mark.parametrize(("slot", "start"), [("ahead", 64), ("behind", 76)])
def test_rival_blocks_have_the_same_twelve_fields(slot, start):
    block = feature_names()[start : start + 12]
    assert list(block) == [f"rival_{slot}_{name}" for name in SPEC_RIVAL_ORDER]


def test_history_block_is_offsets_eightyeight_to_ninetyfive():
    assert list(feature_names()[88:96]) == SPEC_HISTORY_ORDER


def test_indices_are_dense_and_ordered():
    assert [f.index for f in ENERGY_V1.fields] == list(range(96))
    assert len(set(feature_names())) == 96


def test_present_flag_is_never_masked():
    """No rival means present=0 with the mask set: absence is known information."""
    for slot in ("ahead", "behind"):
        field = ENERGY_V1.fields[feature_index(f"rival_{slot}_present_flag")]
        assert field.maskable is False

    for slot in ("ahead", "behind"):
        for name in SPEC_RIVAL_ORDER:
            if name == "present_flag":
                continue
            assert ENERGY_V1.fields[feature_index(f"rival_{slot}_{name}")].maskable is True


def test_probability_and_flag_fields_are_unscaled():
    for name in feature_names():
        field = ENERGY_V1.fields[feature_index(name)]
        if name.endswith(("_probability", "_flag")) or name in ("lap_fraction", "overtake_eligibility"):
            assert field.scale == 1.0, f"{name} must stay in [0,1]"
            assert field.offset == 0.0
            assert field.unit == "1"


def test_temperature_uses_an_offset_so_the_range_is_useful():
    field = ENERGY_V1.fields[feature_index("battery_temperature")]
    assert field.unit == "K"
    assert field.offset == 300.0
    assert field.scale == 40.0
    normalised = (318.0 - field.offset) / field.scale
    assert -1.0 < normalised < 1.0


def test_every_field_has_a_usable_scale_and_clip_range():
    for field in ENERGY_V1.fields:
        assert field.scale != 0.0, field.name
        assert field.clip_low == -5.0 and field.clip_high == 5.0, field.name
        assert field.unit, field.name
        assert field.provenance_note, field.name


def test_rival_energy_fields_document_estimated_provenance():
    for slot in ("ahead", "behind"):
        for suffix in ("energy_belief_mean", "energy_belief_std"):
            field = ENERGY_V1.fields[feature_index(f"rival_{slot}_{suffix}")]
            assert "estimated" in (field.provenance_note or "")
            assert "never measured" in (field.provenance_note or "")


def test_manifest_hash_is_stable_and_change_sensitive():
    first = build_feature_manifest()
    second = build_feature_manifest()
    assert first.content_hash() == second.content_hash()
    assert first.content_hash() == ENERGY_V1.content_hash()

    fields = list(first.fields)
    fields[0], fields[1] = fields[1].revise(index=0), fields[0].revise(index=1)
    reordered = first.revise(fields=tuple(fields))
    assert reordered.content_hash() != first.content_hash()


def test_units_are_si_at_the_domain_boundary():
    """The encoder converts once; the manifest records SI units, not MJ or kW."""
    energy_fields = [f for f in ENERGY_V1.fields if "energy" in f.name or "budget" in f.name]
    assert energy_fields
    for field in energy_fields:
        assert field.unit == "J", f"{field.name} must record joules, not megajoules"

    power_fields = [f for f in ENERGY_V1.fields if "ceiling" in f.name or "power" in f.name]
    assert power_fields
    for field in power_fields:
        assert field.unit == "W", f"{field.name} must record watts, not kilowatts"
