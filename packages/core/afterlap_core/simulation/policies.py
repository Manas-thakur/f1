from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from afterlap_contracts import DeploymentProfile, Quality

if TYPE_CHECKING:
    import numpy as np

    from .observation import Observation

MIN_PACE_SCALE: float = 0.70
MAX_PACE_SCALE: float = 1.00

RESPONSE_STREAM_PREFIX: str = "driver_response"


RESPONSE_BIN_S: float = 0.25


RESPONSE_JITTER_FRACTION: float = 0.05


RESPONSE_JITTER_CLIP: float = 2.0


INTERACTION_HISTORY_STEPS: int = 12


PRESSURE_COMMIT_STEPS: int = 5


ATTEMPT_COOLDOWN_STEPS: int = 25


RECOVERY_STEPS: int = 40


@dataclass(frozen=True, slots=True)
class DriverAction:
    profile: DeploymentProfile = DeploymentProfile.NEUTRAL
    pace_scale: float = 1.0
    target_lateral_d_m: float = 0.0
    throttle: float | None = None
    brake: float | None = None
    harvest_request: float = 1.0
    low_drag: bool = False
    brake_floor: float = 0.0
    issued_at_s: float = 0.0
    label: str = ""

    def __post_init__(self) -> None:
        if not MIN_PACE_SCALE <= self.pace_scale <= MAX_PACE_SCALE:
            raise ValueError(
                f"pace_scale {self.pace_scale} is outside the bounded preference range "
                f"[{MIN_PACE_SCALE}, {MAX_PACE_SCALE}]; aggressiveness may not exceed the envelope"
            )
        if not 0.0 <= self.brake_floor <= 1.0:
            raise ValueError("brake_floor is a fraction in [0, 1]")
        if not 0.0 <= self.harvest_request <= 1.0:
            raise ValueError("harvest_request is a fraction in [0, 1]")
        if self.throttle is not None and not 0.0 <= self.throttle <= 1.0:
            raise ValueError("throttle is a fraction in [0, 1]")
        if self.brake is not None and not 0.0 <= self.brake <= 1.0:
            raise ValueError("brake is a fraction in [0, 1]")

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["profile"] = self.profile.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DriverAction:
        data = dict(payload)
        data["profile"] = DeploymentProfile(data["profile"])
        return cls(**data)


