from __future__ import annotations

import copy
import math
from dataclasses import asdict, replace
from itertools import combinations
from typing import Any

from afterlap_contracts import DeploymentProfile

from ..simulation.engine import Simulator
from ..simulation.observation import Observation
from ..simulation.policies import DriverAction
from ..simulation.track import footprints_overlap
from ..simulation.wake import WakeModel
from .circuit import circuit
from .factory import RaceWeather, race_bundle
from .settings import RaceSettings


class RaceSession:
    def __init__(self, settings: RaceSettings | None = None) -> None:
        self.settings = settings or RaceSettings()
        self.bundle = race_bundle(self.settings)
        self.track, self.map = circuit(self.settings.circuit, self.settings.wetness)
        self.simulator = Simulator().reset(
            self.bundle,
            environment=RaceWeather(self.settings.temperature_k, self.settings.wind_mps),
            wake=WakeModel() if self.settings.wake else None,
        )
        self.simulator.world.policies.clear()
        self.overrides: dict[str, DriverAction] = {}
        self.bms_profiles: dict[str, DeploymentProfile] = {}
        self.lanes = {
            car: initial.lateral_d_m.value for car, initial in self.bundle.scenario.initial_states.items()
        }
        self.finishes: dict[str, float] = {}
        self.events: list[dict[str, Any]] = []
        self.status = "paused"
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
        lane = self.lanes[car_id]
        profile = DeploymentProfile.CONSERVE
        ahead = observation.rival_ahead()
        if ahead is not None and ahead["relative_progress_m"] < 50:
            profile = DeploymentProfile.PUSH
            if abs(ahead["lateral_d_m"] - lane) < 2.5:
                candidate = -2.5 if ahead["lateral_d_m"] >= 0 else 2.5
                clear = all(
                    abs(rival["relative_progress_m"]) > 25 or abs(rival["lateral_d_m"] - candidate) > 2.5
                    for rival in observation.rivals
                )
                if clear:
                    lane = candidate
        self.lanes[car_id] = lane
        brake = None
        throttle = None
        own_speed = observation.channels.get("speed_mps", 0)
        obstacles = [
            rival
            for rival in observation.rivals
            if rival["relative_progress_m"] > 0
            and abs(rival["lateral_d_m"] - observation.channels.get("lateral_d_m", lane)) < 2.8
        ]
        if obstacles:
            obstacle = min(obstacles, key=lambda rival: rival["relative_progress_m"])
            gap = obstacle["relative_progress_m"]
            safe_gap = 12 + 0.5 * own_speed
            acceleration = (obstacle["speed_mps"] - own_speed) / 0.5 + (gap - safe_gap) * 0.8
            if acceleration < 0:
                throttle = 0.0
                brake = min(1.0, -acceleration / 12)
        if observation.channels.get("battery_energy_j", 0) < 6e5:
            profile = DeploymentProfile.HARVEST
        progress = float(observation.channels.get("progress_m", 0))
        straight = all(
            abs(self.track.curvature_at(progress + offset)) < 0.001 for offset in (0, 50, 100, 150)
        )
        return DriverAction(
            profile=self.bms_profiles.get(car_id, profile),
            pace_scale=0.90 + (int(car_id[-2:]) % 5) * 0.01,
            target_lateral_d_m=lane,
            low_drag=straight and brake is None,
            throttle=throttle,
            brake=brake,
        )

    def advance(self, duration_s: float = 0.1) -> None:
        if not math.isfinite(duration_s) or not 0 < duration_s <= 10:
            raise ValueError("advance duration must be in (0, 10]")
        remaining = duration_s
        while remaining > 1e-9 and not self.done:
            h = min(self.settings.dt_s, remaining, self.settings.time_limit_s - self.simulator.session_time_s)
            if h <= 1e-9:
                self.status = "truncated"
                break
            actions = None
            cadence_steps = round(0.1 / self.settings.dt_s)
            if self.steps % cadence_steps == 0:
                actions = {
                    car: replace(
                        self.overrides[car] if car in self.overrides else self.automatic_action(observation),
                        issued_at_s=self.simulator.session_time_s,
                    )
                    for car, observation in self.observations().items()
                }
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
                5.6,
                2.0,
                b.s_m,
                b.lateral_d_m,
                b.heading_error_rad,
                5.6,
                2.0,
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
        observations = self.observations()
        cars = []
        for car_id, observation in observations.items():
            channels = dict(observation.channels)
            cars.append(
                {
                    "id": car_id,
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
            "failure": self.failure,
            "cars": cars,
            "events": self.events,
            "provenance": "simulated; uncalibrated cars and scaled circuit artwork",
        }

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(
            {
                "world": self.simulator.snapshot(),
                "overrides": self.overrides,
                "bms_profiles": self.bms_profiles,
                "lanes": self.lanes,
                "finishes": self.finishes,
                "events": self.events,
                "steps": self.steps,
                "failure": self.failure,
                "status": self.status,
            }
        )

    def restore(self, snapshot: dict[str, Any]) -> None:
        saved = copy.deepcopy(snapshot)
        self.simulator.restore(saved["world"])
        for key in ("overrides", "bms_profiles", "lanes", "finishes", "events", "steps", "failure", "status"):
            setattr(self, key, saved[key])

    def manifest(self) -> dict[str, Any]:
        return {
            "type": "manifest",
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
