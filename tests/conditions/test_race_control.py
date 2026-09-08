from __future__ import annotations

import pytest

from afterlap_core.conditions.race_control import FlagPhase, RaceControlInterval, RaceControlTape


def _tape() -> RaceControlTape:
    return RaceControlTape(
        "unit-rc",
        [
            RaceControlInterval(100.0, 160.0, FlagPhase.YELLOW, sector=2),
            RaceControlInterval(120.0, 300.0, FlagPhase.SC),
            RaceControlInterval(500.0, 560.0, FlagPhase.VSC),
        ],
        source="synthetic unit fixture",
        synthetic=True,
    )


def test_most_restrictive_phase_wins_and_intervals_are_half_open():
    tape = _tape()
    assert tape.phase_at(50.0) is FlagPhase.GREEN
    assert tape.phase_at(100.0) is FlagPhase.YELLOW
    assert tape.phase_at(130.0) is FlagPhase.SC
    assert tape.phase_at(300.0) is FlagPhase.GREEN
    assert tape.phase_at(559.9) is FlagPhase.VSC


def test_sector_local_yellow_does_not_apply_elsewhere():
    tape = _tape()
    assert tape.phase_at(110.0, sector=2) is FlagPhase.YELLOW
    assert tape.phase_at(110.0, sector=1) is FlagPhase.GREEN
    assert tape.phase_at(110.0) is FlagPhase.YELLOW, "track-wide reading is the conservative default"


def test_duration_accounting_and_round_trip():
    tape = _tape()
    assert tape.seconds_in(FlagPhase.SC) == 180.0
    assert tape.seconds_in(FlagPhase.RED) == 0.0
    again = RaceControlTape.from_dict(tape.to_dict())
    assert again.content_hash == tape.content_hash


def test_invalid_intervals_are_refused():
    with pytest.raises(ValueError):
        RaceControlInterval(10.0, 10.0, FlagPhase.SC)
    with pytest.raises(ValueError):
        RaceControlInterval(0.0, 10.0, FlagPhase.GREEN)
