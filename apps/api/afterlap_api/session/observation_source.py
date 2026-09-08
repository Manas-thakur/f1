"""The seam between simulator truth and ingestion.

``Simulator.observe()`` already applies the delay, noise, quantisation and
channel gating. What is left is the *shape* conversion: an
:class:`afterlap_core.simulation.Observation` becomes a stream of
:class:`~afterlap_core.data.ObservationRecord` values that A02's
``SimulatorAdapter`` can ingest.

Two structural rules, both enforced here rather than left to convention:

* This object never holds a reference to the simulator or to a ``WorldState``.
  The runtime *pushes* one already-built ``Observation`` into it with
  :meth:`SimulatorObservationSource.offer`. A02's handoff asks for exactly this
  ("implement it on a view object, not on the simulator itself"), so the adapter
  cannot reach truth through the object it was handed.
* Only fields the observation actually carries are copied, and rival records
  carry position and speed only. :class:`TruthIsolationError` is raised if a
  rival mapping ever presents an energy or thermal channel, so a future
  ``expose_rival_energy=true`` scenario cannot leak through this adapter by
  accident. ``SimulatorAdapter`` also runs ``find_truth_leaks`` over every
  record; that check is satisfied, not defeated.

Channels declared here are the channels actually published. ``simulator_mapping()``
knows how to map ``electrical_power_w`` as well, but ``Observation`` has no
electrical-power channel, so the capability does not claim one. An undeclared
cadence would make a channel permanently degraded (A02 requirement 2), and a
declared channel that is never published would be a false capability claim.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from afterlap_contracts import Quality, SessionMode, SourceCapability
from afterlap_contracts.fixtures import SYNTHETIC_NOTICE
from afterlap_core.data import ObservationRecord
from afterlap_core.simulation.config import ScenarioBundle

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from afterlap_core.simulation.observation import Observation

SIMULATOR_SOURCE_ID = "simulator"

OWN_CHANNEL_FIELDS: Mapping[str, str] = {
    "speed_mps": "speed_mps",
    "progress_m": "progress_m",
    "s_m": "lap_distance_m",
    "battery_energy_j": "battery_energy_j",
    "battery_temperature_k": "battery_temperature_k",
}
"""Own-car channels this source republishes, keyed by the simulator's own name."""

RIVAL_CHANNEL_FIELDS: Mapping[str, str] = {
    "speed_mps": "speed_mps",
}
"""Rival channels copied verbatim. Rival progress is derived, see :func:`_rival_fields`."""

FORBIDDEN_RIVAL_FIELDS: frozenset[str] = frozenset(
    {"battery_energy_j", "battery_temperature_k", "recharge_this_lap_j", "recharge_cumulative_j"}
)
"""Rival channels that are truth even when a scenario configuration exposes them."""

BASE_CHANNELS: tuple[str, ...] = (
    "speed_mps",
    "progress_m",
    "lap_distance_m",
    "battery_temperature_k",
)
"""Own-car channels a simulator session always publishes."""

RELATIONAL_CHANNELS: tuple[str, ...] = ("gap_ahead_s", "gap_behind_s")
"""Gap channels, which exist only while some car occupies the corresponding slot.

These are *relational*, not sensors. An empty slot is known information -- the
feature contract encodes exactly that by leaving the rival ``present_flag``
unmaskable -- so a gap with no counterpart must not be reported as a missing
measurement. Declaring one unconditionally made a two-car scenario report
``gap_behind_s`` missing forever, which escalated the source to stale and
blocked every recommendation for the whole session.
"""

ENERGY_CHANNEL = "battery_energy_j"


class TruthIsolationError(RuntimeError):
    """A rival observation presented a channel the controller may not know."""


