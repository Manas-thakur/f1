"""Adapters declare what they can actually do, and refuse to fabricate the rest."""

from __future__ import annotations

import pytest
from conftest import PUBLIC_SOURCE, SYNTHETIC_FIXTURE_NOTICE, observation, public_row, write_public_archive

from afterlap_contracts import CapabilityState, EligibilityState, Provenance, SessionMode, is_registered
from afterlap_contracts.fixtures import session_manifest
from afterlap_core.data import (
    PUBLIC_SAMPLE_RATE_HZ,
    AdapterError,
    FeedUnavailableError,
    FieldMapping,
    ListObservationSource,
    MappingError,
    MappingTable,
    ObservationRecord,
    PublicReplayAdapter,
    SimulatorAdapter,
    SourceAdapter,
    SyntheticTeamFeedAdapter,
    TeamFeedAdapter,
    TeamFeedAuthorisation,
    TruthLeakError,
    public_replay_capability,
    public_replay_mapping,
    request_channel,
    simulator_capability,
    simulator_mapping,
    validate_mapping_against_capability,
)

MANIFEST = session_manifest()


def _archive(tmp_path, rows=None):
    rows = rows or [public_row(10.0 + i * 0.27, 250.0 + i) for i in range(5)]
    return write_public_archive(tmp_path / "public" / "session.json", rows)


# -- public replay ----------------------------------------------------------


def test_public_replay_declares_no_battery_energy_and_unreliable_lateral_placement(tmp_path):
    adapter = PublicReplayAdapter(_archive(tmp_path))
    capability = adapter.capabilities()

    assert capability.mode is SessionMode.REPLAY
    assert not capability.provides("battery_energy_j")
    assert not capability.provides("electrical_power_w")
    assert not capability.provides("lateral_position_m")
    assert "battery-energy" in " ".join(capability.limitations)
    assert "lateral placement" in " ".join(capability.limitations)
    assert capability.license_note and "openf1" in capability.license_note.lower()


def test_public_replay_does_not_advertise_20_hz(tmp_path):
    adapter = PublicReplayAdapter(_archive(tmp_path))
    rates = adapter.capabilities().update_rates_hz
    assert rates == {"speed_mps": PUBLIC_SAMPLE_RATE_HZ}
    assert all(rate < 5.0 for rate in rates.values())
    assert "3.7 Hz" in " ".join(adapter.capabilities().limitations)


def test_requesting_an_unsupported_capability_yields_unavailable_never_a_value(tmp_path):
    adapter = PublicReplayAdapter(_archive(tmp_path))
    answer = adapter.request("battery_energy_j")
    assert answer.state is CapabilityState.UNAVAILABLE
    assert answer.available is False
    assert answer.value is None
    assert "does not supply" in answer.reason

    supported = adapter.request("speed_mps")
    assert supported.state is CapabilityState.AVAILABLE
    assert supported.expected_rate_hz == pytest.approx(PUBLIC_SAMPLE_RATE_HZ)


def test_request_channel_reports_supported_but_unmeasured_as_degraded():
    adapter = SyntheticTeamFeedAdapter([], acknowledged_synthetic=True)
    answer = request_channel(adapter.capabilities(), "battery_energy_j")
    assert answer.state is CapabilityState.DEGRADED
    assert answer.measured is False
    assert answer.value is None


def test_public_replay_open_is_unavailable_when_the_local_archive_is_missing(tmp_path):
    adapter = PublicReplayAdapter(tmp_path / "does-not-exist.json")
    result = adapter.open(MANIFEST)
    assert result.state is CapabilityState.UNAVAILABLE
    assert result.available is False
    assert "does not exist" in result.detail
    # No network fallback exists, so no events can be produced either.
    with pytest.raises(AdapterError):
        list(adapter.events())


def test_public_replay_reads_local_json_and_leaves_vendor_extras_raw(tmp_path):
    adapter = PublicReplayAdapter(_archive(tmp_path))
    result = adapter.open(MANIFEST)
    assert result.state is CapabilityState.DEGRADED
    records = list(adapter.events())
    assert len(records) == 5
    assert records[0].car_id == "1"
    assert records[0].fields["speed"] == 250.0
    assert records[0].fields["drs"] == 12
    assert records[0].source_time_utc == "2026-09-08T12:00:00+00:00"


