import numpy as np
import pytest

from afterlap_core.race import RaceSession, RaceSettings
from afterlap_core.race.variability import RaceWeather, Variability


@pytest.mark.parametrize(("wetness", "target"), [(0, 1), (1, 0), (0.4, 0.4)])
@pytest.mark.parametrize("preset", ["baseline", "stress"])
def test_vectorized_weather_retains_scalar_field_and_delayed_preview(wetness, target, preset):
    weather = RaceWeather(300, 3, wetness, 1000, Variability(preset=preset, wetness_target=target), 42)
    positions = np.asarray([-10, 0, 20, 510, 1000, 2040], dtype=np.float64)
    for moment in (0, 0.05, 20, 500):
        np.testing.assert_allclose(
            weather.grip_multiplier_array(positions, moment),
            [weather.grip_multiplier(float(position), moment) for position in positions],
            rtol=1e-15,
            atol=1e-15,
        )
        preview = weather.preview_grip_array(positions, moment)
        np.testing.assert_array_equal(
            preview,
            [weather.preview_grip(float(position), moment) for position in positions],
        )
        assert np.all(preview <= weather.grip_multiplier_array(positions, max(0, moment - 0.1)))


def test_braking_preview_ignores_hidden_patch_phases_and_uses_delayed_grip():
    session = RaceSession(
        RaceSettings(cars=1, wetness=0.1, variability=Variability(preset="stress", wetness_target=0.9))
    )
    simulator = session.simulator
    simulator.world.race.session_time_s = 20
    baseline = simulator._envelope_speed("car-01", 100, 0.92)
    weather = session.weather
    actual = weather.grip_multiplier(100, 20)
    weather.phases = tuple(phase + 1 for phase in weather.phases)
    assert weather.grip_multiplier(100, 20) != actual
    assert simulator._envelope_speed("car-01", 100, 0.92) == baseline
    weather.preview_grip_array = None
    assert simulator._envelope_speed("car-01", 100, 0.92) == baseline


def test_uniform_preview_refreshes_after_weather_changes_and_time_rewind():
    weather = RaceWeather(300, 3, 0.1, 1000, Variability(wetness_target=0.9), 42)
    positions = np.zeros((2, 3))
    initial = weather.preview_grip_array(positions, 10)
    assert not initial.flags.writeable
    with pytest.raises(ValueError):
        initial[0, 0] = 0
    for target, patch, moment, shape in [(0.2, 0.1, 20, (3,)), (0.8, 0.2, 0, (2, 3))]:
        weather.target = target
        weather.patch_amplitude = patch
        result = weather.preview_grip_array(np.zeros(shape), moment)
        np.testing.assert_array_equal(result, np.full(shape, weather.preview_grip(0, moment)))
    assert np.all(initial == initial[0, 0])
