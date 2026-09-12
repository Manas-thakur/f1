from __future__ import annotations

import copy
import math
from dataclasses import asdict, replace
from itertools import combinations
from typing import Any

from afterlap_contracts import DeploymentProfile

from ..rng import StreamRegistry
from ..simulation.engine import Simulator
from ..simulation.observation import Observation
from ..simulation.policies import DriverAction
from ..simulation.state import PassRecord
from ..simulation.track import footprints_overlap
from ..simulation.wake import WakeModel
from .circuit import circuit
from .driver_names import driver_names
from .factory import race_bundle
from .racecraft import Racecraft
from .settings import RaceSettings
from .variability import RaceWeather


class RaceSession:
    def __init__(self, settings: RaceSettings | None = None) -> None:
        self.settings = settings or RaceSettings()
        self.bundle = race_bundle(self.settings)
        self.driver_names = driver_names(self.settings.seed, tuple(self.bundle.car_configs))
        self.track, self.map = circuit(self.settings.circuit, 0)
        self.weather = RaceWeather(
            self.settings.temperature_k,
            self.settings.wind_mps,
            self.settings.wetness,
            self.track.length,
            self.settings.variability,
            self.settings.seed,
        )
        self.simulator = Simulator().reset(
            self.bundle,
            environment=self.weather,
            wake=WakeModel() if self.settings.wake else None,
        )
        self.simulator.world.policies.clear()
        self.overrides: dict[str, DriverAction] = {}
        self.bms_profiles: dict[str, DeploymentProfile] = {}
        self.lanes = {
            car: initial.lateral_d_m.value for car, initial in self.bundle.scenario.initial_states.items()
        }
        streams = StreamRegistry(self.settings.seed)
        self.drivers = {
            car: Racecraft(
                self.settings.variability.sample_driver(streams, car),
                lane,
                length_m=self.bundle.car_configs[car].length_m.value,
                width_m=self.bundle.car_configs[car].width_m.value,
            )
            for car, lane in self.lanes.items()
        }
        for car, lane in self.lanes.items():
            self.simulator.world.active_actions[car] = DriverAction(
                target_lateral_d_m=lane, acceleration_ceiling_mps2=0
            )
        self.next_decision_s = 0.0
        self.finishes: dict[str, float] = {}
        self.events: list[dict[str, Any]] = []
        self.status = "paused"
        self.started = False
        self.failure: str | None = None
        self.steps = 0

    @property
    def done(self) -> bool:
        return self.status in {"finished", "failed", "truncated"}

    def observations(self) -> dict[str, Observation]:
        return self.simulator.observe()

    def control(self, car_id: str, action: DriverAction | None) -> None:
        if car_id not in self.bundle.car_configs:
            raise ValueError("unknown car")
        if action is None:
            self.overrides.pop(car_id, None)
        else:
            if not math.isfinite(action.target_lateral_d_m) or abs(action.target_lateral_d_m) > 5:
                raise ValueError("lateral target must be within the synthetic corridor")
            self.overrides[car_id] = action

    def automatic_action(self, observation: Observation) -> DriverAction:
        car_id = observation.car_id
        driver = self.drivers[car_id]
        prior = driver.state
        action = driver.react(observation, self.track)
        if driver.state != prior and driver.state in {"committed", "aborting"} and driver.rival_id:
            event = PassRecord(
                observation.delivered_at_s,
                car_id,
                driver.rival_id,
                "pass_intent" if driver.state == "committed" else "aborted_attempt",
            )
            self.simulator.world.passes.append(event)
            self.events.append(asdict(event))
        self.lanes[car_id] = action.target_lateral_d_m
        return replace(action, profile=self.bms_profiles.get(car_id, action.profile))

    def advance(self, duration_s: float = 0.1) -> None:
        if not math.isfinite(duration_s) or not 0 < duration_s <= 10:
            raise ValueError("advance duration must be in (0, 10]")
        if not self.done:
            self.started = True
        remaining = duration_s
        while remaining > 1e-9 and not self.done:
            h = min(self.settings.dt_s, remaining, self.settings.time_limit_s - self.simulator.session_time_s)
            if h <= 1e-9:
                self.status = "truncated"
                break
            actions = None
            if self.simulator.session_time_s >= self.next_decision_s - 1e-9:
                self.next_decision_s += 0.1
                actions = {
                    car: replace(
                        self.overrides[car] if car in self.overrides else self.automatic_action(observation),
                        issued_at_s=self.simulator.session_time_s,
                    )
                    for car, observation in self.observations().items()
                }
            h = min(h, self.next_decision_s - self.simulator.session_time_s)
            report = self.simulator.step(actions, h)
            self.steps += 1
            remaining -= h
            self.events.extend(asdict(event) for event in report.passes)
            self.events = self.events[-100:]
            if report.envelope_exceedances:
                self.failure = "lateral tyre envelope exceeded; reduced model cannot continue"
            self._check_contacts()
            self._finish_crossings(h)
            if self.failure is not None:
                self.status = "failed"
            elif len(self.finishes) == self.settings.cars:
                self.status = "finished"
            elif self.simulator.session_time_s >= self.settings.time_limit_s - 1e-9:
                self.status = "truncated"

    def _check_contacts(self) -> None:
        world = self.simulator.world
        for a, b in combinations(world.cars.values(), 2):
            if a.car_id in self.finishes or b.car_id in self.finishes:
                continue
            if footprints_overlap(
                self.simulator.geometry,
                a.s_m,
                a.lateral_d_m,
                a.heading_error_rad,
                world.car_configs[a.car_id].length_m.value,
                world.car_configs[a.car_id].width_m.value,
                b.s_m,
                b.lateral_d_m,
                b.heading_error_rad,
                world.car_configs[b.car_id].length_m.value,
                world.car_configs[b.car_id].width_m.value,
            ):
                self.failure = f"contact: {a.car_id} / {b.car_id}; collision response is unsupported"
                break

    def _finish_crossings(self, h: float) -> None:
        target = self.settings.laps * self.track.length
        for car_id, state in self.simulator.world.cars.items():
            if car_id not in self.finishes and state.progress_m >= target:
                overshoot_s = (state.progress_m - target) / max(state.speed_mps, 1e-6)
                self.finishes[car_id] = self.simulator.session_time_s - min(h, overshoot_s)

    def frame(self) -> dict[str, Any]:
        observations = self.simulator.observe(include_rivals=False)
        cars = []
        for car_id, observation in observations.items():
            channels = dict(observation.channels)
            cars.append(
                {
                    "id": car_id,
                    "driver_name": self.driver_names[car_id],
                    "channels": channels,
                    "observed_at_s": observation.observed_at_s,
                    "quality": observation.quality.value,
                    "requested_profile": self.overrides[car_id].profile.value
                    if car_id in self.overrides
                    else "auto",
                    "finish_time_s": self.finishes.get(car_id),
                }
            )
        cars.sort(
            key=lambda car: (
                0 if car["finish_time_s"] is not None else 1,
                car["finish_time_s"]
                if car["finish_time_s"] is not None
                else -car["channels"].get("progress_m", 0),
            )
        )
        return {
            "type": "frame",
            "version": "race-v1",
            "settings": self.settings.model_dump(),
            "time_s": self.simulator.session_time_s,
            "steps": self.steps,
            "status": self.status,
            "started": self.started,
            "failure": self.failure,
            "cars": cars,
            "events": self.events,
            "provenance": "simulated; uncalibrated cars and scaled circuit artwork",
        }

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(
            {
                "model_version": "race-physics-v2",
                "settings": self.settings.model_dump(),
                "drivers": self.drivers,
                "next_decision_s": self.next_decision_s,
                "world": self.simulator.snapshot(),
                "overrides": self.overrides,
                "bms_profiles": self.bms_profiles,
                "lanes": self.lanes,
                "finishes": self.finishes,
                "events": self.events,
                "steps": self.steps,
                "failure": self.failure,
                "status": self.status,
                "started": self.started,
            }
        )

    def restore(self, snapshot: dict[str, Any]) -> None:
        if (
            snapshot.get("model_version") != "race-physics-v2"
            or snapshot.get("settings") != self.settings.model_dump()
        ):
            raise ValueError("incompatible race model or settings in checkpoint")
        saved = copy.deepcopy(snapshot)
        self.simulator.restore(saved["world"])
        for key in (
            "drivers",
            "next_decision_s",
            "overrides",
            "bms_profiles",
            "lanes",
            "finishes",
            "events",
            "steps",
            "failure",
            "status",
            "started",
        ):
            setattr(self, key, saved[key])

    def manifest(self) -> dict[str, Any]:
        return {
            "type": "manifest",
            "model_version": "race-physics-v2",
            "environment_version": "race-bms-v1",
            "drivers": {car: driver.traits.model_dump() for car, driver in self.drivers.items()},
            "weather": self.weather.manifest(),
            "initial_states": {
                car: state.model_dump(mode="json")
                for car, state in self.bundle.scenario.initial_states.items()
            },
            "sensor_config": self.bundle.scenario.observation.model_dump(mode="json"),
            "version": "race-v1",
            "settings": self.settings.model_dump(),
            "bundle_hash": self.bundle.bundle_hash,
            "source_revision": self.map["source_revision"],
            "geometry_hash": self.map["source_sha256"],
            "geometry_provenance": self.track.geometry_provenance,
            "cars": {car: config.model_dump(mode="json") for car, config in self.bundle.car_configs.items()},
            "integrator": "RK2 float64",
            "observation": "delayed simulated sensors; rival energy hidden",
        }
