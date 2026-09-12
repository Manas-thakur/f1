from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field, replace
from typing import TYPE_CHECKING, Any

from afterlap_contracts import DeploymentProfile, FlagState

from ..rng import KeyedRandom, StreamRegistry
from ..timebase import EventPriority, EventQueue, ScheduledEvent, SessionClock
from .battery import EnergyLedger
from .track_source import DEFAULT_ENVIRONMENT, EnvironmentField, TrackSource

if TYPE_CHECKING:
    from .config import CarConfig, DriverConfig, ScenarioBundle
    from .policies import DriverAction, OpponentPolicy


@dataclass(slots=True)
class CarState:
    car_id: str

    progress_m: float = 0.0
    s_m: float = 0.0
    lap: int = 0
    speed_mps: float = 0.0
    acceleration_mps2: float = 0.0
    lateral_d_m: float = 0.0
    heading_error_rad: float = 0.0

    battery_energy_j: float = 0.0
    battery_temperature_k: float = 300.0
    recharge_ledger_j: float = 0.0
    recharge_ledger_this_lap_j: float = 0.0

    active_profile: DeploymentProfile = DeploymentProfile.NEUTRAL
    pending_profile: DeploymentProfile | None = None
    pending_apply_time_s: float | None = None

    elapsed_time_s: float = 0.0
    distance_travelled_m: float = 0.0

    applied_throttle: float = 0.0
    applied_brake: float = 0.0
    grip_multiplier: float = 1.0
    drive_force_n: float = 0.0
    drag_force_n: float = 0.0
    rolling_force_n: float = 0.0
    grade_force_n: float = 0.0
    traction_limit_n: float = 0.0
    traction_envelope_n: float = 0.0
    lateral_demand_n: float = 0.0
    lateral_acceleration_mps2: float = 0.0
    tyre_utilisation: float = 0.0
    ice_power_w: float = 0.0
    deploy_power_dc_w: float = 0.0
    harvest_power_dc_w: float = 0.0
    battery_out_power_w: float = 0.0
    battery_in_power_w: float = 0.0
    auxiliary_power_w: float = 0.0
    electrical_loss_power_w: float = 0.0
    mechanical_braking_power_w: float = 0.0
    mechanical_rejected_power_w: float = 0.0
    target_speed_mps: float = 0.0
    envelope_speed_mps: float = 0.0
    derate_factor: float = 1.0

    def copy(self) -> CarState:
        return replace(self)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["active_profile"] = self.active_profile.value
        payload["pending_profile"] = None if self.pending_profile is None else self.pending_profile.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CarState:
        data = dict(payload)
        data["active_profile"] = DeploymentProfile(data["active_profile"])
        pending = data.get("pending_profile")
        data["pending_profile"] = None if pending is None else DeploymentProfile(pending)
        return cls(**data)


@dataclass(slots=True)
class RaceState:
    session_time_s: float = 0.0
    leader_lap: int = 0
    flags: tuple[FlagState, ...] = (FlagState.GREEN,)
    step_index: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_time_s": self.session_time_s,
            "leader_lap": self.leader_lap,
            "flags": [flag.value for flag in self.flags],
            "step_index": self.step_index,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RaceState:
        return cls(
            session_time_s=payload["session_time_s"],
            leader_lap=payload["leader_lap"],
            flags=tuple(FlagState(flag) for flag in payload["flags"]),
            step_index=payload["step_index"],
        )


@dataclass(slots=True)
class PassRecord:
    session_time_s: float
    overtaking_car_id: str
    overtaken_car_id: str
    kind: str
    checkpoint_id: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PairState:
    label: str = "behind"
    armed: bool = False

    attempted: bool = False
    overlapped: bool = False
    completed_at_s: float | None = None
    completed_progress_m: float | None = None
    retained_evaluated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CheckpointRecord:
    checkpoint_id: str
    car_id: str
    lap: int
    session_time_s: float
    progress_m: float
    speed_mps: float
    battery_energy_j: float
    recharge_cumulative_j: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TruthSample:
    session_time_s: float
    cars: dict[str, dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_time_s": self.session_time_s,
            "cars": {car_id: dict(channels) for car_id, channels in self.cars.items()},
        }


