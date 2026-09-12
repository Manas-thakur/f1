from dataclasses import replace

import numpy as np
import pytest

from afterlap_core.race import RaceSession, RaceSettings
from afterlap_core.race.variability import Variability
from afterlap_core.simulation.wake import FREE_AIR, WakeField, WakeModel, nearby_wake_indices


class ReferenceWake(WakeModel):
    pass


def reference_effect(entries, model, car_id, progress, lateral, speed, length):
    own_length = next(entry[4] for entry in entries if entry[0] == car_id)
    strongest = FREE_AIR
    for other_id, other_progress, other_lateral, other_speed, other_length in entries:
        if other_id == car_id:
            continue
        delta = (other_progress - progress) % length
        clearance = 0.5 * (own_length + other_length)
        if not 0 < delta < model.range_m + clearance:
            continue
        effect = model.evaluate(
            separation_m=max(0, delta - clearance),
            lateral_offset_m=lateral - other_lateral,
            relative_speed_mps=other_speed - speed,
            leader_speed_mps=other_speed,
            leader_car_id=other_id,
        )
        shielding = effect.shielding * min(1, delta / clearance) ** 2
        if shielding > strongest.shielding:
            strongest = replace(
                effect,
                shielding=shielding,
                drag_multiplier=1 - model.drag_reduction_max * shielding,
                downforce_multiplier=1 - model.downforce_loss_max * shielding,
            )
    return strongest


def test_cached_wake_field_matches_reference_effects_exactly():
    rng = np.random.default_rng(42)
    for _ in range(30):
        entries = tuple(
            (
                str(i),
                float(rng.uniform(-80, 80)),
                float(rng.uniform(-5, 5)),
                float(rng.uniform(0, 100)),
                float(rng.uniform(3, 7)),
            )
            for i in range(20)
        )
        field = WakeField(entries)
        model = WakeModel(range_m=float(rng.uniform(10, 100)), lateral_scale_m=float(rng.uniform(0.5, 3)))
        for car_id, progress, lateral, speed, _ in entries:
            args = (model, car_id, progress + 1000, lateral, speed, 1000)
            assert field.effect(*args) == reference_effect(entries, *args)


def test_wake_filter_preserves_range_boundaries_and_first_equal_winner():
    boundary = 45.6
    offsets = [
        0,
        np.nextafter(0.0, 1),
        np.nextafter(boundary, 0),
        boundary,
        np.nextafter(boundary, 100),
        1000,
    ]
    bounds = np.asarray([(offset, 5.6) for offset in offsets])
    expected = [i for i in range(1, len(bounds)) if 0 < bounds[i, 0] % 1000 < boundary]
    assert nearby_wake_indices(bounds, 0, 0, 1000, 40).tolist() == expected
    entries = (("first", 20.0, -1.0, 50.0, 5.6), ("own", 0.0, 0.0, 50.0, 5.6), ("last", 20.0, 1.0, 50.0, 5.6))
    assert WakeField(entries).effect(WakeModel(), "own", 0, 0, 50, 1000).leader_car_id == "first"


@pytest.mark.parametrize("offset", [0.0, float("inf"), float("nan")])
@pytest.mark.parametrize("leader_speed", [0.0, 15.0, 50.0, float("nan")])
def test_cached_wake_preserves_unknown_lateral_and_stationary_leaders(offset, leader_speed):
    entries = (("own", 0.0, 0.0, 50.0, 5.6), ("leader", 20.0, offset, leader_speed, 5.6))
    args = (WakeModel(), "own", 0.0, 0.0, 50.0, 1000.0)
    assert WakeField(entries).effect(*args) == reference_effect(entries, *args)


@pytest.mark.parametrize(
    ("circuit", "cars", "preset"),
    [("monaco", 20, "mild"), ("silverstone", 20, "training"), ("monza", 2, "stress")],
)
def test_optimized_wake_preserves_entire_frame_trace_and_checkpoint(circuit, cars, preset):
    settings = RaceSettings(circuit=circuit, cars=cars, seed=42, variability=Variability(preset=preset))
    optimized, reference = RaceSession(settings), RaceSession(settings)
    reference.simulator._wake = ReferenceWake()
    for _ in range(10):
        optimized.advance(0.1)
        reference.advance(0.1)
        assert optimized.frame() == reference.frame()
    assert optimized.simulator.snapshot() == reference.simulator.snapshot()
    saved = optimized.snapshot()
    optimized.advance(0.2)
    expected = optimized.frame()
    optimized.restore(saved)
    optimized.advance(0.2)
    assert optimized.frame() == expected
    assert optimized.simulator._wake_field is None