def simulator_session_capability(
    *,
    source_id: str = SIMULATOR_SOURCE_ID,
    energy_channel_available: bool,
    rate_hz: float,
    relational_channels: Sequence[str] = RELATIONAL_CHANNELS,
    clock_error_s: float = 0.0,
    observation_delay_s: float = 0.0,
) -> SourceCapability:
    """Declare exactly what this observation stream publishes.

    ``relational_channels`` names the gap channels a slot can actually be filled
    for in this scenario. A two-car session with the ego car at the back has no
    car behind it, so declaring ``gap_behind_s`` would promise a measurement
    that can never arrive.

    ``battery_energy_j`` appears only when the scenario's observation
    configuration actually carries it. A source that cannot see stored energy
    says so, and estimation then reports ``own_energy_capability=False`` rather
    than inventing a number.
    """
    supported = (
        BASE_CHANNELS
        + tuple(c for c in RELATIONAL_CHANNELS if c in set(relational_channels))
        + ((ENERGY_CHANNEL,) if energy_channel_available else ())
    )
    limitations = [
        SYNTHETIC_NOTICE,
        "simulated observations from a reduced physical model; not a measured car",
        f"observations are delayed by {observation_delay_s:.3f} s at the source",
    ]
    if not energy_channel_available:
        limitations.append("no battery-energy channel in this scenario: stored energy is not observable here")
    limitations.append(
        "rival records carry derived position and speed only; rival stored energy is never published"
    )
    return SourceCapability(
        source_id=source_id,
        mode=SessionMode.SIMULATION,
        supported_channels=supported,
        measured_channels=supported,
        update_rates_hz=dict.fromkeys(supported, rate_hz),
        clock_error_s=clock_error_s,
        limitations=tuple(limitations),
    )


def relational_channels_for(bundle: ScenarioBundle) -> tuple[str, ...]:
    """Which gap channels this scenario can ever fill.

    Decided from the starting grid order: a car with nobody behind it never
    produces ``gap_behind_s``, and promising that channel would make an empty
    slot look like a broken feed for the whole session.
    """
    scenario = bundle.scenario
    ego = scenario.ego_car_id
    initial = scenario.initial_states
    ego_progress = float(initial[ego].progress_m.value)

    ahead = any(
        float(state.progress_m.value) > ego_progress for car_id, state in initial.items() if car_id != ego
    )
    behind = any(
        float(state.progress_m.value) < ego_progress for car_id, state in initial.items() if car_id != ego
    )
    channels: list[str] = []
    if ahead:
        channels.append("gap_ahead_s")
    if behind:
        channels.append("gap_behind_s")
    return tuple(channels)


