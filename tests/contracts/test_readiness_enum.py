"""The contract readiness ladder is a deliberate copy of the domain ladder.

``afterlap_contracts`` is the innermost layer and imports no domain package, so
``TrackReadiness`` restates ``afterlap_core.tracks.package.ReadinessStatus``
rung for rung instead of importing it. Two hand-kept copies drift unless
something fails when they do, and a drifted ladder is not a cosmetic defect:
the catalogue payloads are typed by the contract copy, so a rung the domain can
emit but the contract does not know would turn a working response into a 500.

A test may reach both layers; the package under test may not.
"""

from __future__ import annotations

import pytest

from afterlap_contracts.catalogue import ScenarioSummary, TrackSummary, ValidationSummary
from afterlap_contracts.enums import TrackReadiness
from afterlap_core.tracks.package import ReadinessStatus


def test_the_contract_readiness_ladder_is_the_domain_ladder_rung_for_rung():
    """Same member names, same wire values, same order: one ladder, written twice."""
    assert [(rung.name, rung.value) for rung in TrackReadiness] == [
        (status.name, status.value) for status in ReadinessStatus
    ]


@pytest.mark.parametrize("status", list(ReadinessStatus))
def test_every_rung_the_domain_can_emit_is_accepted_by_the_catalogue_payloads(status):
    """The retyped catalogue fields must accept every value the server can serialise."""
    track = TrackSummary(
        track_id="a-circuit",
        display_name="A Circuit",
        readiness=status.value,
        registry_readiness=status.value,
    )
    scenario = ScenarioSummary(scenario_id="a-scenario", track_readiness=status.value)
    validation = ValidationSummary(status=status.value)

    assert track.readiness is TrackReadiness(status.value)
    assert track.registry_readiness is TrackReadiness(status.value)
    assert scenario.track_readiness is TrackReadiness(status.value)
    assert validation.status is TrackReadiness(status.value)


def test_a_rung_outside_the_ladder_is_refused_rather_than_carried():
    """The ladder is closed: an unknown rung fails at the boundary, not downstream."""
    with pytest.raises(ValueError, match="readiness"):
        TrackSummary(track_id="a-circuit", display_name="A Circuit", readiness="nearly_ready")
