"""The only controller input path.

``observe`` reads the buffered truth at ``now - delay_s``, adds keyed sensor
noise, quantises, drops unavailable channels and returns an immutable
``Observation``. Anything the controller is not entitled to know is **absent**
from the mapping, not present as zero and not present as a null. A caller can
therefore write ``"battery_energy_j" in observation.channels`` and get a
truthful answer about availability.

``debug_truth`` exists for test and diagnostic use. It is a separate function
with a separate call site; ``observe`` never calls it and no field it produces
appears in an ``Observation``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from afterlap_contracts import Provenance, Quality

from .config import ObservationConfig

if TYPE_CHECKING:  # pragma: no cover
    from .state import WorldState

OWN_CHANNELS: tuple[str, ...] = (
    "speed_mps",
    "progress_m",
    "s_m",
    "lap",
    "lateral_d_m",
    "acceleration_mps2",
    "battery_energy_j",
    "battery_temperature_k",
    "recharge_this_lap_j",
    "recharge_cumulative_j",
    "electrical_power_w",
)
"""Own-car channels that may be observed. ``battery_energy_j`` is gated."""

RIVAL_CHANNELS: tuple[str, ...] = (
    "relative_progress_m",
    "relative_speed_mps",
    "gap_s",
    "lateral_d_m",
    "speed_mps",
)
"""Rival channels that are always derivable from an external observer's view."""

GATED_RIVAL_CHANNELS: tuple[str, ...] = ("battery_energy_j",)
"""Rival channels that require an explicit authorisation to be present at all."""


@dataclass(frozen=True, slots=True)
class Observation:
    """What one car's controller is allowed to know at one cutoff time.

    ``channels`` and each entry of ``rivals`` are read-only mappings whose keys
    are the *available* channels. An unavailable channel has no key.
    """

    car_id: str
    observed_at_s: float
    delivered_at_s: float
    channels: MappingProxyType
    rivals: tuple[MappingProxyType, ...]
    context: MappingProxyType
    provenance: Provenance
    quality: Quality

    def has(self, channel: str) -> bool:
        return channel in self.channels

    def get(self, channel: str) -> float:
        """Fetch a channel or fail loudly. There is no zero-valued fallback."""
        if channel not in self.channels:
            raise KeyError(
                f"channel {channel!r} is not available in this observation; "
                "an unavailable channel is absent, never zero"
            )
        return float(self.channels[channel])

    def rival_ahead(self) -> MappingProxyType | None:
        """The nearest rival in front, or ``None`` when there is none."""
        ahead = [rival for rival in self.rivals if rival["relative_progress_m"] > 0.0]
        if not ahead:
            return None
        return min(ahead, key=lambda rival: rival["relative_progress_m"])

    def rival_behind(self) -> MappingProxyType | None:
        behind = [rival for rival in self.rivals if rival["relative_progress_m"] < 0.0]
        if not behind:
            return None
        return max(behind, key=lambda rival: rival["relative_progress_m"])

    def as_plain(self) -> dict[str, Any]:
        return {
            "car_id": self.car_id,
            "observed_at_s": self.observed_at_s,
            "delivered_at_s": self.delivered_at_s,
            "channels": dict(self.channels),
            "rivals": [dict(rival) for rival in self.rivals],
            "context": dict(self.context),
            "provenance": self.provenance.value,
            "quality": self.quality.value,
        }

    def canonical_bytes(self) -> bytes:
        """Deterministic serialisation used by the isolation byte-identity test."""
        return json.dumps(self.as_plain(), sort_keys=True, separators=(",", ":")).encode("utf-8")


def _known(value: float) -> float | None:
    """``nan`` from an unsurveyed corridor becomes an honest ``None`` on the wire."""
    return None if math.isnan(value) else value


def _quantise(value: float, quantum: float) -> float:
    if quantum <= 0.0:
        return value
    return round(value / quantum) * quantum


def _noise(world: WorldState, car_id: str, channel: str, cutoff_s: float, sigma: float) -> float:
    """Keyed sensor noise.

    Keyed by ``(channel, car, physical time bin)`` so two experiment branches
    that reach the same physical instant see the same disturbance regardless of
    how many calls each made to get there.
    """
    if sigma <= 0.0:
        return 0.0
    assert world.keyed is not None
    return world.keyed.normal(f"sensor:{channel}:{car_id}", cutoff_s, scale=sigma)


def _sample_at(world: WorldState, cutoff_s: float):
    """Newest buffered truth sample at or before ``cutoff_s``.

    Zero-order hold rather than interpolation: a real delayed feed delivers the
    last packet it had, and holding is exactly restorable from a snapshot.
    """
    chosen = None
    for sample in world.sensor_buffer:
        if sample.session_time_s <= cutoff_s + 1e-12:
            chosen = sample
        else:
            break
    return chosen