def test_public_replay_reads_local_parquet(tmp_path):
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    rows = [public_row(10.0 + i * 0.27, 250.0 + i) for i in range(3)]
    path = tmp_path / "session.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path)
    adapter = PublicReplayAdapter(path)
    adapter.open(MANIFEST)
    records = list(adapter.events())
    assert [r.source_sequence for r in records] == [0, 1, 2]
    assert records[2].fields["speed"] == 252.0


# -- DRS must not become 2026 Overtake eligibility --------------------------


def test_a_drs_style_historical_field_is_not_mapped_to_overtake_eligibility(tmp_path):
    mapping = public_replay_mapping(PUBLIC_SOURCE)

    # It is not mapped to any canonical channel.
    assert not mapping.is_mapped("drs")
    assert mapping.is_forbidden("drs")

    # Asking for its mapping fails loudly rather than returning something plausible.
    with pytest.raises(MappingError) as excinfo:
        mapping.get("drs")
    assert "2026 Overtake eligibility" in str(excinfo.value)

    # There is no eligibility channel in the registry at all: eligibility is a
    # rules-engine state machine, not a telemetry channel.
    for name in ("overtake_eligible", "overtake_eligibility", "drs", "drs_active"):
        assert not is_registered(name)
    assert set(EligibilityState) >= {EligibilityState.UNKNOWN, EligibilityState.ELIGIBLE_DETECTED}

    # A table that tried to map it would not even construct.
    with pytest.raises(MappingError):
        MappingTable(
            mapping_revision="bad-1",
            source_id=PUBLIC_SOURCE,
            entries=(FieldMapping("drs", "speed_mps", "km/h"),),
            forbidden_fields={"drs": "historical DRS state is not 2026 Overtake eligibility"},
        )
    with pytest.raises(MappingError):
        FieldMapping("drs", "overtake_eligible", "1")


def test_ingesting_a_drs_field_archives_it_without_producing_a_channel(tmp_path):
    from conftest import public_config

    from afterlap_core.data import IngestionPipeline

    pipeline = IngestionPipeline(public_config(reorder_window_s=0.0))
    output = pipeline.ingest_all(
        [
            observation(
                0,
                10.0,
                {"speed": 250.0, "driver_number": 1, "drs": 12},
                source_id=PUBLIC_SOURCE,
                received_time_s=10.0,
            )
        ]
    )
    assert {r.event.channel for r in output.normalised} == {"speed_mps"}
    assert output.raw[0].fields["drs"] == 12


# -- team feed --------------------------------------------------------------


def test_team_feed_without_authorisation_reports_unavailable_and_yields_nothing():
    adapter = TeamFeedAdapter()
    result = adapter.open(MANIFEST)
    assert result.state is CapabilityState.UNAVAILABLE
    assert result.available is False
    assert "no authorised feed" in result.detail
    assert list(adapter.events()) == []
    assert adapter.capabilities().supported_channels == ()
    assert adapter.unavailable_reason


def test_team_feed_with_unreviewed_field_definitions_is_still_unavailable():
    adapter = TeamFeedAdapter(
        authorisation=TeamFeedAuthorisation(
            feed_id="feed-1",
            endpoint="https://example.invalid/feed",
            credential_ref="secretstore://team-feed",
            terms_review_status="approved",
            field_definitions_reviewed=False,
        )
    )
    result = adapter.open(MANIFEST)
    assert result.state is CapabilityState.UNAVAILABLE
    assert "field definitions" in result.detail
    assert list(adapter.events()) == []


def test_team_feed_with_authorisation_refuses_to_invent_a_transport():
    adapter = TeamFeedAdapter(
        authorisation=TeamFeedAuthorisation(
            feed_id="feed-1",
            endpoint="https://example.invalid/feed",
            credential_ref="secretstore://team-feed",
            terms_review_status="approved",
            field_definitions_reviewed=True,
        )
    )
    result = adapter.open(MANIFEST)
    assert result.state is CapabilityState.AVAILABLE
    with pytest.raises(FeedUnavailableError):
        list(adapter.events())


