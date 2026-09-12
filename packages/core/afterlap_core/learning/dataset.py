"""Dataset collection from complete simulator episodes.

Two datasets are collected here and they have different shapes for a reason.

**Continuation returns** are per-cutoff regression targets: every step of a
complete episode contributes one ``(observation, discounted return)`` pair.
``value.collect_episodes`` already does this; the wrapper here exists so the
episode records travel with the split metadata a fit needs.

**Calibration samples** are per-event classification pairs: a forecast made at
a decision, and whether the forecast event then happened *in the episode that
actually unfolded*. This is the dataset that did not exist, and the two rules
that make it honest are:

* **the label comes from the same episode as the forecast.** Comparing a
  forecast against a differently seeded episode would measure the forecaster
  against a world it was not forecasting;
* **an unreached event is dropped, not labelled false.** A checkpoint the
  episode never got to is no evidence that a pass failed to happen, and
  labelling it negative would drag every forecast downward and look like
  systematic overconfidence.

Both collectors require ``planner_mode`` to be set appropriately and say so
rather than returning an empty set: calibration needs rollouts enabled, and an
empty dataset silently returned is indistinguishable from a scenario that
produced no events.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .calibration import CalibrationSample
from .config import EnvConfig
from .value import ContinuationSample, collect_episodes

__all__ = [
    "CalibrationCollection",
    "ContinuationCollection",
    "collect_calibration_samples",
    "collect_continuation_samples",
    "rollout_enabled_config",
]


@dataclass(frozen=True, slots=True)
class ContinuationCollection:
    """Continuation samples plus the episodes they came from."""

    samples: list[ContinuationSample]
    episodes: list[dict[str, object]]
    environment_version: str
    gamma: float
    policy_identity: str

    @property
    def complete_episode_count(self) -> int:
        return sum(1 for record in self.episodes if bool(record.get("complete")))

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample_count": len(self.samples),
            "episode_count": len(self.episodes),
            "complete_episode_count": self.complete_episode_count,
            "environment_version": self.environment_version,
            "gamma": self.gamma,
            "policy_identity": self.policy_identity,
            "episodes": self.episodes,
        }


@dataclass(frozen=True, slots=True)
class CalibrationCollection:
    """Forecast/realisation pairs plus what was dropped and why."""

    samples: list[CalibrationSample]
    episode_count: int
    forecast_count: int
    unreached_count: int
    environment_version: str
    policy_identity: str
    forecaster_version: str
    planner_deadline_s: float | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def event_definitions(self) -> tuple[str, ...]:
        return tuple(sorted({sample.event_definition for sample in self.samples}))

    def base_rates(self) -> dict[str, float | None]:
        """Observed positive rate per event. ``None`` when nothing was labelled."""
        rates: dict[str, float | None] = {}
        for event in self.event_definitions:
            rows = [s for s in self.samples if s.event_definition == event]
            rates[event] = (sum(s.outcome for s in rows) / len(rows)) if rows else None
        return rates

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample_count": len(self.samples),
            "episode_count": self.episode_count,
            "forecast_count": self.forecast_count,
            "unreached_count": self.unreached_count,
            "environment_version": self.environment_version,
            "policy_identity": self.policy_identity,
            "forecaster_version": self.forecaster_version,
            "planner_deadline_s": self.planner_deadline_s,
            "event_definitions": list(self.event_definitions),
            "base_rates": self.base_rates(),
            "dropped_note": (
                "an unreached checkpoint is dropped rather than labelled false; a line the "
                "episode never crossed is not evidence that the event failed to happen"
            ),
            "notes": list(self.notes),
        }


def rollout_enabled_config(config: EnvConfig, *, planner_deadline_s: float | None = None) -> EnvConfig:
    """The same environment with the planner's re-simulation turned on.

    This changes ``environment_version``, and deliberately so: transitions
    collected with rollouts on are not interchangeable with transitions
    collected without them, and the revision string is what stops the two being
    mixed by accident.

    ``planner_deadline_s`` exists because the operational 200 ms budget is
    routinely exceeded once re-simulation is on -- measured at 200 to 460 ms on
    the development machine -- and a deadline expiry withdraws the decision
    without publishing a forecast. Collecting a calibration set under the
    operational deadline would therefore keep only the decisions that happened
    to fit inside it, which is a biased sample of exactly the easy cases. The
    deadline actually used is recorded on the collection.
    """
    updates: dict[str, Any] = {}
    if config.planner_mode != "full":
        updates["planner_mode"] = "full"
    if planner_deadline_s is not None and planner_deadline_s != config.planner_deadline_s:
        updates["planner_deadline_s"] = float(planner_deadline_s)
    return config if not updates else dataclasses.replace(config, **updates)


def collect_continuation_samples(
    config: EnvConfig,
    *,
    policy: Any,
    policy_identity: str,
    episodes: int,
    gamma: float,
    seed: int = 0,
    scenario_id: str | None = None,
    max_steps: int | None = None,
) -> ContinuationCollection:
    """Roll out complete episodes and turn them into continuation samples.

    ``policy_identity`` is recorded because an ensemble fitted under one frozen
    controller is not a universal value function and must not be reused under
    another.
    """
    from .env import AfterlapEnv

    env = AfterlapEnv(config=config, scenario_id=scenario_id)
    try:
        samples, records = collect_episodes(
            env,
            policy=policy,
            episodes=episodes,
            gamma=gamma,
            seed=seed,
            max_steps=max_steps,
        )
    finally:
        env.close()
    return ContinuationCollection(
        samples=samples,
        episodes=records,
        environment_version=config.environment_version,
        gamma=gamma,
        policy_identity=policy_identity,
    )


def collect_calibration_samples(
    config: EnvConfig,
    *,
    policy: Any,
    policy_identity: str,
    episodes: int,
    seed: int = 0,
    scenario_id: str | None = None,
    max_steps: int | None = None,
) -> CalibrationCollection:
    """Pair every published forecast with what happened in the same episode.

    Requires ``planner_mode='full'``: without the re-simulation ensemble the
    planner publishes no probabilities and there is nothing to calibrate. Rather
    than returning an empty set, this raises, because an empty calibration set
    returned quietly is indistinguishable from a scenario that produced no
    events.
    """
    from ..planning.rollout import FORECASTER_VERSION
    from .env import AfterlapEnv

    if config.planner_mode != "full":
        raise ValueError(
            f"calibration needs planner_mode='full' so the rollout ensemble publishes "
            f"probabilities; this configuration is {config.planner_mode!r}. "
            "`rollout_enabled_config` returns a suitable copy."
        )
    if not callable(policy):
        raise TypeError("policy must be callable")

    samples: list[CalibrationSample] = []
    notes: list[str] = []
    forecast_count = 0
    unreached = 0
    completed_episodes = 0

    env = AfterlapEnv(config=config, scenario_id=scenario_id)
    try:
        for index in range(episodes):
            observation, reset_info = env.reset(seed=seed + index)
            episode_scenario = str(reset_info.get("scenario_id", "unknown"))
            episode_id = f"{episode_scenario}:{seed + index}"
            pending: list[dict[str, Any]] = []
            terminated = truncated = False
            steps = 0
            while not (terminated or truncated):
                action = policy(observation)
                observation, _reward, terminated, truncated, info = env.step(action)
                steps += 1
                planning = info.get("planning") if isinstance(info, dict) else None
                if isinstance(planning, dict):
                    for forecast in planning.get("forecasts") or ():
                        pending.append(dict(forecast))
                if max_steps is not None and steps >= max_steps:
                    break

            if not terminated:
                notes.append(
                    f"{episode_id}: the episode did not terminate, so its forecasts were dropped; "
                    "a truncated episode has no settled realisation"
                )
                continue
            completed_episodes += 1
            realisation = env.realisation
            for forecast in pending:
                forecast_count += 1
                checkpoint = forecast.get("checkpoint_id")
                event = str(forecast.get("event_definition", ""))
                raw = forecast.get("raw_frequency")
                if checkpoint is None or not event or raw is None:
                    unreached += 1
                    continue
                label = realisation.resolve(event, str(checkpoint))
                if label is None:
                    unreached += 1
                    continue
                value = float(raw)
                if not np.isfinite(value):
                    unreached += 1
                    continue
                samples.append(
                    CalibrationSample(
                        event_definition=event,
                        raw_frequency=float(np.clip(value, 0.0, 1.0)),
                        outcome=int(bool(label)),
                        episode_id=episode_id,
                        scenario_id=episode_scenario,
                        checkpoint_id=str(checkpoint),
                        sample_count=(
                            None if forecast.get("sample_count") is None else int(forecast["sample_count"])
                        ),
                    )
                )
    finally:
        env.close()

    if forecast_count == 0:
        notes.append(
            "no forecast was published across every episode; with rollouts enabled this means "
            "the planner withdrew at every decision rather than that the events never occurred"
        )
    return CalibrationCollection(
        samples=samples,
        episode_count=completed_episodes,
        forecast_count=forecast_count,
        unreached_count=unreached,
        environment_version=config.environment_version,
        policy_identity=policy_identity,
        forecaster_version=FORECASTER_VERSION,
        planner_deadline_s=config.planner_deadline_s,
        notes=tuple(dict.fromkeys(notes)),
    )
