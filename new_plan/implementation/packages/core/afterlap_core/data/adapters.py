"""Source adapters: simulator observations, public archive replay, team feed.

Every adapter implements the same four methods -- ``capabilities()``,
``open(manifest)``, ``events()``, ``close()`` -- and owns exactly one versioned
:class:`~afterlap_core.data.mapping.MappingTable`. Adapters do not normalise,
deduplicate or timestamp; they produce :class:`ObservationRecord` values and the
pipeline does the rest.

Three honesty rules are structural rather than advisory:

* :class:`SimulatorAdapter` is only ever handed an observation source and only
  ever calls its observation method. It holds no reference to a world state, and
  it rejects any record carrying a hidden-truth field, so a truth value cannot
  reach the controller path even if the object it was handed exposes one.
* :class:`PublicReplayAdapter` declares what a public feed actually provides:
  approximately 3.7 Hz car data, no battery-energy channel, and no reliable
  lateral placement. It never advertises 20 Hz and never maps a historical DRS
  flag onto 2026 Overtake eligibility.
* :class:`TeamFeedAdapter` without an authorised feed returns an explicit
  ``CapabilityState.UNAVAILABLE`` and yields no events. The synthetic
  implementation is labelled synthetic in its own capability record.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

from afterlap_contracts import (
    CapabilityState,
    Provenance,
    SessionManifest,
    SessionMode,
    SourceCapability,
)
from afterlap_contracts.fixtures import SYNTHETIC_NOTICE

from .mapping import FieldMapping, MappingError, MappingTable, find_truth_leaks

OPENF1_LICENSE_NOTE = (
    "Public reference archive in the shape of the OpenF1 car-data schema (source register D01, "
    "https://openf1.org/docs/). Terms review status is recorded in the acquisition manifest; "
    "fixtures shipped with this repository are synthetic and are not redistributed OpenF1 data."
)


class AdapterError(RuntimeError):
    """An adapter was used incorrectly, or a feed is not usable."""


class TruthLeakError(AdapterError):
    """An observation stream carried a field that belongs to simulator truth."""


class FeedUnavailableError(AdapterError):
    """No authorised feed is configured; nothing may be fabricated in its place."""


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    """One vendor packet as it left the source.

    This is the single ingestion unit: an observation source produces them, an
    adapter yields them, and the pipeline consumes them. Values are still in
    vendor units and vendor names.

    ``source_sequence`` must be monotonic within an epoch. ``restart_marker``
    marks the first record after the source restarted its sequence counter; see
    :class:`~afterlap_core.data.pipeline.DeduplicationIndex` for why both are
    needed to stop a restart replaying old packets as new ones.
    """

    source_id: str
    car_id: str
    source_time_s: float
    source_sequence: int
    fields: Mapping[str, Any]
    received_time_s: float | None = None
    restart_marker: bool = False
    source_time_utc: str | None = None

    def field_names(self) -> tuple[str, ...]:
        return tuple(self.fields)


@runtime_checkable
class ObservationSource(Protocol):
    """What a simulator must expose to be ingestible.

    This is the whole contract between :class:`SimulatorAdapter` and a
    simulator. It is deliberately narrow: a source that satisfies it cannot hand
    the adapter a world state, an opponent's true energy, or an RNG stream.
    """

    def observation_capability(self) -> SourceCapability:
        """Declare what this stream actually observes."""

    def observations(self) -> Iterable[ObservationRecord]:
        """Yield observation records in source order."""


ObservationFactory = Callable[[], Iterable[ObservationRecord]]


@dataclass(frozen=True, slots=True)
class AdapterOpenResult:
    """Outcome of ``open()``: available, degraded, or explicitly unavailable."""

    source_id: str
    state: CapabilityState
    capability: SourceCapability
    detail: str | None = None

    @property
    def available(self) -> bool:
        return self.state is not CapabilityState.UNAVAILABLE


@dataclass(frozen=True, slots=True)
class CapabilityAnswer:
    """Answer to 'can this source give me channel X?'.

    ``value`` is always ``None``: an unsupported capability yields an explicit
    unavailable answer, never a fabricated number.
    """

    channel: str
    state: CapabilityState
    reason: str
    expected_rate_hz: float | None = None
    measured: bool = False
    value: None = None

    @property
    def available(self) -> bool:
        return self.state is CapabilityState.AVAILABLE


def request_channel(capability: SourceCapability, channel: str) -> CapabilityAnswer:
    """Ask a capability record for one channel without ever inventing a value."""
    if not capability.provides(channel):
        return CapabilityAnswer(
            channel=channel,
            state=CapabilityState.UNAVAILABLE,
            reason=(
                f"source {capability.source_id!r} does not supply {channel!r}; "
                f"declared limitations: {'; '.join(capability.limitations) or 'none'}"
            ),
        )
    rate = capability.update_rates_hz.get(channel)
    measured = capability.measures(channel)
    if not measured:
        return CapabilityAnswer(
            channel=channel,
            state=CapabilityState.DEGRADED,
            reason=f"{channel!r} is supported but not measured by {capability.source_id!r}",
            expected_rate_hz=rate,
            measured=False,
        )
    return CapabilityAnswer(
        channel=channel,
        state=CapabilityState.AVAILABLE,
        reason=f"{channel!r} is measured at {rate} Hz",
        expected_rate_hz=rate,
        measured=True,
    )


@runtime_checkable
class SourceAdapter(Protocol):
    """The four-method adapter contract from the data specification."""

    def capabilities(self) -> SourceCapability: ...

    def open(self, manifest: SessionManifest) -> AdapterOpenResult: ...

    def events(self) -> Iterator[ObservationRecord]: ...

    def close(self) -> None: ...


class _BaseAdapter:
    """Shared open/close bookkeeping and mapping access."""

    provenance: Provenance = Provenance.MEASURED

    def __init__(self, capability: SourceCapability, mapping: MappingTable) -> None:
        if mapping.source_id != capability.source_id:
            raise AdapterError(
                f"mapping table is for {mapping.source_id!r} but capability is for {capability.source_id!r}"
            )
        self._capability = capability
        self._mapping = mapping
        self._opened = False
        self._manifest: SessionManifest | None = None

    @property
    def source_id(self) -> str:
        return self._capability.source_id

    @property
    def mapping_revision(self) -> str:
        return self._mapping.mapping_revision

    def mapping(self) -> MappingTable:
        return self._mapping

    def capabilities(self) -> SourceCapability:
        return self._capability

    def request(self, channel: str) -> CapabilityAnswer:
        return request_channel(self._capability, channel)

    def open(self, manifest: SessionManifest) -> AdapterOpenResult:
        self._manifest = manifest
        self._opened = True
        return AdapterOpenResult(
            source_id=self.source_id,
            state=CapabilityState.AVAILABLE,
            capability=self._capability,
        )

    def close(self) -> None:
        self._opened = False

    def _require_open(self) -> None:
        if not self._opened:
            raise AdapterError(f"adapter {self.source_id!r} must be opened before events() is consumed")

    def _validate_record(self, record: ObservationRecord) -> ObservationRecord:
        if record.source_id != self.source_id:
            raise AdapterError(
                f"record claims source {record.source_id!r} but this adapter is {self.source_id!r}"
            )
        leaks = find_truth_leaks(record.field_names())
        if leaks:
            raise TruthLeakError(
                f"observation record from {record.source_id!r} carries hidden-truth fields {list(leaks)}; "
                "the controller path may not observe simulator truth"
            )
        # Forbidden vendor fields are not an error here: they stay in the record
        # and are preserved as raw archive data. What is forbidden is *mapping*
        # them onto a canonical channel, which MappingTable.get refuses.
        return record


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

SIMULATOR_MAPPING_REVISION = "sim-observation-map-2"


def simulator_mapping(source_id: str = "simulator") -> MappingTable:
    """Canonical simulator observation map for an own-car stream.

    The simulator publishes SI values already, but the mapping still exists so
    that renaming a simulator field is a reviewed mapping-revision change rather
    than an invisible behaviour change. Revision 2 is the first one that
    actually does its job: the simulator's own field names had drifted from the
    contract's canonical channel names, and because every entry here was an
    identity pair the drift was invisible. The left column is now what
    ``afterlap_core.simulation.observation`` really emits and the right column
    is the registered channel.

    Two emitted fields are deliberately unmapped rather than passed through.
    ``lap`` is an integer lap count, not a measured channel, and
    ``recharge_this_lap_j`` is a per-lap counter that resets, so publishing it
    beside a cumulative channel would invite a consumer to add the two.

    Relational quantities are absent because an own-car stream does not emit
    them: the simulator puts ``gap_s`` and the relative channels on a rival
    record. A caller that genuinely has a grid declares ``gap_ahead_s`` and
    ``gap_behind_s`` through the ``channels`` argument of
    :func:`simulator_capability`.
    """
    return MappingTable(
        mapping_revision=SIMULATOR_MAPPING_REVISION,
        source_id=source_id,
        entries=(
            FieldMapping("speed_mps", "speed_mps", "m/s"),
            FieldMapping("acceleration_mps2", "acceleration_mps2", "m/s^2"),
            FieldMapping("s_m", "lap_distance_m", "m"),
            FieldMapping("progress_m", "progress_m", "m"),
            FieldMapping("lateral_d_m", "lateral_position_m", "m"),
            FieldMapping("battery_energy_j", "battery_energy_j", "J"),
            FieldMapping("electrical_power_w", "electrical_power_w", "W"),
            FieldMapping("battery_temperature_k", "battery_temperature_k", "K"),
            FieldMapping("recharge_cumulative_j", "recharge_ledger_j", "J"),
        ),
        forbidden_fields={
            "world_state": "simulator truth is not an observation",
            "rival_battery_energy_j": "rival truth is not observable without authorised measurement",
        },
    )


class SimulatorAdapter(_BaseAdapter):
    """Adapter over an injected observation stream.

    The constructor accepts an :class:`ObservationSource`, a zero-argument
    factory, or a plain iterable, and it only ever calls the observation method.
    It holds no reference to a world state and never reaches for a truth
    accessor even if the object it was handed happens to have one.

    The enforced guarantee is at the record level: every emitted record is
    checked by :func:`find_truth_leaks`, and a record carrying a hidden-truth
    field raises :class:`TruthLeakError`. That check is what makes 'the
    controller cannot see truth' a tested property rather than a convention.
    """

    provenance = Provenance.SIMULATED

    def __init__(
        self,
        source: ObservationSource | ObservationFactory | Iterable[ObservationRecord],
        *,
        capability: SourceCapability | None = None,
        mapping: MappingTable | None = None,
        source_id: str = "simulator",
    ) -> None:
        declared = capability
        if declared is None:
            observation_capability = getattr(source, "observation_capability", None)
            if callable(observation_capability):
                declared = observation_capability()
        if declared is None:
            raise AdapterError(
                "SimulatorAdapter needs a SourceCapability, either passed explicitly or "
                "declared by the observation source"
            )
        if declared.mode is not SessionMode.SIMULATION:
            raise AdapterError(
                f"a simulator observation stream must declare mode=simulation, got {declared.mode}"
            )
        super().__init__(declared, mapping or simulator_mapping(declared.source_id or source_id))
        self._source = source

    def _iterate(self) -> Iterable[ObservationRecord]:
        observations = getattr(self._source, "observations", None)
        if callable(observations):
            return observations()
        if callable(self._source):
            return self._source()
        return cast("Iterable[ObservationRecord]", self._source)

    def events(self) -> Iterator[ObservationRecord]:
        self._require_open()
        for record in self._iterate():
            if not isinstance(record, ObservationRecord):
                raise AdapterError(
                    f"observation source yielded {type(record).__name__}, expected ObservationRecord"
                )
            yield self._validate_record(record)


def simulator_capability(
    source_id: str = "simulator",
    *,
    rate_hz: float = 20.0,
    channels: Sequence[str] | None = None,
    clock_error_s: float = 0.0,
) -> SourceCapability:
    """Capability for a simulator observation stream (synthetic by definition).

    The default list is derived from :func:`simulator_mapping`, so the two
    cannot drift: the capability declares exactly the canonical channels the
    mapping can produce from what the simulator emits. Declaring a channel the
    source cannot actually supply is the same dishonesty as calling a
    configured value measured, and a consumer that trusts this list and finds
    nothing arriving has no way to tell a missing channel from a broken feed.

    Rival-derived quantities (``gap_s`` and the relative channels) are not
    listed here because they belong to a rival observation record rather than
    to the own-car stream. Pass ``channels`` explicitly to declare them when a
    grid really supports them.
    """
    supported = tuple(channels if channels is not None else simulator_mapping(source_id).channels())
    return SourceCapability(
        source_id=source_id,
        mode=SessionMode.SIMULATION,
        supported_channels=supported,
        measured_channels=supported,
        update_rates_hz=dict.fromkeys(supported, rate_hz),
        clock_error_s=clock_error_s,
        limitations=(SYNTHETIC_NOTICE, "simulated observations; not a measured car"),
    )


# ---------------------------------------------------------------------------
# Public archive replay
# ---------------------------------------------------------------------------

PUBLIC_MAPPING_REVISION = "public-openf1-shape-map-1"

#: Approximate car/location sampling documented for public feeds (source
#: register D01). Deliberately not 20 Hz.
PUBLIC_SAMPLE_RATE_HZ = 3.7

PUBLIC_LIMITATIONS: tuple[str, ...] = (
    "approximately 3.7 Hz car and location sampling; this source is not a 20 Hz feed",
    "no battery-energy channel: stored energy is not observable from this source",
    "lateral placement is not reliable; do not derive lateral_position_m or racing line from it",
    "historical DRS-style fields are not 2026 Overtake eligibility and are left unmapped",
    "usable for pace, context and calibration only; not an observed energy controller",
)


def public_replay_mapping(source_id: str = "public-replay") -> MappingTable:
    """Vendor map for an OpenF1-shaped car-data archive.

    Only ``speed`` has a defensible canonical mapping. ``x``/``y``/``z``,
    ``n_gear``, ``rpm``, ``throttle`` and ``brake`` are passed through as raw
    fields; ``drs`` is forbidden outright.
    """
    return MappingTable(
        mapping_revision=PUBLIC_MAPPING_REVISION,
        source_id=source_id,
        entries=(FieldMapping("speed", "speed_mps", "km/h", missing_values=(-1,)),),
        forbidden_fields={
            "drs": (
                "a historical DRS state field is not 2026 Overtake eligibility; "
                "eligibility is resolved by the rules engine from detection lines, never inferred here"
            ),
            "x": "public location is not a reliable Frenet lateral coordinate",
            "y": "public location is not a reliable Frenet lateral coordinate",
            "z": "public location is not a reliable Frenet lateral coordinate",
        },
        passthrough_fields=("n_gear", "rpm", "throttle", "brake", "date", "driver_number"),
    )


def public_replay_capability(
    source_id: str = "public-replay",
    *,
    clock_error_s: float = 0.5,
) -> SourceCapability:
    """Honest capability for a public reference archive."""
    supported = ("speed_mps",)
    return SourceCapability(
        source_id=source_id,
        mode=SessionMode.REPLAY,
        supported_channels=supported,
        measured_channels=supported,
        update_rates_hz={"speed_mps": PUBLIC_SAMPLE_RATE_HZ},
        clock_error_s=clock_error_s,
        limitations=PUBLIC_LIMITATIONS,
        license_note=OPENF1_LICENSE_NOTE,
    )


class PublicReplayAdapter(_BaseAdapter):
    """Offline importer for a locally stored public-style session.

    There is no network access in this adapter: it reads JSON or Parquet files
    that were acquired separately and recorded in the acquisition manifest.
    """

    provenance = Provenance.MEASURED

    def __init__(
        self,
        path: Path | str,
        *,
        source_id: str = "public-replay",
        capability: SourceCapability | None = None,
        mapping: MappingTable | None = None,
        car_field: str = "driver_number",
        time_field: str = "session_time",
        sequence_field: str | None = None,
    ) -> None:
        super().__init__(
            capability or public_replay_capability(source_id),
            mapping or public_replay_mapping(source_id),
        )
        self._path = Path(path)
        self._car_field = car_field
        self._time_field = time_field
        self._sequence_field = sequence_field

    def open(self, manifest: SessionManifest) -> AdapterOpenResult:
        if not self._path.exists():
            return AdapterOpenResult(
                source_id=self.source_id,
                state=CapabilityState.UNAVAILABLE,
                capability=self._capability,
                detail=f"local archive {self._path} does not exist; no public data is fabricated",
            )
        result = super().open(manifest)
        return replace(
            result,
            state=CapabilityState.DEGRADED,
            detail=("public reference archive: " + "; ".join(PUBLIC_LIMITATIONS[:3])),
        )

    def _rows(self) -> list[dict[str, Any]]:
        suffix = self._path.suffix.lower()
        if suffix == ".json":
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload = payload.get("rows", [])
            if not isinstance(payload, list):
                raise AdapterError(f"{self._path} does not contain a list of records")
            return [dict(row) for row in payload]
        if suffix in (".parquet", ".pq"):
            import pyarrow.parquet as pq

            table = pq.read_table(self._path)
            return [dict(row) for row in table.to_pylist()]
        raise AdapterError(f"unsupported archive format {suffix!r}; expected .json or .parquet")

    def events(self) -> Iterator[ObservationRecord]:
        self._require_open()
        for index, row in enumerate(self._rows()):
            if self._time_field not in row:
                raise AdapterError(
                    f"archive row {index} has no {self._time_field!r}; source time cannot be guessed"
                )
            car_value = row.get(self._car_field)
            if car_value is None:
                raise AdapterError(f"archive row {index} has no {self._car_field!r} to identify a car")
            sequence = int(row[self._sequence_field]) if self._sequence_field else index
            fields = {k: v for k, v in row.items() if k != self._time_field}
            yield self._validate_record(
                ObservationRecord(
                    source_id=self.source_id,
                    car_id=str(car_value),
                    source_time_s=float(row[self._time_field]),
                    source_sequence=sequence,
                    fields=fields,
                    source_time_utc=str(row["date"]) if "date" in row else None,
                )
            )


# ---------------------------------------------------------------------------
# Team feed
# ---------------------------------------------------------------------------

TEAM_FEED_MAPPING_REVISION = "team-feed-map-0-unreviewed"


@dataclass(frozen=True, slots=True)
class TeamFeedAuthorisation:
    """Proof that a team feed exists, is authorised and its terms were reviewed.

    ``credential_ref`` is a reference into a secret store, never a secret. The
    recording layer redacts it anyway.
    """

    feed_id: str
    endpoint: str
    credential_ref: str
    terms_review_status: str
    field_definitions_reviewed: bool = False

    def is_usable(self) -> tuple[bool, str]:
        if not self.field_definitions_reviewed:
            return False, "vendor field definitions have not been reviewed; no mapping can be trusted"
        if self.terms_review_status.lower() not in ("approved", "authorised", "authorized"):
            return False, f"terms review status is {self.terms_review_status!r}, not approved"
        return True, "authorised"


def team_feed_mapping(source_id: str = "team-feed") -> MappingTable:
    """Placeholder map. Empty on purpose: no authorised field definitions exist."""
    return MappingTable(
        mapping_revision=TEAM_FEED_MAPPING_REVISION,
        source_id=source_id,
        entries=(),
        forbidden_fields={
            "drs": "historical DRS state is not 2026 Overtake eligibility",
        },
    )


def team_feed_capability(
    source_id: str = "team-feed",
    *,
    state: CapabilityState = CapabilityState.UNAVAILABLE,
) -> SourceCapability:
    limitations = [
        "no authorised team feed is configured",
        "field definitions unreviewed; no vendor field is mapped",
    ]
    if state is not CapabilityState.UNAVAILABLE:
        limitations = [
            SYNTHETIC_NOTICE,
            "synthetic stand-in for an authorised team feed; not a live feed and not measured data",
        ]
    return SourceCapability(
        source_id=source_id,
        mode=SessionMode.SIMULATION if state is not CapabilityState.UNAVAILABLE else SessionMode.LIVE_TEAM,
        supported_channels=(),
        measured_channels=(),
        update_rates_hz={},
        clock_error_s=0.0,
        limitations=tuple(limitations),
    )


class TeamFeedAdapter(_BaseAdapter):
    """Interface for an authorised team feed.

    Without a usable :class:`TeamFeedAuthorisation`, ``open()`` returns
    ``CapabilityState.UNAVAILABLE`` and ``events()`` yields nothing. It never
    substitutes a synthetic stream for the real one; that substitution has to be
    an explicit choice of :class:`SyntheticTeamFeedAdapter`.
    """

    provenance = Provenance.MEASURED

    def __init__(
        self,
        *,
        source_id: str = "team-feed",
        authorisation: TeamFeedAuthorisation | None = None,
        capability: SourceCapability | None = None,
        mapping: MappingTable | None = None,
    ) -> None:
        super().__init__(
            capability or team_feed_capability(source_id),
            mapping or team_feed_mapping(source_id),
        )
        self._authorisation = authorisation
        self._unavailable_reason: str | None = None

    def authorisation_status(self) -> tuple[bool, str]:
        if self._authorisation is None:
            return False, "no authorised feed is configured for this deployment"
        return self._authorisation.is_usable()

    def open(self, manifest: SessionManifest) -> AdapterOpenResult:
        usable, reason = self.authorisation_status()
        if not usable:
            self._unavailable_reason = reason
            self._opened = False
            return AdapterOpenResult(
                source_id=self.source_id,
                state=CapabilityState.UNAVAILABLE,
                capability=self._capability,
                detail=reason,
            )
        return super().open(manifest)

    def events(self) -> Iterator[ObservationRecord]:
        usable, reason = self.authorisation_status()
        if not usable:
            self._unavailable_reason = reason
            return iter(())
        self._require_open()
        raise FeedUnavailableError(
            "an authorised team feed is configured but no vendor transport is implemented; "
            "implement it against the reviewed field definitions rather than emitting placeholder data"
        )

    @property
    def unavailable_reason(self) -> str | None:
        return self._unavailable_reason


class SyntheticTeamFeedAdapter(_BaseAdapter):
    """Clearly-labelled synthetic stand-in for a team feed.

    Provenance is ``SIMULATED`` and the capability carries the synthetic notice,
    so nothing downstream can mistake it for measured team telemetry.
    """

    provenance = Provenance.SIMULATED

    def __init__(
        self,
        records: Iterable[ObservationRecord] | ObservationFactory,
        *,
        source_id: str = "team-feed-synthetic",
        acknowledged_synthetic: bool = False,
        rate_hz: float = 10.0,
    ) -> None:
        if not acknowledged_synthetic:
            raise AdapterError(
                "SyntheticTeamFeedAdapter must be constructed with acknowledged_synthetic=True; "
                "a synthetic feed is never a default substitute for an authorised one"
            )
        supported = ("speed_mps", "battery_energy_j", "electrical_power_w")
        capability = SourceCapability(
            source_id=source_id,
            mode=SessionMode.SIMULATION,
            supported_channels=supported,
            measured_channels=(),
            update_rates_hz=dict.fromkeys(supported, rate_hz),
            clock_error_s=0.05,
            limitations=(
                SYNTHETIC_NOTICE,
                "synthetic team-feed stand-in: supported but not measured; provenance is simulated",
            ),
        )
        mapping = MappingTable(
            mapping_revision="team-feed-synthetic-map-1",
            source_id=source_id,
            entries=(
                FieldMapping("vcar", "speed_mps", "km/h"),
                FieldMapping("ers_store", "battery_energy_j", "MJ"),
                FieldMapping("ers_power", "electrical_power_w", "kW"),
            ),
            forbidden_fields={"drs": "historical DRS state is not 2026 Overtake eligibility"},
        )
        super().__init__(capability, mapping)
        self._records = records

    def events(self) -> Iterator[ObservationRecord]:
        self._require_open()
        source = self._records() if callable(self._records) else self._records
        for record in source:
            yield self._validate_record(record)


# ---------------------------------------------------------------------------
# Test/fixture helper: a minimal in-memory observation source
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ListObservationSource:
    """Synthetic :class:`ObservationSource` over a fixed list of records.

    Exists so ingestion can be exercised before a simulator exists. It satisfies
    exactly the protocol A03's simulator must satisfy and nothing more.
    """

    capability: SourceCapability
    records: list[ObservationRecord] = field(default_factory=list)

    def observation_capability(self) -> SourceCapability:
        return self.capability

    def observations(self) -> Iterable[ObservationRecord]:
        return list(self.records)


def validate_mapping_against_capability(capability: SourceCapability, mapping: MappingTable) -> None:
    """Fail fast when a source maps a channel it never declared it supports."""
    undeclared = sorted(set(mapping.channels()) - set(capability.supported_channels))
    if undeclared:
        raise MappingError(
            f"mapping table {mapping.mapping_revision!r} produces channels {undeclared} that "
            f"capability {capability.source_id!r} does not declare as supported"
        )


__all__ = [
    "OPENF1_LICENSE_NOTE",
    "PUBLIC_LIMITATIONS",
    "PUBLIC_MAPPING_REVISION",
    "PUBLIC_SAMPLE_RATE_HZ",
    "SIMULATOR_MAPPING_REVISION",
    "TEAM_FEED_MAPPING_REVISION",
    "AdapterError",
    "AdapterOpenResult",
    "CapabilityAnswer",
    "FeedUnavailableError",
    "ListObservationSource",
    "ObservationFactory",
    "ObservationRecord",
    "ObservationSource",
    "PublicReplayAdapter",
    "SimulatorAdapter",
    "SourceAdapter",
    "SyntheticTeamFeedAdapter",
    "TeamFeedAdapter",
    "TeamFeedAuthorisation",
    "TruthLeakError",
    "public_replay_capability",
    "public_replay_mapping",
    "request_channel",
    "simulator_capability",
    "simulator_mapping",
    "team_feed_capability",
    "team_feed_mapping",
    "validate_mapping_against_capability",
]
