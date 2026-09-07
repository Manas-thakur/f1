"""The frozen ``energy-v1`` feature contract.

``07_learning/ENVIRONMENT_AND_FEATURES.md`` makes the coordinator responsible
for generating a machine-readable manifest from that specification before
training starts. This module is that generator.

Order, semantics, scaling and mask rules are frozen. Any change here requires a
new revision string and retraining: the manifest hash is embedded in every
model bundle so a mismatch disables the learned contribution rather than
silently feeding a network the wrong 96 numbers.

Layout (96 values, plus a 96-element known-mask block, giving shape ``(192,)``):

===========  ====================================================
Offsets      Contents
===========  ====================================================
0-23         own-car and race context
24-63        eight lookahead samples, five fields each
64-75        nearest relevant rival ahead, twelve fields
76-87        nearest relevant rival behind, the same twelve
88-95        short-horizon history summaries
===========  ====================================================
"""

from __future__ import annotations

from typing import Final

from afterlap_contracts import SCHEMA_VERSION, FeatureField, FeatureManifest

FEATURE_REVISION: Final[str] = "energy-v1"
VALUE_COUNT: Final[int] = 96
OBSERVATION_SIZE: Final[int] = 2 * VALUE_COUNT
ACTION_SIZE: Final[int] = 2
POLICY_INTERVAL_S: Final[float] = 1.0
PREFERENCE_WINDOW_S: Final[float] = 10.0

LOOKAHEAD_OFFSETS_M: Final[tuple[float, ...]] = (100.0, 250.0, 500.0, 750.0, 1000.0, 1500.0, 2000.0, 3000.0)
"""Fixed lookahead sample distances. Track geometry wraps; race completion does not."""

RIVAL_SLOTS: Final[tuple[str, ...]] = ("ahead", "behind")

# Physical scales. Chosen from the supported scenario bounds so a normalised
# value of about 1 is a typical magnitude and clipping at [-5, 5] is generous.
SPEED_SCALE_MPS: Final[float] = 100.0
ACCELERATION_SCALE_MPS2: Final[float] = 20.0
DISTANCE_SCALE_M: Final[float] = 5_000.0
RACE_DISTANCE_SCALE_M: Final[float] = 50_000.0
ENERGY_SCALE_J: Final[float] = 4_000_000.0
ENERGY_SIGMA_SCALE_J: Final[float] = 500_000.0
RECHARGE_SCALE_J: Final[float] = 8_500_000.0
POWER_SCALE_W: Final[float] = 350_000.0
TIME_SCALE_S: Final[float] = 10.0
SHORT_TIME_SCALE_S: Final[float] = 1.0
GAP_SCALE_S: Final[float] = 5.0
CURVATURE_SCALE_INV_M: Final[float] = 0.02
GRADE_SCALE_RAD: Final[float] = 0.1
COUNT_SCALE: Final[float] = 8.0
LAP_SCALE: Final[float] = 60.0
PACE_SCALE_S_PER_LAP: Final[float] = 2.0

# Kelvin uses an offset as well as a scale: a raw 318 K should not normalise to
# 318/scale, which would waste the network's dynamic range on absolute zero.
TEMPERATURE_OFFSET_K: Final[float] = 300.0
TEMPERATURE_SCALE_K: Final[float] = 40.0

_SPEC = "07_learning/ENVIRONMENT_AND_FEATURES.md"


def _field(
    index: int,
    name: str,
    unit: str,
    scale: float,
    *,
    offset: float = 0.0,
    maskable: bool = True,
    note: str | None = None,
) -> FeatureField:
    return FeatureField(
        index=index,
        name=name,
        unit=unit,
        offset=offset,
        scale=scale,
        clip_low=-5.0,
        clip_high=5.0,
        maskable=maskable,
        provenance_note=note or _SPEC,
    )


def _own_car_and_context(start: int) -> list[FeatureField]:
    """Offsets 0-23, in the exact order given by the specification table."""
    unit_scale = 1.0
    entries: list[tuple[str, str, float, float]] = [
        ("own_speed", "m/s", SPEED_SCALE_MPS, 0.0),
        ("own_acceleration", "m/s^2", ACCELERATION_SCALE_MPS2, 0.0),
        ("lap_fraction", "1", unit_scale, 0.0),
        ("remaining_race_distance", "m", RACE_DISTANCE_SCALE_M, 0.0),
        ("own_energy_mean", "J", ENERGY_SCALE_J, 0.0),
        ("own_energy_std", "J", ENERGY_SIGMA_SCALE_J, 0.0),
        ("battery_temperature", "K", TEMPERATURE_SCALE_K, TEMPERATURE_OFFSET_K),
        ("thermal_headroom", "K", TEMPERATURE_SCALE_K, 0.0),
        ("recharge_spent_this_lap", "J", RECHARGE_SCALE_J, 0.0),
        ("recharge_allowance_remaining", "J", RECHARGE_SCALE_J, 0.0),
        ("observed_electrical_power", "W", POWER_SCALE_W, 0.0),
        ("deployment_ceiling", "W", POWER_SCALE_W, 0.0),
        ("recovery_ceiling", "W", POWER_SCALE_W, 0.0),
        ("own_observation_age", "s", SHORT_TIME_SCALE_S, 0.0),
        ("clock_uncertainty", "s", SHORT_TIME_SCALE_S, 0.0),
        ("instruction_hold_remaining", "s", TIME_SCALE_S, 0.0),
        ("driver_delay_mean", "s", SHORT_TIME_SCALE_S, 0.0),
        ("driver_delay_std", "s", SHORT_TIME_SCALE_S, 0.0),
        ("tyre_pace_residual", "s", PACE_SCALE_S_PER_LAP, 0.0),
        ("completed_laps", "1", LAP_SCALE, 0.0),
        ("wet_flag", "1", unit_scale, 0.0),
        ("yellow_flag", "1", unit_scale, 0.0),
        ("overtake_eligibility", "1", unit_scale, 0.0),
        ("eligibility_known_flag", "1", unit_scale, 0.0),
    ]
    return [
        _field(start + i, name, unit, scale, offset=offset)
        for i, (name, unit, scale, offset) in enumerate(entries)
    ]