class SimulatorObservationSource:
    """A truth-free ``ObservationSource`` fed one observation at a time.

    The runtime calls :meth:`offer` after each simulator step; ``observations()``
    drains whatever has accumulated since the last drain, which is what the
    ``SimulatorAdapter`` iterates.
    """

    def __init__(
        self,
        *,
        ego_car_id: str,
        rival_car_ids: tuple[str, ...],
        capability: SourceCapability,
        source_id: str = SIMULATOR_SOURCE_ID,
    ) -> None:
        if capability.mode is not SessionMode.SIMULATION:
            raise ValueError("a simulator observation stream must declare mode=simulation")
        self._ego_car_id = ego_car_id
        self._rival_car_ids = rival_car_ids
        self._capability = capability
        self._source_id = source_id
        self._pending: list[ObservationRecord] = []
        self._sequence = 0
        self._restart_pending = False
        self._highest_source_time_s: float | None = None
        self._offered = 0
        self._skipped_missing = 0

    def observation_capability(self) -> SourceCapability:
        return self._capability

    def observations(self) -> Iterable[ObservationRecord]:
        """Drain the buffer. Draining is destructive so nothing is re-sent."""
        drained = tuple(self._pending)
        self._pending.clear()
        return drained

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def skipped_missing(self) -> int:
        """Observations that carried no channels at all, so nothing was emitted."""
        return self._skipped_missing

    def mark_restart(self) -> None:
        """Flag the next emitted record as the first after a source restart.

        A02 requirement 6: the first record after a restart carries
        ``restart_marker=True`` and the source must not re-send times it has
        already emitted. :meth:`offer` enforces the second half.
        """
        self._restart_pending = True

    def offer(self, observation: Observation) -> tuple[ObservationRecord, ...]:
        """Convert one observation into records and queue them.

        Returns what was queued so a caller can assert on it. An observation
        with no channels (nothing yet old enough to have been delivered) queues
        nothing: that is a real operational state and it is reported by its
        absence, never as zeroes.
        """
        self._offered += 1
        if observation.quality is Quality.MISSING or not observation.channels:
            self._skipped_missing += 1
            return ()
        if observation.car_id != self._ego_car_id:
            raise TruthIsolationError(
                f"this source publishes the ego car {self._ego_car_id!r}, not {observation.car_id!r}"
            )

        source_time_s = float(observation.observed_at_s)
        if self._highest_source_time_s is not None and source_time_s <= self._highest_source_time_s:
            return ()
        self._highest_source_time_s = source_time_s
        received_time_s = float(observation.delivered_at_s)

        records: list[ObservationRecord] = [
            self._record(
                car_id=self._ego_car_id,
                source_time_s=source_time_s,
                received_time_s=received_time_s,
                fields=_own_fields(observation),
            )
        ]
        own_progress = observation.channels.get("progress_m")
        for rival in observation.rivals:
            fields = _rival_fields(rival, own_progress)
            if not fields:
                continue
            records.append(
                self._record(
                    car_id=str(rival["car_id"]),
                    source_time_s=source_time_s,
                    received_time_s=received_time_s,
                    fields=fields,
                )
            )

        self._pending.extend(records)
        return tuple(records)

    def _record(
        self,
        *,
        car_id: str,
        source_time_s: float,
        received_time_s: float,
        fields: dict[str, Any],
    ) -> ObservationRecord:
        record = ObservationRecord(
            source_id=self._source_id,
            car_id=car_id,
            source_time_s=source_time_s,
            source_sequence=self._sequence,
            fields=fields,
            received_time_s=received_time_s,
            restart_marker=self._restart_pending,
        )
        self._sequence += 1
        self._restart_pending = False
        return record


def _own_fields(observation: Observation) -> dict[str, Any]:
    """Own-car vendor fields. An unavailable channel is simply absent."""
    fields: dict[str, Any] = {}
    for channel, vendor in OWN_CHANNEL_FIELDS.items():
        if channel in observation.channels:
            fields[vendor] = float(observation.channels[channel])

    ahead = observation.rival_ahead()
    behind = observation.rival_behind()
    if ahead is not None and _finite(ahead.get("gap_s")):
        fields["gap_ahead_s"] = float(ahead["gap_s"])
    if behind is not None and _finite(behind.get("gap_s")):
        fields["gap_behind_s"] = float(behind["gap_s"])
    return fields


def _rival_fields(rival: Mapping[str, Any], own_progress_m: float | None) -> dict[str, Any]:
    """Rival vendor fields: derived absolute progress and observed speed only.

    Relative progress plus our own progress is a position an external observer
    can resolve. Stored energy is not, and this function refuses to copy it even
    if the mapping presents one.
    """
    leaked = sorted(FORBIDDEN_RIVAL_FIELDS.intersection(rival))
    if leaked:
        raise TruthIsolationError(
            f"rival observation carries {leaked}; the controller path may not observe rival truth"
        )

    fields: dict[str, Any] = {}
    for channel, vendor in RIVAL_CHANNEL_FIELDS.items():
        if channel in rival and _finite(rival[channel]):
            fields[vendor] = float(rival[channel])
    relative: Any = rival.get("relative_progress_m")
    if own_progress_m is not None and relative is not None and _finite(relative):
        fields["progress_m"] = float(own_progress_m) + float(relative)
    return fields


def _finite(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and abs(number) != float("inf")


__all__ = [
    "BASE_CHANNELS",
    "ENERGY_CHANNEL",
    "FORBIDDEN_RIVAL_FIELDS",
    "OWN_CHANNEL_FIELDS",
    "RELATIONAL_CHANNELS",
    "RIVAL_CHANNEL_FIELDS",
    "SIMULATOR_SOURCE_ID",
    "SimulatorObservationSource",
    "TruthIsolationError",
    "relational_channels_for",
    "simulator_session_capability",
]