def test_the_synthetic_team_feed_must_be_acknowledged_and_is_labelled_synthetic():
    with pytest.raises(AdapterError):
        SyntheticTeamFeedAdapter([], acknowledged_synthetic=False)

    adapter = SyntheticTeamFeedAdapter(
        [
            ObservationRecord(
                source_id="team-feed-synthetic",
                car_id="car-01",
                source_time_s=1.0,
                source_sequence=0,
                fields={"vcar": 250.0, "ers_store": 2.4, "ers_power": 120.0},
            )
        ],
        acknowledged_synthetic=True,
    )
    capability = adapter.capabilities()
    assert adapter.provenance is Provenance.SIMULATED
    assert capability.mode is SessionMode.SIMULATION
    assert capability.measured_channels == ()
    assert SYNTHETIC_FIXTURE_NOTICE not in capability.limitations  # it carries the contract's notice
    assert any("synthetic" in note.lower() for note in capability.limitations)

    adapter.open(MANIFEST)
    records = list(adapter.events())
    assert len(records) == 1


# -- simulator --------------------------------------------------------------


def test_simulator_adapter_only_accepts_an_observation_source():
    source = ListObservationSource(
        capability=simulator_capability(),
        records=[observation(0, 1.0, {"speed_mps": 70.0})],
    )
    adapter = SimulatorAdapter(source)
    assert adapter.provenance is Provenance.SIMULATED
    assert adapter.capabilities().mode is SessionMode.SIMULATION
    adapter.open(MANIFEST)
    assert len(list(adapter.events())) == 1


def test_simulator_adapter_accepts_a_plain_factory_or_iterable():
    records = [observation(0, 1.0, {"speed_mps": 70.0})]
    capability = simulator_capability()
    for source in (records, lambda: iter(records)):
        adapter = SimulatorAdapter(source, capability=capability)
        adapter.open(MANIFEST)
        assert len(list(adapter.events())) == 1


def test_simulator_adapter_refuses_hidden_truth_fields():
    source = ListObservationSource(
        capability=simulator_capability(),
        records=[
            ObservationRecord(
                source_id="simulator",
                car_id="car-01",
                source_time_s=1.0,
                source_sequence=0,
                fields={"speed_mps": 70.0, "truth_rival_energy_j": 2_400_000.0},
            )
        ],
    )
    adapter = SimulatorAdapter(source)
    adapter.open(MANIFEST)
    with pytest.raises(TruthLeakError):
        list(adapter.events())


def test_simulator_adapter_refuses_a_non_simulation_capability():
    with pytest.raises(AdapterError):
        SimulatorAdapter([], capability=public_replay_capability("simulator"))


def test_adapter_must_be_opened_before_events_are_consumed():
    adapter = SimulatorAdapter([], capability=simulator_capability())
    with pytest.raises(AdapterError):
        list(adapter.events())


def test_all_three_adapters_satisfy_the_source_adapter_protocol(tmp_path):
    adapters = [
        SimulatorAdapter([], capability=simulator_capability()),
        PublicReplayAdapter(_archive(tmp_path)),
        TeamFeedAdapter(),
        SyntheticTeamFeedAdapter([], acknowledged_synthetic=True),
    ]
    for adapter in adapters:
        assert isinstance(adapter, SourceAdapter)
        assert adapter.capabilities().source_id
        assert adapter.mapping_revision


def test_mapping_tables_only_produce_channels_their_capability_declares():
    validate_mapping_against_capability(simulator_capability(), simulator_mapping())
    validate_mapping_against_capability(public_replay_capability(), public_replay_mapping())

    with pytest.raises(MappingError):
        validate_mapping_against_capability(public_replay_capability(), simulator_mapping("public-replay"))


def test_every_mapping_entry_declares_a_registered_channel_and_a_known_unit():
    for mapping in (simulator_mapping(), public_replay_mapping()):
        assert mapping.mapping_revision
        for entry in mapping.entries:
            assert is_registered(entry.channel)
            assert entry.si_unit
    with pytest.raises(MappingError):
        FieldMapping("speed", "speed_mps", "furlongs/fortnight")
