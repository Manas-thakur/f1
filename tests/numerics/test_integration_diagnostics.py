import pytest

from afterlap_core.race import RaceSession, RaceSettings
from afterlap_core.race.variability import Variability


@pytest.mark.parametrize(("circuit", "seed"), [("monaco", 42), ("silverstone", 1709133), ("monza", 340829)])
def test_discarded_first_stage_telemetry_preserves_trace_and_checkpoint(circuit, seed, monkeypatch):
    settings = RaceSettings(circuit=circuit, cars=20, seed=seed, variability=Variability(preset="training"))
    optimized, reference = RaceSession(settings), RaceSession(settings)
    evaluate = reference.simulator._evaluate
    calls = 0

    def evaluate_with_diagnostics(*args, **kwargs):
        nonlocal calls
        calls += not kwargs.get("diagnostics", True)
        kwargs["diagnostics"] = True
        return evaluate(*args, **kwargs)

    monkeypatch.setattr(reference.simulator, "_evaluate", evaluate_with_diagnostics)
    for _ in range(10):
        optimized.advance(0.1)
        reference.advance(0.1)
        assert optimized.frame() == reference.frame()
    assert calls > 0
    assert optimized.simulator.snapshot() == reference.simulator.snapshot()
    saved = optimized.snapshot()
    optimized.advance(0.2)
    expected = optimized.frame()
    optimized.restore(saved)
    optimized.advance(0.2)
    assert optimized.frame() == expected


@pytest.mark.parametrize("available_energy_j", [0.0, 0.01, 10.0, 200000.0])
def test_first_stage_deployment_matches_full_ledger_near_energy_floor(available_energy_j, monkeypatch):
    settings = RaceSettings(circuit="silverstone", cars=2, seed=1709133)
    optimized, reference = RaceSession(settings), RaceSession(settings)
    for session in (optimized, reference):
        for ledger in session.simulator.world.ledgers.values():
            ledger.energy_j = ledger.energy_min_j + available_energy_j
    evaluate = reference.simulator._evaluate

    def evaluate_with_full_ledger(*args, **kwargs):
        kwargs["diagnostics"] = True
        return evaluate(*args, **kwargs)

    monkeypatch.setattr(reference.simulator, "_evaluate", evaluate_with_full_ledger)
    for _ in range(3):
        optimized.advance(0.1)
        reference.advance(0.1)
        assert optimized.frame() == reference.frame()
    assert optimized.simulator.snapshot() == reference.simulator.snapshot()
