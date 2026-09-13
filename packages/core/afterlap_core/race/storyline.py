from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, replace
from typing import Any

from afterlap_contracts import DeploymentProfile

from ..rng import StreamRegistry
from ..simulation.observation import Observation
from ..simulation.policies import DriverAction
from .settings import StorylineSettings


@dataclass(slots=True)
class StoryBeat:
    mode: str
    next_s: float
    until_s: float = 0
    count: int = 0


@dataclass(slots=True)
class BoostConfusion:
    true_positive: int = 0
    false_positive: int = 0
    true_negative: int = 0
    false_negative: int = 0

    def add(self, opportunity: bool, boost: bool) -> None:
        if opportunity and boost:
            self.true_positive += 1
        elif boost:
            self.false_positive += 1
        elif opportunity:
            self.false_negative += 1
        else:
            self.true_negative += 1

    def payload(self) -> dict[str, int | float | None]:
        values = asdict(self)
        total = sum(values.values())
        predicted = self.true_positive + self.false_positive
        relevant = self.true_positive + self.false_negative
        return {
            **values,
            "accuracy": None if total == 0 else (self.true_positive + self.true_negative) / total,
            "precision": None if predicted == 0 else self.true_positive / predicted,
            "recall": None if relevant == 0 else self.true_positive / relevant,
        }


class StorylineDirector:
    def __init__(self, seed: int, cars: tuple[str, ...], settings: StorylineSettings) -> None:
        self.settings = settings
        self.streams = StreamRegistry(seed, tuple(f"storyline:{car}" for car in cars))
        self.beats = {car: StoryBeat("natural", self._next(car, 0)) for car in cars}
        self.confusion = BoostConfusion()

    def _next(self, car_id: str, now: float) -> float:
        rng = self.streams.stream(f"storyline:{car_id}")
        return now + float(
            rng.uniform(self.settings.event_interval_min_s, self.settings.event_interval_max_s)
        )

    def _start(self, car_id: str, now: float) -> dict[str, Any]:
        beat = self.beats[car_id]
        rng = self.streams.stream(f"storyline:{car_id}")
        mode = str(rng.choice(("attack", "push", "coast", "surge"), p=(0.32, 0.28, 0.18, 0.22)))
        beat.mode = mode
        beat.count += 1
        beat.until_s = now + float(
            rng.uniform(self.settings.event_duration_min_s, self.settings.event_duration_max_s)
        )
        beat.next_s = self._next(car_id, beat.until_s)
        return {
            "kind": "storyline_started",
            "car_id": car_id,
            "mode": mode,
            "session_time_s": now,
        }

    @staticmethod
    def opportunity(observation: Observation) -> bool:
        return any(
            0 < float(rival["relative_progress_m"]) < 65 and float(rival["relative_speed_mps"]) < -0.2
            for rival in observation.rivals
        )

    def direct(
        self, car_id: str, observation: Observation, action: DriverAction
    ) -> tuple[DriverAction, dict[str, Any] | None]:
        now = observation.delivered_at_s
        beat = self.beats[car_id]
        event = None
        if self.settings.enabled and beat.mode == "natural" and now >= beat.next_s:
            event = self._start(car_id, now)
        elif beat.mode != "natural" and now >= beat.until_s:
            beat.mode = "natural"
        if beat.mode == "attack":
            action = replace(
                action,
                profile=DeploymentProfile.OVERTAKE,
                pace_scale=1,
                acceleration_ceiling_mps2=min(3.5, action.acceleration_ceiling_mps2 or 3.5),
                label="storyline_attack",
            )
        elif beat.mode == "push":
            action = replace(
                action,
                profile=DeploymentProfile.PUSH,
                acceleration_ceiling_mps2=min(2, action.acceleration_ceiling_mps2 or 2),
                label="storyline_push",
            )
        elif beat.mode == "surge":
            action = replace(
                action,
                pace_scale=min(1, action.pace_scale + 0.04),
                acceleration_ceiling_mps2=min(3, action.acceleration_ceiling_mps2 or 3),
                label="storyline_surge",
            )
        elif beat.mode == "coast":
            action = replace(
                action,
                profile=DeploymentProfile.HARVEST,
                acceleration_ceiling_mps2=min(-1, action.acceleration_ceiling_mps2 or 15),
                label="storyline_coast",
            )
        boost = action.profile in {DeploymentProfile.PUSH, DeploymentProfile.OVERTAKE}
        self.confusion.add(self.opportunity(observation), boost)
        return action, event

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(
            {
                "streams": self.streams.capture(),
                "beats": self.beats,
                "confusion": self.confusion,
            }
        )

    def restore(self, snapshot: dict[str, Any]) -> None:
        saved = copy.deepcopy(snapshot)
        self.streams.restore(saved["streams"])
        self.beats = saved["beats"]
        self.confusion = saved["confusion"]