def observe(
    world: WorldState,
    sensor_config: ObservationConfig,
    car_id: str | None = None,
) -> dict[str, Observation]:
    """Build the delayed, noisy, gated observation for one car or every car."""
    now = world.race.session_time_s
    cutoff = now - float(sensor_config.delay_s.value)
    sample = _sample_at(world, cutoff)
    targets = [car_id] if car_id is not None else sorted(world.cars)

    if sample is None:
        # Nothing old enough has been recorded yet. That is a real operational
        # state and it is reported as missing, not filled in with the present.
        return {
            target: Observation(
                car_id=target,
                observed_at_s=cutoff,
                delivered_at_s=now,
                channels=MappingProxyType({}),
                rivals=(),
                context=MappingProxyType(
                    {
                        "flags": [flag.value for flag in world.race.flags],
                        "track_id": world.track.id,
                        "delay_s": float(sensor_config.delay_s.value),
                        "reason": "no_observation_older_than_delay",
                    }
                ),
                provenance=sensor_config.energy_provenance,
                quality=Quality.MISSING,
            )
            for target in targets
        }

    sigmas = {name: float(param.value) for name, param in sensor_config.noise_sigma.items()}
    quanta = {name: float(param.value) for name, param in sensor_config.quantisation.items()}
    result: dict[str, Observation] = {}

    for target in targets:
        truth = sample.cars[target]
        channels: dict[str, float] = {}
        for channel in OWN_CHANNELS:
            if channel == "battery_energy_j" and not sensor_config.energy_channel_available:
                continue
            raw = truth[channel]
            value = raw + _noise(world, target, channel, sample.session_time_s, sigmas.get(channel, 0.0))
            channels[channel] = _quantise(value, quanta.get(channel, 0.0))

        rivals: list[MappingProxyType] = []
        for other in sorted(sample.cars):
            if other == target:
                continue
            other_truth = sample.cars[other]
            relative_progress = other_truth["progress_m"] - truth["progress_m"]
            own_speed = truth["speed_mps"]
            gap_s = relative_progress / own_speed if abs(own_speed) > 1e-6 else float("inf")
            rival: dict[str, Any] = {
                "car_id": other,
                "relative_progress_m": relative_progress
                + _noise(
                    world,
                    target,
                    "relative_progress_m",
                    sample.session_time_s,
                    sigmas.get("relative_progress_m", 0.0),
                ),
                "relative_speed_mps": other_truth["speed_mps"]
                - own_speed
                + _noise(
                    world,
                    target,
                    "relative_speed_mps",
                    sample.session_time_s,
                    sigmas.get("relative_speed_mps", 0.0),
                ),
                "gap_s": gap_s
                + _noise(world, target, "gap_s", sample.session_time_s, sigmas.get("gap_s", 0.0)),
                "lateral_d_m": other_truth["lateral_d_m"]
                + _noise(
                    world,
                    target,
                    "rival_lateral_d_m",
                    sample.session_time_s,
                    sigmas.get("rival_lateral_d_m", 0.0),
                ),
                "speed_mps": other_truth["speed_mps"]
                + _noise(
                    world,
                    target,
                    "rival_speed_mps",
                    sample.session_time_s,
                    sigmas.get("rival_speed_mps", 0.0),
                ),
            }
            for name in RIVAL_CHANNELS:
                if name in quanta:
                    rival[name] = _quantise(rival[name], quanta[name])
            if sensor_config.expose_rival_energy:
                # Only ever populated when a configuration explicitly authorises
                # it; there is no real-world measurement behind this channel.
                rival["battery_energy_j"] = other_truth["battery_energy_j"]
            rivals.append(MappingProxyType(rival))

        context = MappingProxyType(
            {
                "flags": [flag.value for flag in world.race.flags],
                "track_id": world.track.id,
                "track_length_m": world.track.length,
                "curvature_inv_m": world.track.curvature_at(truth["s_m"]),
                "mu": world.track.mu_at(truth["s_m"]),
                "width_m": _known(world.track.width_at(truth["s_m"])),
                "active_profile": truth["active_profile_code"],
                "delay_s": float(sensor_config.delay_s.value),
                "energy_channel_available": sensor_config.energy_channel_available,
                "rival_energy_exposed": sensor_config.expose_rival_energy,
            }
        )
        result[target] = Observation(
            car_id=target,
            observed_at_s=sample.session_time_s,
            delivered_at_s=now,
            channels=MappingProxyType(channels),
            rivals=tuple(rivals),
            context=context,
            provenance=sensor_config.energy_provenance,
            quality=Quality.VALID,
        )
    return result


def debug_truth(world: WorldState) -> dict[str, Any]:
    """Complete hidden truth, for tests and offline diagnosis only.

    This is deliberately a free function taking the private ``WorldState``. It
    is never called by :func:`observe`, its output never reaches an
    ``Observation``, and nothing in the controller path imports it.
    """
    return {
        "session_time_s": world.race.session_time_s,
        "cars": {
            car_id: {
                "progress_m": state.progress_m,
                "speed_mps": state.speed_mps,
                "battery_energy_j": state.battery_energy_j,
                "battery_temperature_k": state.battery_temperature_k,
                "recharge_cumulative_j": state.recharge_ledger_j,
                "active_profile": state.active_profile.value,
            }
            for car_id, state in sorted(world.cars.items())
        },
    }


__all__ = [
    "GATED_RIVAL_CHANNELS",
    "OWN_CHANNELS",
    "RIVAL_CHANNELS",
    "Observation",
    "debug_truth",
    "observe",
]
