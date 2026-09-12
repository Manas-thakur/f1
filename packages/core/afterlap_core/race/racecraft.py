from __future__ import annotations

from dataclasses import dataclass

from afterlap_contracts import DeploymentProfile

from ..simulation.observation import Observation
from ..simulation.policies import DriverAction
from ..simulation.track_source import TrackSource
from .variability import DriverTraits


@dataclass
class Racecraft:
    traits: DriverTraits
    lane: float
    goal: float | None = None
    state: str = "free"
    rival_id: str | None = None
    since_s: float = 0
    acceleration: float = 0
    profile: DeploymentProfile = DeploymentProfile.CONSERVE
    last_time_s: float = -0.1
    length_m: float = 5.6
    width_m: float = 2

    def transition(self, state: str, now: float) -> None:
        if self.state != state:
            self.state = state
            self.since_s = now

    def traffic(self, observation: Observation, length: float) -> list[dict[str, float | str]]:
        age = max(0.0, observation.delivered_at_s - observation.observed_at_s) + self.traits.reaction_s
        return [
            {
                **dict(rival),
                "relative_progress_m": (
                    (float(rival["relative_progress_m"]) + length / 2) % length
                    - length / 2
                    + float(rival["relative_speed_mps"]) * age
                ),
            }
            for rival in observation.rivals
        ]

    def clear(
        self, rivals: list[dict[str, float | str]], own_d: float, target: float, horizon: float
    ) -> bool:
        for rival in rivals:
            gap = float(rival["relative_progress_m"])
            future = gap + float(rival["relative_speed_mps"]) * horizon
            nearest = 0 if gap * future <= 0 else min(abs(gap), abs(future))
            low, high = sorted((own_d, target))
            lateral = float(rival["lateral_d_m"])
            if (
                nearest < self.length_m + self.traits.clearance_m
                and low - self.width_m - self.traits.clearance_m
                < lateral
                < high + self.width_m + self.traits.clearance_m
            ):
                return False
        return True

    def choose_lane(
        self, observation: Observation, track: TrackSource, rivals: list[dict[str, float | str]], dt: float
    ) -> None:
        speed = max(0, observation.get("speed_mps"))
        own_d = observation.get("lateral_d_m")
        progress = observation.get("progress_m")
        now = observation.delivered_at_s
        target = next((rival for rival in rivals if rival["car_id"] == self.rival_id), None)
        clearance = self.length_m + self.traits.clearance_m + speed * self.traits.reaction_s
        horizon = max(self.traits.commitment_s, 2 * self.width_m / self.traits.lateral_rate_mps)
        width = min(track.width_at(progress + speed * t) for t in (0, horizon / 2, horizon))
        limit = max(0, width / 2 - self.width_m / 2 - self.traits.clearance_m)
        desired = self.lane if self.goal is None else self.goal
        if target is not None and self.state in {"committed", "alongside"}:
            gap = float(target["relative_progress_m"])
            if gap < -clearance:
                self.transition("returning", now)
            elif abs(gap) <= self.length_m:
                self.transition("alongside", now)
            elif (
                (
                    now - self.since_s >= self.traits.commitment_s
                    and abs(own_d - desired) < 0.3
                    and float(target["relative_speed_mps"]) > 0.5
                )
                or abs(desired - float(target["lateral_d_m"])) < self.width_m + self.traits.clearance_m
                or not self.clear(
                    [rival for rival in rivals if rival["car_id"] != self.rival_id], own_d, desired, 0.7
                )
            ):
                self.transition("aborting", now)
        elif self.state in {"committed", "alongside"}:
            self.transition("aborting", now)
        if self.state in {"aborting", "returning"}:
            desired = own_d
            preferred = max(-limit, min(limit, self.traits.preferred_line_m))
            if self.clear(rivals, own_d, preferred, horizon):
                desired = preferred
                if abs(own_d - preferred) < 0.2:
                    self.rival_id = None
                    self.transition("recovering" if self.state == "aborting" else "free", now)
        elif self.state == "recovering":
            if now - self.since_s >= self.traits.reaction_s + 0.1:
                self.transition("free", now)
        elif self.state not in {"committed", "alongside"}:
            ahead = [
                rival for rival in rivals if 0 < float(rival["relative_progress_m"]) < max(30, speed * 2.5)
            ]
            target = min(ahead, key=lambda rival: float(rival["relative_progress_m"]), default=None)
            self.transition("closing" if target else "free", now)
            if target:
                gap = float(target["relative_progress_m"])
                closing = -float(target["relative_speed_mps"])
                self.transition("following", now)
                grip = float(observation.channels.get("grip_multiplier", 0.55))
                feasible = all(
                    speed * speed * abs(track.curvature_at(progress + speed * t)) < 0.7 * 9.80665 * grip
                    for t in (0, horizon / 2, horizon)
                )
                if closing > 0.3 and feasible and gap > self.length_m:
                    sides = [
                        float(target["lateral_d_m"]) + side * (self.width_m + self.traits.clearance_m + 0.3)
                        for side in (-1, 1)
                    ]
                    if (
                        abs(own_d - float(target["lateral_d_m"]))
                        > self.width_m + self.traits.clearance_m + 0.3
                    ):
                        sides.insert(0, own_d)
                    sides.sort(
                        key=lambda lane: abs(lane - own_d) + 0.2 * abs(lane - self.traits.preferred_line_m)
                    )
                    for lane in sides:
                        move_time = abs(lane - own_d) / self.traits.lateral_rate_mps + self.traits.reaction_s
                        if (
                            abs(lane) <= limit
                            and gap - closing * move_time > self.length_m + self.traits.clearance_m
                            and self.clear(rivals, own_d, lane, move_time)
                        ):
                            desired = lane
                            self.rival_id = str(target["car_id"])
                            self.transition("committed", now)
                            break
            else:
                desired = own_d
                pressured = any(
                    -self.length_m - speed * self.traits.headway_s < float(rival["relative_progress_m"]) < 0
                    for rival in rivals
                )
                if not pressured and self.clear(rivals, own_d, self.traits.preferred_line_m, horizon):
                    desired = self.traits.preferred_line_m
        self.goal = desired
        delta = self.traits.lateral_rate_mps * dt
        self.lane = max(-limit, min(limit, self.lane + max(-delta, min(delta, desired - self.lane))))

    def react(self, observation: Observation, track: TrackSource) -> DriverAction:
        now = observation.delivered_at_s
        dt = max(0.0, now - self.last_time_s)
        self.last_time_s = now
        if not all(observation.has(key) for key in ("speed_mps", "progress_m", "lateral_d_m")):
            return DriverAction(target_lateral_d_m=self.lane, acceleration_ceiling_mps2=0, label="unobserved")
        rivals = self.traffic(observation, track.length)
        self.choose_lane(observation, track, rivals, dt)
        speed = max(0, observation.get("speed_mps"))
        own_d = observation.get("lateral_d_m")
        desired_a = 4.0
        emergency = False
        for rival in rivals:
            gap = float(rival["relative_progress_m"])
            if gap <= 0 or abs(float(rival["lateral_d_m"]) - own_d) > self.width_m + self.traits.clearance_m:
                continue
            closing = -float(rival["relative_speed_mps"])
            net = max(0.2, gap - self.length_m - self.traits.clearance_m)
            headway = self.traits.headway_s
            error = net - speed * headway
            demand = (0.45 * error - 1.2 * closing) / (1 + headway)
            stop_a = closing * max(0, closing) / (2 * net)
            moving_clear = (
                self.state == "committed"
                and self.rival_id == rival["car_id"]
                and self.goal is not None
                and abs(self.goal - float(rival["lateral_d_m"])) > self.width_m + self.traits.clearance_m
                and net
                > max(0, closing)
                * (abs(self.goal - own_d) / self.traits.lateral_rate_mps + self.traits.reaction_s + 0.4)
            )
            desired_a = min(desired_a, 4 if moving_clear else demand, 4 - stop_a)
            emergency |= net < max(1, closing * (self.traits.reaction_s + 0.2))
        change = self.traits.jerk_mps3 * dt
        self.acceleration = max(
            -15,
            min(
                4,
                desired_a
                if emergency
                else max(self.acceleration - change, min(self.acceleration + change, desired_a)),
            ),
        )
        energy = observation.channels.get("battery_energy_j")
        if energy is not None and energy < self.traits.reserve_j:
            self.profile = DeploymentProfile.HARVEST
        elif self.profile != DeploymentProfile.HARVEST or (
            energy is not None and energy > self.traits.reserve_j + 200000
        ):
            self.profile = (
                DeploymentProfile.PUSH
                if self.state in {"committed", "alongside"}
                else DeploymentProfile.CONSERVE
            )
        return DriverAction(
            profile=self.profile,
            pace_scale=self.traits.pace,
            target_lateral_d_m=self.lane,
            acceleration_ceiling_mps2=self.acceleration,
            label=self.state,
        )