@runtime_checkable
class OpponentPolicy(Protocol):
    @property
    def policy_hash(self) -> str: ...

    def react(self, observation: Observation, rng: np.random.Generator) -> DriverAction: ...

    def capture(self) -> dict[str, Any]: ...

    def restore(self, memory: dict[str, Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class Interaction:
    ahead_id: str | None = None
    behind_id: str | None = None
    gap_ahead_s: float | None = None
    gap_behind_s: float | None = None
    closing_rate_mps: float | None = None
    pressure_steps: int = 0
    tow_steps: int = 0
    passed_by: int = 0
    passes_made: int = 0
    recovery: int = 0
    cooldown: int = 0
    attempts: int = 0

    @property
    def present(self) -> bool:

        return (
            self.ahead_id is not None or self.behind_id is not None or self.recovery > 0 or self.cooldown > 0
        )

    @property
    def just_lost_a_position(self) -> bool:
        return self.recovery > 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_MEMORY_DEFAULTS: dict[str, Any] = {
    "state": "idle",
    "steps": 0,
    "bias_bin": None,
    "response_bias": 0.0,
    "pressure_steps": 0,
    "tow_steps": 0,
    "passed_by": 0,
    "passes_made": 0,
    "attempts": 0,
    "cooldown": 0,
    "recovery": 0,
    "ahead_id": None,
    "behind_id": None,
    "gap_ahead_s": None,
    "gap_behind_s": None,
    "closing_rate_mps": None,
    "history": [],
}


@dataclass
class _BasePolicy:
    kind: str = "normal"
    reserve_energy_j: float = 5.0e5
    engage_gap_s: float = 1.20
    release_gap_s: float = 1.80
    pace_scale: float = 1.0
    lateral_offset_m: float = 0.0
    memory: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.pace_scale = min(MAX_PACE_SCALE, max(MIN_PACE_SCALE, self.pace_scale))
        if self.release_gap_s <= self.engage_gap_s:
            raise ValueError(
                "the release gap must exceed the engage gap, otherwise the state machine has no "
                "hysteresis and a jittery gap measurement makes the opponent flicker"
            )
        self._ensure_memory()

    def _ensure_memory(self) -> None:
        for name, default in _MEMORY_DEFAULTS.items():
            self.memory.setdefault(name, [] if isinstance(default, list) else default)

    @property
    def policy_hash(self) -> str:
        payload = {
            "class": type(self).__name__,
            "kind": self.kind,
            "reserve_energy_j": self.reserve_energy_j,
            "engage_gap_s": self.engage_gap_s,
            "release_gap_s": self.release_gap_s,
            "pace_scale": self.pace_scale,
            "lateral_offset_m": self.lateral_offset_m,
        }
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"

    def capture(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.memory, sort_keys=True))

    def restore(self, memory: dict[str, Any]) -> None:
        self.memory = json.loads(json.dumps(memory, sort_keys=True))
        self._ensure_memory()

    def _own_energy(self, observation: Observation) -> float | None:

        if not observation.has("battery_energy_j"):
            return None
        return observation.get("battery_energy_j")

    def _set_state(self, name: str) -> None:
        self.memory["state"] = name

    @property
    def state(self) -> str:
        return str(self.memory.get("state", "idle"))

    @property
    def interaction(self) -> Interaction:

        memory = self.memory
        return Interaction(
            ahead_id=memory.get("ahead_id"),
            behind_id=memory.get("behind_id"),
            gap_ahead_s=memory.get("gap_ahead_s"),
            gap_behind_s=memory.get("gap_behind_s"),
            closing_rate_mps=memory.get("closing_rate_mps"),
            pressure_steps=int(memory.get("pressure_steps", 0)),
            tow_steps=int(memory.get("tow_steps", 0)),
            passed_by=int(memory.get("passed_by", 0)),
            passes_made=int(memory.get("passes_made", 0)),
            recovery=int(memory.get("recovery", 0)),
            cooldown=int(memory.get("cooldown", 0)),
            attempts=int(memory.get("attempts", 0)),
        )

    def _draw_response_bias(self, observation: Observation, rng: np.random.Generator) -> None:

        draw = float(rng.normal(0.0, 1.0))
        draw = max(-RESPONSE_JITTER_CLIP, min(RESPONSE_JITTER_CLIP, draw))
        moment = observation.observed_at_s
        bin_index = int(moment // RESPONSE_BIN_S) if moment == moment else 0
        if self.memory.get("bias_bin") != bin_index:
            self.memory["bias_bin"] = bin_index
            self.memory["response_bias"] = draw

    def _engage_threshold(self) -> float:

        bias = float(self.memory.get("response_bias", 0.0))
        moved = self.engage_gap_s * (1.0 + RESPONSE_JITTER_FRACTION * bias)
        return max(0.05, min(moved, self.release_gap_s - 1.0e-6))

    def _update_interaction(self, observation: Observation) -> Interaction:

        memory = self.memory
        previous_ahead = memory.get("ahead_id")
        previous_behind = memory.get("behind_id")

        ahead = observation.rival_ahead()
        behind = observation.rival_behind()
        ahead_id = None if ahead is None else str(ahead["car_id"])
        behind_id = None if behind is None else str(behind["car_id"])
        gap_ahead = None if ahead is None else abs(float(ahead["gap_s"]))
        gap_behind = None if behind is None else abs(float(behind["gap_s"]))
        closing = None if ahead is None else -float(ahead["relative_speed_mps"])

        if ahead_id is not None and ahead_id == previous_behind:
            memory["passed_by"] = int(memory.get("passed_by", 0)) + 1
            memory["recovery"] = RECOVERY_STEPS
        if behind_id is not None and behind_id == previous_ahead:
            memory["passes_made"] = int(memory.get("passes_made", 0)) + 1
            memory["cooldown"] = 0
            memory["recovery"] = 0

        engage = self._engage_threshold()
        memory["pressure_steps"] = (
            int(memory.get("pressure_steps", 0)) + 1 if gap_behind is not None and gap_behind <= engage else 0
        )
        memory["tow_steps"] = (
            int(memory.get("tow_steps", 0)) + 1 if gap_ahead is not None and gap_ahead <= engage else 0
        )
        memory["recovery"] = max(0, int(memory.get("recovery", 0)) - 1)
        memory["cooldown"] = max(0, int(memory.get("cooldown", 0)) - 1)
        memory["steps"] = int(memory.get("steps", 0)) + 1
        memory["ahead_id"] = ahead_id
        memory["behind_id"] = behind_id
        memory["gap_ahead_s"] = gap_ahead
        memory["gap_behind_s"] = gap_behind
        memory["closing_rate_mps"] = closing

        history = list(memory.get("history", []))
        history.append(
            {
                "t": observation.observed_at_s,
                "ahead_s": gap_ahead,
                "behind_s": gap_behind,
                "state": self.state,
            }
        )
        memory["history"] = history[-INTERACTION_HISTORY_STEPS:]
        return self.interaction

    def react(self, observation: Observation, rng: np.random.Generator) -> DriverAction:

        self._draw_response_bias(observation, rng)
        if observation.quality is not Quality.VALID:
            self._set_state("no_observation_hold")
            return DriverAction(
                profile=DeploymentProfile.NEUTRAL,
                pace_scale=self.pace_scale,
                target_lateral_d_m=0.0,
                issued_at_s=observation.delivered_at_s,
                label=f"{self.kind}:no_observation_hold",
            )
        interaction = self._update_interaction(observation)
        return self._decide(observation, interaction)

    def _decide(self, observation: Observation, interaction: Interaction) -> DriverAction:
        raise NotImplementedError


@dataclass
class NormalPolicy(_BasePolicy):
    kind: str = "normal"

    def _decide(self, observation: Observation, interaction: Interaction) -> DriverAction:
        curvature = abs(float(observation.context["curvature_inv_m"]))
        energy = self._own_energy(observation)
        straight = curvature < 2.0e-3
        in_tow = interaction.tow_steps > 0
        if energy is not None and energy <= self.reserve_energy_j:
            profile = DeploymentProfile.CONSERVE
            self._set_state("reserve_floor")
        elif straight and in_tow:
            profile = DeploymentProfile.PUSH
            self._set_state("tow_straight")
        elif straight:
            profile = DeploymentProfile.NEUTRAL
            self._set_state("deploy_straight")
        else:
            profile = DeploymentProfile.HARVEST
            self._set_state("corner")
        return DriverAction(
            profile=profile,
            pace_scale=self.pace_scale,
            target_lateral_d_m=self.lateral_offset_m,
            issued_at_s=observation.delivered_at_s,
            label=f"{self.kind}:{self.state}",
        )


@dataclass
class ConservePolicy(_BasePolicy):
    kind: str = "conserve"
    pace_scale: float = 0.95

    def _decide(self, observation: Observation, interaction: Interaction) -> DriverAction:
        energy = self._own_energy(observation)
        pressured = interaction.pressure_steps >= PRESSURE_COMMIT_STEPS
        if energy is None:
            self._set_state("energy_unknown_hold")
            profile = DeploymentProfile.CONSERVE
        elif energy < self.reserve_energy_j:
            self._set_state("rebuilding")
            profile = DeploymentProfile.HARVEST
        elif pressured:
            self._set_state("pressured")
            profile = DeploymentProfile.NEUTRAL
        else:
            self._set_state("holding")
            profile = DeploymentProfile.CONSERVE
        return DriverAction(
            profile=profile,
            pace_scale=self.pace_scale,
            target_lateral_d_m=self.lateral_offset_m,
            harvest_request=1.0,
            issued_at_s=observation.delivered_at_s,
            label=f"{self.kind}:{self.state}",
        )


@dataclass
class AttackPolicy(_BasePolicy):
    kind: str = "attack"
    lateral_offset_m: float = 1.6

    def _decide(self, observation: Observation, interaction: Interaction) -> DriverAction:
        ahead = observation.rival_ahead()
        energy = self._own_energy(observation)
        has_margin = energy is None or energy > self.reserve_energy_j
        gap = float(ahead["gap_s"]) if ahead is not None else float("inf")
        engage = self._engage_threshold()
        cooling = interaction.cooldown > 0

        if ahead is None or not has_margin:
            self._set_state("idle")
        elif self.state == "committed":
            if gap > self.release_gap_s:
                self.memory["attempts"] = int(self.memory.get("attempts", 0)) + 1
                self.memory["cooldown"] = ATTEMPT_COOLDOWN_STEPS
                self._set_state("closing")
        elif gap <= engage and not cooling:
            self._set_state("committed")
        elif gap <= self.release_gap_s:
            self._set_state("cooling" if cooling else "closing")
        else:
            self._set_state("idle")

        if self.state == "cooling":
            return DriverAction(
                profile=DeploymentProfile.PUSH if has_margin else DeploymentProfile.CONSERVE,
                pace_scale=self.pace_scale,
                target_lateral_d_m=0.0,
                issued_at_s=observation.delivered_at_s,
                label=f"{self.kind}:{self.state}",
            )

        if self.state == "committed":
            profile = DeploymentProfile.OVERTAKE
            lateral = self.lateral_offset_m
        elif self.state == "closing":
            profile = DeploymentProfile.PUSH
            lateral = 0.5 * self.lateral_offset_m
        else:
            profile = DeploymentProfile.NEUTRAL
            lateral = 0.0
        return DriverAction(
            profile=profile,
            pace_scale=self.pace_scale,
            target_lateral_d_m=lateral,
            issued_at_s=observation.delivered_at_s,
            label=f"{self.kind}:{self.state}",
        )


@dataclass
class DefendPolicy(_BasePolicy):
    kind: str = "defend"
    lateral_offset_m: float = -1.4

    def _decide(self, observation: Observation, interaction: Interaction) -> DriverAction:
        behind = observation.rival_behind()
        energy = self._own_energy(observation)
        pressure_s = abs(float(behind["gap_s"])) if behind is not None else float("inf")
        engage = self._engage_threshold()

        if interaction.just_lost_a_position and interaction.ahead_id is not None:
            self._set_state("recovering")
            return DriverAction(
                profile=(
                    DeploymentProfile.PUSH
                    if (energy is None or energy > self.reserve_energy_j)
                    else DeploymentProfile.CONSERVE
                ),
                pace_scale=self.pace_scale,
                target_lateral_d_m=-self.lateral_offset_m,
                issued_at_s=observation.delivered_at_s,
                label=f"{self.kind}:{self.state}",
            )

        if behind is None:
            self._set_state("clear")
        elif self.state == "defending":
            if pressure_s > self.release_gap_s:
                self._set_state("watching")
        elif pressure_s <= engage:
            self._set_state("defending")
        else:
            self._set_state("watching")

        if self.state == "defending":
            profile = (
                DeploymentProfile.PUSH
                if (energy is None or energy > self.reserve_energy_j)
                else (DeploymentProfile.CONSERVE)
            )
            lateral = self.lateral_offset_m
        elif self.state == "watching":
            profile = DeploymentProfile.NEUTRAL
            lateral = 0.5 * self.lateral_offset_m
        else:
            profile = DeploymentProfile.CONSERVE
            lateral = 0.0
        return DriverAction(
            profile=profile,
            pace_scale=self.pace_scale,
            target_lateral_d_m=lateral,
            issued_at_s=observation.delivered_at_s,
            label=f"{self.kind}:{self.state}",
        )


POLICY_TYPES: dict[str, type[_BasePolicy]] = {
    "conserve": ConservePolicy,
    "normal": NormalPolicy,
    "attack": AttackPolicy,
    "defend": DefendPolicy,
}


def build_policy(kind: str, params: dict[str, float] | None = None) -> OpponentPolicy:

    if kind not in POLICY_TYPES:
        raise KeyError(f"unknown opponent policy {kind!r}; known kinds are {sorted(POLICY_TYPES)}")
    policy_type = POLICY_TYPES[kind]
    allowed = {"reserve_energy_j", "engage_gap_s", "release_gap_s", "pace_scale", "lateral_offset_m"}
    supplied = dict(params or {})
    unknown = set(supplied) - allowed
    if unknown:
        raise KeyError(f"policy {kind!r} does not accept parameters {sorted(unknown)}")
    return policy_type(**supplied)  # type: ignore[arg-type]


__all__ = [
    "ATTEMPT_COOLDOWN_STEPS",
    "INTERACTION_HISTORY_STEPS",
    "MAX_PACE_SCALE",
    "MIN_PACE_SCALE",
    "POLICY_TYPES",
    "PRESSURE_COMMIT_STEPS",
    "RECOVERY_STEPS",
    "RESPONSE_BIN_S",
    "RESPONSE_JITTER_CLIP",
    "RESPONSE_JITTER_FRACTION",
    "RESPONSE_STREAM_PREFIX",
    "AttackPolicy",
    "ConservePolicy",
    "DefendPolicy",
    "DriverAction",
    "Interaction",
    "NormalPolicy",
    "OpponentPolicy",
    "build_policy",
]
