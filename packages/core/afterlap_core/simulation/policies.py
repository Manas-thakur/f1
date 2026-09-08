"""Driver actions and frozen reactive opponent policies.

A policy receives **only** an :class:`~.observation.Observation`. It never sees
``WorldState`` and never sees another car's private state; the signature makes
that structural rather than a convention.

Aggressiveness is a bounded timing and energy preference. ``pace_scale`` is
clamped to at most 1.0, and 1.0 means "use the whole tyre envelope the physics
allows", so no policy setting can request a speed the friction envelope forbids.
Lateral targets are clamped to the track width by the engine. A policy therefore
cannot buy an overtake by asking for a geometry violation.
"""

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


@dataclass(frozen=True, slots=True)
class DriverAction:
    """One driver input.

    ``throttle`` and ``brake`` are ``None`` by default, meaning "let the driver
    model's speed governor decide". A test or a controller that wants direct
    longitudinal authority sets them explicitly; the engine still clamps the
    resulting force to the tyre envelope.
    """

    profile: DeploymentProfile = DeploymentProfile.NEUTRAL
    pace_scale: float = 1.0
    target_lateral_d_m: float = 0.0
    throttle: float | None = None
    brake: float | None = None
    harvest_request: float = 1.0
    issued_at_s: float = 0.0
    label: str = ""

    def __post_init__(self) -> None:
        if not MIN_PACE_SCALE <= self.pace_scale <= MAX_PACE_SCALE:
            raise ValueError(
                f"pace_scale {self.pace_scale} is outside the bounded preference range "
                f"[{MIN_PACE_SCALE}, {MAX_PACE_SCALE}]; aggressiveness may not exceed the envelope"
            )
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
    """Frozen opponent identity: an observation in, a driver action out."""

    @property
    def policy_hash(self) -> str: ...

    def react(self, observation: Observation, rng: np.random.Generator) -> DriverAction: ...

    def capture(self) -> dict[str, Any]: ...

    def restore(self, memory: dict[str, Any]) -> None: ...


@dataclass
class _BasePolicy:
    """Shared parameter handling, memory and hashing for the frozen policies."""

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
        self.memory.setdefault("state", "idle")

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

    def _own_energy(self, observation: Observation) -> float | None:
        """Own stored energy, or ``None`` when the channel is unavailable.

        A missing channel is never substituted with zero; the policy falls back
        to an energy-agnostic branch instead.
        """
        if not observation.has("battery_energy_j"):
            return None
        return observation.get("battery_energy_j")

    def _set_state(self, name: str) -> None:
        self.memory["state"] = name

    @property
    def state(self) -> str:
        return str(self.memory.get("state", "idle"))

    def react(self, observation: Observation, rng: np.random.Generator) -> DriverAction:
        """Template method: refuse to act on an unusable observation.

        Before the sensor delay has elapsed, or when a feed is missing, there is
        no observation to reason about. The policy holds a neutral action rather
        than treating absent channels as zeros.
        """
        if observation.quality is not Quality.VALID:
            self._set_state("no_observation_hold")
            return DriverAction(
                profile=DeploymentProfile.NEUTRAL,
                pace_scale=self.pace_scale,
                target_lateral_d_m=0.0,
                issued_at_s=observation.delivered_at_s,
                label=f"{self.kind}:no_observation_hold",
            )
        return self._decide(observation, rng)

    def _decide(self, observation: Observation, rng: np.random.Generator) -> DriverAction:
        raise NotImplementedError


@dataclass
class NormalPolicy(_BasePolicy):
    """Baseline deployment schedule driven by local track curvature.

    Deploys on the straights, backs off through a corner, and never dips below
    the configured reserve. Deterministic: the same observation always yields
    the same action.
    """

    kind: str = "normal"

    def _decide(self, observation: Observation, rng: np.random.Generator) -> DriverAction:
        del rng
        curvature = abs(float(observation.context["curvature_inv_m"]))
        energy = self._own_energy(observation)
        straight = curvature < 2.0e-3
        if energy is not None and energy <= self.reserve_energy_j:
            profile = DeploymentProfile.CONSERVE
            self._set_state("reserve_floor")
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
    """Targets a later reserve: harvests whenever it legally can.

    It only spends above ``reserve_energy_j`` and pushes back to harvesting as
    soon as the margin is thin, which is what makes a conserve opponent
    interesting to plan against.
    """

    kind: str = "conserve"
    pace_scale: float = 0.95

    def _decide(self, observation: Observation, rng: np.random.Generator) -> DriverAction:
        del rng
        energy = self._own_energy(observation)
        if energy is None:
            self._set_state("energy_unknown_hold")
            profile = DeploymentProfile.CONSERVE
        elif energy < self.reserve_energy_j:
            self._set_state("rebuilding")
            profile = DeploymentProfile.HARVEST
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
    """Evaluates a feasible corridor to the car ahead before committing.

    Finite states: ``idle`` -> ``closing`` -> ``committed`` -> ``idle``. The
    engage/release gap pair gives hysteresis so a jittery gap measurement cannot
    make the opponent flicker between attacking and cruising.
    """

    kind: str = "attack"
    lateral_offset_m: float = 1.6

    def _decide(self, observation: Observation, rng: np.random.Generator) -> DriverAction:
        del rng
        ahead = observation.rival_ahead()
        energy = self._own_energy(observation)
        has_margin = energy is None or energy > self.reserve_energy_j
        gap = float(ahead["gap_s"]) if ahead is not None else float("inf")

        if ahead is None or not has_margin:
            self._set_state("idle")
        elif self.state == "committed":
            if gap > self.release_gap_s:
                self._set_state("closing")
        elif gap <= self.engage_gap_s:
            self._set_state("committed")
        elif gap <= self.release_gap_s:
            self._set_state("closing")
        else:
            self._set_state("idle")

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
    """Preserves energy and takes a legal defensive line when pressured.

    The defensive lateral offset is a *preference*; the engine clamps it to the
    track width, and a policy can never request an offset that would place the
    car on top of another. Contact is resolved by geometry, not by the policy.
    """

    kind: str = "defend"
    lateral_offset_m: float = -1.4

    def _decide(self, observation: Observation, rng: np.random.Generator) -> DriverAction:
        del rng
        behind = observation.rival_behind()
        energy = self._own_energy(observation)
        pressure_s = abs(float(behind["gap_s"])) if behind is not None else float("inf")

        if behind is None:
            self._set_state("clear")
        elif self.state == "defending":
            if pressure_s > self.release_gap_s:
                self._set_state("watching")
        elif pressure_s <= self.engage_gap_s:
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
    """Construct a frozen policy by name.

    Unknown parameters are rejected rather than ignored: a silently dropped
    aggressiveness setting would make an experiment manifest describe an
    opponent that was never actually run.
    """
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
    "MAX_PACE_SCALE",
    "MIN_PACE_SCALE",
    "POLICY_TYPES",
    "AttackPolicy",
    "ConservePolicy",
    "DefendPolicy",
    "DriverAction",
    "NormalPolicy",
    "OpponentPolicy",
    "build_policy",
]
