from __future__ import annotations

import copy
import math
from dataclasses import asdict, replace
from itertools import combinations
from typing import Any

from afterlap_contracts import DeploymentProfile

from ..rng import StreamRegistry
from ..simulation.energy_limits import EventEnergyLimits
from ..simulation.engine import Simulator
from ..simulation.observation import Observation
from ..simulation.policies import DriverAction
from ..simulation.state import PassRecord
from ..simulation.track import footprints_overlap
from ..simulation.wake import WakeModel
from .circuit import circuit
from .factory import race_bundle
from .racecraft import Racecraft
from .regulations import RaceRegulations2026
from .settings import RaceSettings
from .storyline import StorylineDirector
from .tyres import TyreState, sample_compound
from .variability import RaceWeather


class RaceSession:
    def __init__(self, settings: RaceSettings | None = None) -> None:
        self.settings = settings or RaceSettings()
        self.regulations = RaceRegulations2026()
        self.bundle = race_bundle(self.settings)
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
            event_limits=EventEnergyLimits.race_2026(),
            wake=WakeModel() if self.settings.wake else None,
        )
        self.simulator.world.policies.clear()
        self.overrides: dict[str, DriverAction] = {}
        self.bms_profiles: dict[str, DeploymentProfile] = {}
        self.lanes = {
            car: initial.lateral_d_m.value for car, initial in self.bundle.scenario.initial_states.items()
        }
        streams = StreamRegistry(self.settings.seed)
        self.tyre_streams = StreamRegistry(
            self.settings.seed,
            tuple(f"tyres:{car}" for car in self.lanes),
        )
        self.drivers = {
            car: Racecraft(
                self.settings.variability.sample_driver(streams, car),
                lane,
                length_m=self.bundle.car_configs[car].length_m.value,
                width_m=self.bundle.car_configs[car].width_m.value,
            )
            for car, lane in self.lanes.items()
        }
        self.tyres = {}
        for car_id, initial in self.bundle.scenario.initial_states.items():
            rng = self.tyre_streams.stream(f"tyres:{car_id}")
            compound = sample_compound(rng)
            self.tyres[car_id] = TyreState(
                compound=compound,
                condition=1,
                change_threshold=float(rng.uniform(0.12, 0.24)),
                last_progress_m=initial.progress_m.value,
                next_compound=sample_compound(rng, compound),
                service_duration_s=float(rng.uniform(2, 3)),
            )
            self.simulator.world.cars[car_id].tyre_grip_multiplier = self.tyres[car_id].grip
        self.storyline = StorylineDirector(
            self.settings.seed,
            tuple(self.lanes),
            self.settings.storyline,
        )
        for car, lane in self.lanes.items():
            self.simulator.world.active_actions[car] = DriverAction(
                target_lateral_d_m=lane, acceleration_ceiling_mps2=0
            )
        self.next_decision_s = 0.0
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
        driver = self.drivers[car_id]
        tyre = self.tyres[car_id]
        if tyre.phase == "service":
            return DriverAction(
                profile=DeploymentProfile.HARVEST,
                pace_scale=0.7,
                target_lateral_d_m=driver.lane,
                acceleration_ceiling_mps2=-15,
                brake_floor=1,
                label="pit_service",
            )
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
        if tyre.phase == "entry":
            state = self.simulator.world.cars[car_id]
            box_s = self._pit_box_s(car_id)
            limit = self.regulations.pit_lane_speed_limit_mps
            if state.s_m < self._pit_lane_start_s:
                distance = self._pit_lane_start_s - state.s_m
                braking_distance = max(0, state.speed_mps**2 - limit**2) / 24 + 5
                ceiling = -12 if distance <= braking_distance else 3
            else:
                distance = max(0, box_s - state.s_m)
                stop_distance = state.speed_mps**2 / 24 + 5
                ceiling = -12 if distance <= stop_distance else (0 if state.speed_mps <= limit else -4)
            action = replace(
                action,
                profile=DeploymentProfile.HARVEST,
                pace_scale=0.7,
                acceleration_ceiling_mps2=ceiling,
                label="pit_entry",
            )
        elif tyre.phase == "exit":
            action = replace(
                action,
                pace_scale=min(0.9, action.pace_scale),
                acceleration_ceiling_mps2=min(3, action.acceleration_ceiling_mps2 or 3),
                label="pit_exit",
            )
        else:
            action, event = self.storyline.direct(car_id, observation, action)
            if event is not None:
                self.events.append(event)
        self.lanes[car_id] = action.target_lateral_d_m
        if tyre.phase == "track":
            action = replace(action, profile=self.bms_profiles.get(car_id, action.profile))
        return action

    def _requested_action(self, observation: Observation) -> DriverAction:
        car_id = observation.car_id
        if self.tyres[car_id].phase != "track" or car_id not in self.overrides:
            return self.automatic_action(observation)
        return self.overrides[car_id]

    def _pit_box_s(self, car_id: str) -> float:
        index = int(car_id.rsplit("-", maxsplit=1)[-1]) - 1
        return self.track.length - 42 - index * 5.5

    @property
    def _pit_lane_start_s(self) -> float:
        return self.track.length - 250

    def _visual_lateral(self, car_id: str) -> float:
        tyre = self.tyres[car_id]
        state = self.simulator.world.cars[car_id]
        track_lateral = state.lateral_d_m
        pit_lateral = -13.0
        if tyre.phase == "entry":
            start = self.track.length - 350
            ratio = min(1, max(0, (state.s_m - start) / max(1, self._pit_box_s(car_id) - start)))
            return track_lateral + (pit_lateral - track_lateral) * ratio
        if tyre.phase == "service":
            return pit_lateral
        if tyre.phase == "exit":
            remaining = max(0, tyre.exit_after_progress_m - state.progress_m)
            ratio = min(1, remaining / 220)
            return track_lateral + (pit_lateral - track_lateral) * ratio
        return track_lateral

    def _update_tyres(self, h: float) -> None:
        now = self.simulator.session_time_s
        for car_id, tyre in self.tyres.items():
            state = self.simulator.world.cars[car_id]
            distance = max(0, state.progress_m - tyre.last_progress_m)
            tyre.last_progress_m = state.progress_m
            tyre.wear(distance, state.tyre_utilisation, self.settings.storyline.tyre_wear_scale)
            state.tyre_grip_multiplier = tyre.grip
            if (
                self.settings.storyline.pit_stops
                and tyre.phase == "track"
                and not tyre.requested
                and (
                    tyre.condition <= tyre.change_threshold
                    or (
                        len(tyre.used_compounds) < self.regulations.required_dry_compounds
                        and self.regulations.mandatory_stop_due(
                            state.progress_m,
                            self.settings.laps * self.track.length,
                        )
                    )
                )
            ):
                tyre.requested = True
                self.events.append(
                    {
                        "kind": "pit_stop_requested",
                        "car_id": car_id,
                        "compound": tyre.next_compound.value,
                        "session_time_s": now,
                    }
                )
            if tyre.phase == "track" and tyre.requested and state.s_m >= self.track.length - 350:
                tyre.phase = "entry"
                self.events.append({"kind": "pit_entry", "car_id": car_id, "session_time_s": now})
            elif tyre.phase == "entry" and state.speed_mps <= 0.25:
                tyre.phase = "service"
                tyre.service_remaining_s = tyre.service_duration_s
                self.events.append(
                    {
                        "kind": "pit_service_started",
                        "car_id": car_id,
                        "compound": tyre.next_compound.value,
                        "duration_s": tyre.service_duration_s,
                        "session_time_s": now,
                    }
                )
            elif tyre.phase == "service":
                tyre.service_remaining_s = max(0, tyre.service_remaining_s - h)
                if tyre.service_remaining_s <= 0:
                    fitted = tyre.next_compound
                    rng = self.tyre_streams.stream(f"tyres:{car_id}")
                    tyre.compound = fitted
                    tyre.condition = 1
                    tyre.change_threshold = float(rng.uniform(0.12, 0.24))
                    tyre.next_compound = sample_compound(rng, fitted)
                    tyre.service_duration_s = float(rng.uniform(2, 3))
                    tyre.requested = False
                    tyre.phase = "exit"
                    tyre.exit_after_progress_m = state.progress_m + 220
                    tyre.stops += 1
                    state.tyre_grip_multiplier = tyre.grip
                    self.events.append(
                        {
                            "kind": "pit_service_completed",
                            "car_id": car_id,
                            "compound": fitted.value,
                            "session_time_s": now,
                        }
                    )
            elif tyre.phase == "exit" and state.progress_m >= tyre.exit_after_progress_m:
                tyre.phase = "track"
                if tyre.compound not in tyre.used_compounds:
                    tyre.used_compounds.append(tyre.compound)
                self.events.append({"kind": "pit_exit", "car_id": car_id, "session_time_s": now})

            if (
                tyre.phase in {"entry", "service", "exit"}
                and state.s_m >= self._pit_lane_start_s
                and state.speed_mps > self.regulations.pit_lane_speed_limit_mps
            ):
                state.speed_mps = self.regulations.pit_lane_speed_limit_mps
                state.acceleration_mps2 = min(0, state.acceleration_mps2)

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
            if self.simulator.session_time_s >= self.next_decision_s - 1e-9:
                self.next_decision_s += 0.1
                actions = {
                    car: replace(
                        self._requested_action(observation),
                        issued_at_s=self.simulator.session_time_s,
                    )
                    for car, observation in self.observations().items()
                }
            h = min(h, self.next_decision_s - self.simulator.session_time_s)
            report = self.simulator.step(actions, h)
            self.steps += 1
            remaining -= h
            self._update_tyres(h)
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
            if self.tyres[a.car_id].phase != "track" or self.tyres[b.car_id].phase != "track":
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
        provisional_order = sorted(
            self.simulator.world.cars,
            key=lambda car_id: (
                0 if car_id in self.finishes else 1,
                self.finishes.get(car_id, -self.simulator.world.cars[car_id].progress_m),
            ),
        )
        positions = {car_id: index + 1 for index, car_id in enumerate(provisional_order)}
        winner_laps = self.settings.laps if self.status == "finished" else 0
        for car_id, observation in observations.items():
            channels = dict(observation.channels)
            completed_laps = min(
                self.settings.laps,
                max(0, math.floor(self.simulator.world.cars[car_id].progress_m / self.track.length)),
            )
            distance_compliant = self.regulations.distance_is_classified(completed_laps, winner_laps)
            compound_compliant = (
                len(self.tyres[car_id].used_compounds) >= self.regulations.required_dry_compounds
            )
            classified = self.status == "finished" and distance_compliant and compound_compliant
            position = positions[car_id]
            cars.append(
                {
                    "id": car_id,
                    "channels": channels,
                    "observed_at_s": observation.observed_at_s,
                    "active_profile": observation.context.get("active_profile"),
                    "energy_laps": [dict(lap) for lap in observation.context.get("energy_laps", ())],
                    "battery_window_j": [
                        self.bundle.car_configs[car_id].battery_energy_min_j.value,
                        self.bundle.car_configs[car_id].battery_energy_max_j.value,
                    ],
                    "quality": observation.quality.value,
                    "requested_profile": self.overrides[car_id].profile.value
                    if car_id in self.overrides
                    else "auto",
                    "finish_time_s": self.finishes.get(car_id),
                    "qualifying_position": int(car_id.rsplit("-", maxsplit=1)[-1]),
                    "storyline": self.storyline.beats[car_id].mode,
                    "tyres": self.tyres[car_id].payload(self._visual_lateral(car_id)),
                    "classified": classified,
                    "regulation_status": (
                        "classified"
                        if classified
                        else "running"
                        if self.status != "finished"
                        else "disqualified: two dry compounds not used"
                        if not compound_compliant
                        else "not classified: less than 90% distance"
                    ),
                    "points": self.regulations.points(position, 1, self.settings.laps)
                    if self.status == "finished" and classified
                    else 0,
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
            "version": "race-v2",
            "settings": self.settings.model_dump(),
            "time_s": self.simulator.session_time_s,
            "steps": self.steps,
            "status": self.status,
            "failure": self.failure,
            "cars": cars,
            "events": self.events,
            "boost_evaluation": self.storyline.confusion.payload(),
            "regulations": self.regulations.manifest(),
            "provenance": "simulated; uncalibrated cars and scaled circuit artwork",
        }

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(
            {
                "model_version": "race-physics-v4",
                "settings": self.settings.model_dump(),
                "drivers": self.drivers,
                "tyres": self.tyres,
                "tyre_streams": self.tyre_streams.capture(),
                "storyline": self.storyline.snapshot(),
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
            }
        )

    def restore(self, snapshot: dict[str, Any]) -> None:
        if (
            snapshot.get("model_version") != "race-physics-v4"
            or snapshot.get("settings") != self.settings.model_dump()
        ):
            raise ValueError("incompatible race model or settings in checkpoint")
        saved = copy.deepcopy(snapshot)
        self.simulator.restore(saved["world"])
        for key in (
            "drivers",
            "tyres",
            "next_decision_s",
            "overrides",
            "bms_profiles",
            "lanes",
            "finishes",
            "events",
            "steps",
            "failure",
            "status",
        ):
            setattr(self, key, saved[key])
        self.tyre_streams.restore(saved["tyre_streams"])
        self.storyline.restore(saved["storyline"])

    def manifest(self) -> dict[str, Any]:
        return {
            "type": "manifest",
            "model_version": "race-physics-v4",
            "environment_version": "race-control-v2",
            "drivers": {car: driver.traits.model_dump() for car, driver in self.drivers.items()},
            "tyres": {
                car: {
                    "compound": tyre.compound.value,
                    "condition": tyre.condition,
                    "change_threshold": tyre.change_threshold,
                    "next_compound": tyre.next_compound.value,
                }
                for car, tyre in self.tyres.items()
            },
            "storyline": {
                **self.settings.storyline.model_dump(),
                "boost_evaluation": self.storyline.confusion.payload(),
                "provenance": "seeded synthetic race narrative, not calibrated strategy data",
            },
            "weather": self.weather.manifest(),
            "initial_states": {
                car: state.model_dump(mode="json")
                for car, state in self.bundle.scenario.initial_states.items()
            },
            "sensor_config": self.bundle.scenario.observation.model_dump(mode="json"),
            "version": "race-v2",
            "settings": self.settings.model_dump(),
            "bundle_hash": self.bundle.bundle_hash,
            "source_revision": self.map["source_revision"],
            "geometry_hash": self.map["source_sha256"],
            "geometry_provenance": self.track.geometry_provenance,
            "cars": {car: config.model_dump(mode="json") for car, config in self.bundle.car_configs.items()},
            "energy_rules": {
                "reference": "FIA 2026 Section C Issue 20, C5.2.7-10",
                "scope": "base dry power curve and 8.5 MJ recharge; event overrides unavailable",
                "overtake_authorization": "unavailable; boost uses standard curve",
                "strategy": "synthetic observation-driven straight and passing deployment",
            },
            "regulations": self.regulations.manifest(),
            "integrator": "RK2 float64",
            "observation": "delayed simulated sensors; rival energy hidden",
        }