def _lookahead(start: int) -> list[FeatureField]:
    """Offsets 24-63: eight samples, five fields each, in fixed order."""
    fields: list[FeatureField] = []
    index = start
    for distance in LOOKAHEAD_OFFSETS_M:
        label = f"lookahead_{int(distance)}m"
        for name, unit, scale in (
            ("distance_ahead", "m", DISTANCE_SCALE_M),
            ("curvature", "1/m", CURVATURE_SCALE_INV_M),
            ("grade", "rad", GRADE_SCALE_RAD),
            ("deployment_ceiling", "W", POWER_SCALE_W),
            ("recovery_capacity", "W", POWER_SCALE_W),
        ):
            note = (
                f"{_SPEC}; ceiling derived from currently known context only, "
                "future unknown eligibility stays masked"
                if name == "deployment_ceiling"
                else _SPEC
            )
            fields.append(_field(index, f"{label}_{name}", unit, scale, note=note))
            index += 1
    return fields


def _rival(start: int, slot: str) -> list[FeatureField]:
    """Twelve fields for one stable rival identity slot."""
    entries: list[tuple[str, str, float]] = [
        ("gap_s", "s", GAP_SCALE_S),
        ("relative_speed", "m/s", SPEED_SCALE_MPS),
        ("energy_belief_mean", "J", ENERGY_SCALE_J),
        ("energy_belief_std", "J", ENERGY_SIGMA_SCALE_J),
        ("pace_bias", "s", PACE_SCALE_S_PER_LAP),
        ("pace_uncertainty", "s", PACE_SCALE_S_PER_LAP),
        ("conserve_probability", "1", 1.0),
        ("normal_probability", "1", 1.0),
        ("attack_probability", "1", 1.0),
        ("defend_probability", "1", 1.0),
        ("observation_age", "s", SHORT_TIME_SCALE_S),
        ("present_flag", "1", 1.0),
    ]
    fields: list[FeatureField] = []
    for i, (name, unit, scale) in enumerate(entries):
        note = _SPEC
        if name.startswith("energy_belief"):
            note = f"{_SPEC}; provenance is estimated, never measured battery telemetry"
        if name == "present_flag":
            # The absence of a rival is itself known information, so this flag
            # is never masked: present=0 with mask=1.
            fields.append(_field(start + i, f"rival_{slot}_{name}", unit, scale, maskable=False, note=note))
        else:
            fields.append(_field(start + i, f"rival_{slot}_{name}", unit, scale, note=note))
    return fields


def _history(start: int) -> list[FeatureField]:
    """Offsets 88-95: engineered short-horizon summaries."""
    entries: list[tuple[str, str, float]] = [
        ("gap_trend_4s", "s", GAP_SCALE_S),
        ("own_depletion_rate_4s", "W", POWER_SCALE_W),
        ("gap_innovation_magnitude", "s", GAP_SCALE_S),
        ("missed_execution_count_8s", "1", COUNT_SCALE),
        ("last_decoded_budget", "J", ENERGY_SCALE_J),
        ("last_decoded_reserve_target", "J", ENERGY_SCALE_J),
        ("time_since_instruction_change", "s", TIME_SCALE_S),
        ("instruction_change_count_8s", "1", COUNT_SCALE),
    ]
    return [_field(start + i, name, unit, scale) for i, (name, unit, scale) in enumerate(entries)]


def build_feature_manifest() -> FeatureManifest:
    """Construct the frozen ``energy-v1`` manifest."""
    fields: list[FeatureField] = []
    fields += _own_car_and_context(0)
    fields += _lookahead(24)
    fields += _rival(64, "ahead")
    fields += _rival(76, "behind")
    fields += _history(88)

    if len(fields) != VALUE_COUNT:  # pragma: no cover - guarded by tests
        raise AssertionError(f"expected {VALUE_COUNT} feature fields, built {len(fields)}")

    return FeatureManifest(
        schema_version=SCHEMA_VERSION,
        revision=FEATURE_REVISION,
        value_count=VALUE_COUNT,
        observation_size=OBSERVATION_SIZE,
        fields=tuple(fields),
        action_size=ACTION_SIZE,
        policy_interval_s=POLICY_INTERVAL_S,
        preference_window_s=PREFERENCE_WINDOW_S,
    )


ENERGY_V1: Final[FeatureManifest] = build_feature_manifest()
"""Module-level frozen instance. Its ``content_hash()`` is the feature schema hash."""


def feature_index(name: str) -> int:
    """Look up a field's offset by name, failing loudly on a typo."""
    for field in ENERGY_V1.fields:
        if field.name == name:
            return field.index
    raise KeyError(f"unknown feature {name!r} in revision {FEATURE_REVISION}")


def feature_names() -> tuple[str, ...]:
    return tuple(field.name for field in ENERGY_V1.fields)


__all__ = [
    "ACTION_SIZE",
    "ENERGY_V1",
    "FEATURE_REVISION",
    "LOOKAHEAD_OFFSETS_M",
    "OBSERVATION_SIZE",
    "POLICY_INTERVAL_S",
    "PREFERENCE_WINDOW_S",
    "RIVAL_SLOTS",
    "TEMPERATURE_OFFSET_K",
    "TEMPERATURE_SCALE_K",
    "VALUE_COUNT",
    "build_feature_manifest",
    "feature_index",
    "feature_names",
]
