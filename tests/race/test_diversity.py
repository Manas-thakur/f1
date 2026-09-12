import numpy as np
import pytest

from afterlap_core.race import RaceSession, RaceSettings


@pytest.mark.parametrize("circuit_id", ["monza", "silverstone", "monaco", "suzuka"])
def test_seeded_racing_lines_are_distinct_periodic_smooth_and_inside_track(circuit_id):
    settings = RaceSettings(circuit=circuit_id, cars=6, seed=817)
    first = RaceSession(settings)
    replay = RaceSession(settings)
    changed = RaceSession(settings.model_copy(update={"seed": 818}))
    profiles = [driver.racing_line for driver in first.drivers.values() if driver.racing_line is not None]
    assert len(profiles) == settings.cars
    samples = np.linspace(0, first.track.length, 1001)
    values = np.asarray([[profile.target_at(float(s)) for s in samples] for profile in profiles])
    assert np.unique(np.round(values, 6), axis=0).shape[0] == settings.cars
    assert first.manifest()["racing_lines"] == replay.manifest()["racing_lines"]
    assert first.manifest()["racing_lines"] != changed.manifest()["racing_lines"]
    assert np.max(np.abs(values[:, 0] - values[:, -1])) < 1e-9
    assert np.max(np.abs(np.diff(values, axis=1))) < 1
    assert np.max(np.abs(values)) <= 4.75