@dataclass(slots=True)
class QueuedAction:
    apply_time_s: float
    car_id: str
    action: DriverAction
    issued_at_s: float
    sequence: int


@dataclass
class WorldState:
    bundle: ScenarioBundle
    track: TrackSource
    car_configs: dict[str, CarConfig]
    driver_configs: dict[str, DriverConfig]
    seed: int
    environment: EnvironmentField = field(default_factory=lambda: DEFAULT_ENVIRONMENT)

    cars: dict[str, CarState] = field(default_factory=dict)
    ledgers: dict[str, EnergyLedger] = field(default_factory=dict)
    race: RaceState = field(default_factory=RaceState)
    clock: SessionClock = field(default_factory=SessionClock)
    events: EventQueue[dict[str, Any]] = field(default_factory=EventQueue)
    streams: StreamRegistry | None = None
    keyed: KeyedRandom | None = None
    policies: dict[str, OpponentPolicy] = field(default_factory=dict)
    action_queues: dict[str, list[QueuedAction]] = field(default_factory=dict)
    active_actions: dict[str, DriverAction] = field(default_factory=dict)
    next_thresholds: dict[str, dict[str, float]] = field(default_factory=dict)
    sensor_buffer: list[TruthSample] = field(default_factory=list)
    pairs: dict[tuple[str, str], PairState] = field(default_factory=dict)
    passes: list[PassRecord] = field(default_factory=list)
    checkpoint_records: list[CheckpointRecord] = field(default_factory=list)
    action_sequence: int = 0
    integrator: str = "explicit_midpoint"
    last_dt_s: float = 0.0

    def capture_complete_state(self) -> dict[str, Any]:

        if self.streams is None or self.keyed is None:
            raise RuntimeError("world state has no random streams; reset() was not called")
        return copy.deepcopy(
            {
                "schema": "afterlap.simulation.snapshot/1",
                "scenario_id": self.bundle.scenario.id,
                "bundle_hash": self.bundle.bundle_hash,
                "seed": self.seed,
                "cars": {car_id: state.as_dict() for car_id, state in sorted(self.cars.items())},
                "ledgers": {car_id: ledger.as_dict() for car_id, ledger in sorted(self.ledgers.items())},
                "race": self.race.as_dict(),
                "clock": {
                    "session_time_s": self.clock.session_time_s,
                    "paused": self.clock.paused,
                    "clock_error_s": self.clock.clock_error_s,
                    "speed": self.clock.speed,
                },
                "events": {
                    "counter": self.events.counter,
                    "items": [
                        {
                            "time_s": event.time_s,
                            "priority": int(event.priority),
                            "tiebreak": event.tiebreak,
                            "payload": event.payload,
                        }
                        for event in self.events.snapshot()
                    ],
                },
                "streams": self.streams.capture(),
                "keyed": {
                    "scenario": self.keyed.scenario,
                    "seed": self.keyed.seed,
                    "bin_width_s": self.keyed.bin_width_s,
                },
                "policies": {
                    car_id: {"hash": policy.policy_hash, "memory": policy.capture()}
                    for car_id, policy in sorted(self.policies.items())
                },
                "action_queues": {
                    car_id: [
                        {
                            "apply_time_s": queued.apply_time_s,
                            "car_id": queued.car_id,
                            "issued_at_s": queued.issued_at_s,
                            "sequence": queued.sequence,
                            "action": queued.action.as_dict(),
                        }
                        for queued in queue
                    ]
                    for car_id, queue in sorted(self.action_queues.items())
                },
                "active_actions": {
                    car_id: action.as_dict() for car_id, action in sorted(self.active_actions.items())
                },
                "next_thresholds": {
                    car_id: dict(thresholds) for car_id, thresholds in sorted(self.next_thresholds.items())
                },
                "sensor_buffer": [sample.as_dict() for sample in self.sensor_buffer],
                "pairs": {f"{a}|{b}": pair.as_dict() for (a, b), pair in sorted(self.pairs.items())},
                "passes": [record.as_dict() for record in self.passes],
                "checkpoint_records": [record.as_dict() for record in self.checkpoint_records],
                "action_sequence": self.action_sequence,
                "integrator": self.integrator,
                "last_dt_s": self.last_dt_s,
            }
        )

    def restore(self, snapshot: dict[str, Any]) -> None:

        from .policies import DriverAction

        if snapshot.get("schema") != "afterlap.simulation.snapshot/1":
            raise ValueError("unrecognised simulation snapshot schema")
        if snapshot["bundle_hash"] != self.bundle.bundle_hash:
            raise ValueError(
                "snapshot was taken from a different scenario bundle; restoring it would "
                "silently change the physics under the recorded state"
            )
        payload = copy.deepcopy(snapshot)
        self.seed = payload["seed"]
        self.cars = {car_id: CarState.from_dict(state) for car_id, state in payload["cars"].items()}
        self.ledgers = {car_id: EnergyLedger.from_dict(state) for car_id, state in payload["ledgers"].items()}
        self.race = RaceState.from_dict(payload["race"])
        clock = payload["clock"]
        self.clock = SessionClock(
            session_time_s=clock["session_time_s"],
            paused=clock["paused"],
            clock_error_s=clock["clock_error_s"],
            speed=clock["speed"],
        )
        self.events = EventQueue()
        self.events.restore(
            [
                ScheduledEvent(
                    time_s=item["time_s"],
                    priority=EventPriority(item["priority"]),
                    tiebreak=item["tiebreak"],
                    payload=item["payload"],
                )
                for item in payload["events"]["items"]
            ],
            payload["events"]["counter"],
        )
        registry = StreamRegistry(payload["streams"]["root_seed"])
        registry.restore(payload["streams"])
        self.streams = registry
        keyed = payload["keyed"]
        self.keyed = KeyedRandom(keyed["scenario"], keyed["seed"], bin_width_s=keyed["bin_width_s"])
        for car_id, policy_state in payload["policies"].items():
            policy = self.policies[car_id]
            if policy.policy_hash != policy_state["hash"]:
                raise ValueError(
                    f"snapshot policy hash for {car_id} does not match the loaded policy; "
                    "the opponent identity would change under restore"
                )
            policy.restore(policy_state["memory"])
        self.action_queues = {
            car_id: [
                QueuedAction(
                    apply_time_s=item["apply_time_s"],
                    car_id=item["car_id"],
                    action=DriverAction.from_dict(item["action"]),
                    issued_at_s=item["issued_at_s"],
                    sequence=item["sequence"],
                )
                for item in queue
            ]
            for car_id, queue in payload["action_queues"].items()
        }
        self.active_actions = {
            car_id: DriverAction.from_dict(action) for car_id, action in payload["active_actions"].items()
        }
        self.next_thresholds = {
            car_id: dict(thresholds) for car_id, thresholds in payload["next_thresholds"].items()
        }
        self.sensor_buffer = [
            TruthSample(session_time_s=sample["session_time_s"], cars=sample["cars"])
            for sample in payload["sensor_buffer"]
        ]
        self.pairs = {}
        for key, pair in payload["pairs"].items():
            first, second = key.split("|", 1)
            self.pairs[(first, second)] = PairState(**pair)
        self.passes = [PassRecord(**record) for record in payload["passes"]]
        self.checkpoint_records = [CheckpointRecord(**record) for record in payload["checkpoint_records"]]
        self.action_sequence = payload["action_sequence"]
        self.integrator = payload["integrator"]
        self.last_dt_s = payload["last_dt_s"]


__all__ = [
    "CarState",
    "CheckpointRecord",
    "PairState",
    "PassRecord",
    "QueuedAction",
    "RaceState",
    "TruthSample",
    "WorldState",
]
