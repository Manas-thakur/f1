"""The Gymnasium environment.

One policy step is exactly one second of simulated time and does, in order:

1. decode the raw SAC action into bounded soft preferences;
2. queue those preferences and either **solve** a new plan or **reuse** an
   eligible one already in force;
3. publish the head profile of the accepted plan as a driver instruction, which
   the simulator then subjects to the driver reaction delay before it takes
   effect;
4. integrate the physics to the next one-second tick;
5. re-observe, re-estimate, re-encode and score the transition.

Two timing rules are load-bearing and both are implemented literally.

**Safety invalidation between ticks does not trigger an off-cadence policy
call.** The simulator's own physical admissibility check downgrades a profile
mid-tick; the learned proposal is held until the next tick while that baseline
safety reacts immediately.

**Termination and truncation are different.** A finish or a physical abort is
``terminated``; the external episode-step limit is ``truncated`` and the final
observation is preserved so a bootstrap remains valid there. Zeroing the
potential on a truncation would tell the critic that running out of wall clock
is the same as retiring the car.

``info`` carries diagnostic identifiers and reward components. It never carries
privileged truth: :func:`AfterlapEnv.step` builds it from the decoded action,
the planning result and the reward decomposition, all of which are functions of
the delivered observation. The finish position appears once, in the terminal
``episode_outcome`` block, because a completed episode's outcome is a recorded
result rather than a mid-episode observation. ``tests/learning/test_env.py``
asserts the non-terminal invariant by truth mutation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from afterlap_contracts import (
    DeploymentProfile,
    PlanningStatus,
    ReasonCode,
    RewardManifest,
    RuleContext,
    StateEstimate,
)

from ..feature_manifest import OBSERVATION_SIZE, VALUE_COUNT
from ..planning import (
    ActivePlan,
    BudgetProposal,
    ContinuationModel,
    PlanningWorld,
    active_plan_from,
    plan as run_planner,
)
from ..rules import RulePack, load_rule_pack
from ..simulation import DriverAction, ScenarioBundle, Simulator
from .actions import ActionBounds, DecodedPreferences, action_space, compute_bounds, decode_action
from .bridge import BridgeTick, ObservationBridge
from .config import EnvConfig, ScenarioSpec, load_env_config
from .features import EncodedObservation, FeatureEncoder
from .reward import RewardTerms, assert_field_size_supported, load_reward_manifest, step_reward
from .sampler import resolve_bundle

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "AfterlapEnv",
    "EnvDiagnostics",
    "EpisodeOutcome",
    "make_env",
]

_MIN_PACE_SCALE = 0.70
_MAX_PACE_SCALE = 1.00


@dataclass(slots=True)
class EnvDiagnostics:
    """Counters the training callbacks aggregate. All controller-side."""

    solves: int = 0
    reuses: int = 0
    withdrawals: int = 0
    solver_timeouts: int = 0
    instruction_changes: int = 0
    learned_disabled_ticks: int = 0
    projection_distance_j: float = 0.0
    projection_samples: int = 0
    clip_events: int = 0
    missed_executions: int = 0
    instructions_issued: int = 0
    observed_executions: int = 0
    """Instructions whose profile was actually in force at the end of the tick."""

    def as_dict(self) -> dict[str, float | int]:
        mean_projection = (
            self.projection_distance_j / self.projection_samples if self.projection_samples else 0.0
        )
        return {
            "solves": self.solves,
            "reuses": self.reuses,
            "withdrawals": self.withdrawals,
            "solver_timeouts": self.solver_timeouts,
            "instruction_changes": self.instruction_changes,
            "learned_disabled_ticks": self.learned_disabled_ticks,
            "mean_projection_distance_j": mean_projection,
            "clip_events": self.clip_events,
            "missed_executions": self.missed_executions,
            "instructions_issued": self.instructions_issued,
            "observed_executions": self.observed_executions,
        }


@dataclass(frozen=True, slots=True)
class EpisodeOutcome:
    """Physical outcomes, recorded separately from the dimensionless utility."""

    finished: bool
    failed: bool
    truncated: bool
    finish_position: int | None
    elapsed_time_s: float
    distance_travelled_m: float
    final_energy_j: float
    instruction_changes: int
    withdrawn_decisions: int
    steps: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "finished": self.finished,
            "failed": self.failed,
            "truncated": self.truncated,
            "finish_position": self.finish_position,
            "elapsed_time_s": self.elapsed_time_s,
            "distance_travelled_m": self.distance_travelled_m,
            "final_energy_j": self.final_energy_j,
            "instruction_changes": self.instruction_changes,
            "withdrawn_decisions": self.withdrawn_decisions,
            "steps": self.steps,
        }


class AfterlapEnv(gym.Env[np.ndarray, np.ndarray]):
    """Single-agent energy-strategy environment over the AFTERLAP simulator."""

    metadata: dict[str, Any] = {"render_modes": []}  # noqa: RUF012 - gymnasium.Env declares this as an instance variable

    def __init__(
        self,
        *,
        config: EnvConfig | None = None,
        scenario_id: str | None = None,
        reward_manifest: RewardManifest | None = None,
        continuation_model: ContinuationModel | None = None,
        session_id: str = "learning",
    ) -> None:
        super().__init__()
        self._config = config or load_env_config()
        self._scenario_ids = (
            (scenario_id,)
            if scenario_id is not None
            else tuple(s.scenario_id for s in self._config.scenarios)
        )
        for identifier in self._scenario_ids:
            self._config.scenario(identifier)
        self._reward = reward_manifest or load_reward_manifest(self._config.objective_id)
        if not math.isclose(self._reward.gamma, self._reward.gamma):  # pragma: no cover
            raise ValueError("reward gamma is not finite")
        self._continuation = continuation_model
        self._session_id = session_id

        self.observation_space = spaces.Box(
            low=np.concatenate([np.full(VALUE_COUNT, -5.0), np.zeros(VALUE_COUNT)]).astype(np.float32),
            high=np.concatenate([np.full(VALUE_COUNT, 5.0), np.ones(VALUE_COUNT)]).astype(np.float32),
            shape=(OBSERVATION_SIZE,),
            dtype=np.float32,
        )
        self.action_space = action_space()

        self._encoder = FeatureEncoder()
        self._simulator: Simulator | None = None
        self._bundle: ScenarioBundle | None = None
        self._spec: ScenarioSpec | None = None
        self._bridge: ObservationBridge | None = None
        self._planning_world: PlanningWorld | None = None
        self._pack: RulePack | None = None
        self._np_random_seed_used: int | None = None

        self._tick: BridgeTick | None = None
        self._encoded: EncodedObservation | None = None
        self._active_plan: ActivePlan | None = None
        self._last_profile: DeploymentProfile | None = None
        self._last_budget_j: float | None = None
        self._steps = 0
        self._start_progress_m = 0.0
        self._start_time_s = 0.0
        self._instruction_changes_total = 0
        self._withdrawn_total = 0
        self._diagnostics = EnvDiagnostics()
        self._closed = False

    @property
    def environment_version(self) -> str:
        return self._config.environment_version

    @property
    def feature_hash(self) -> str:
        return self._encoder.feature_hash

    @property
    def reward_revision(self) -> str:
        return self._reward.revision

    @property
    def diagnostics(self) -> EnvDiagnostics:
        return self._diagnostics

    @property
    def encoder(self) -> FeatureEncoder:
        return self._encoder

    def reset(
        self, *, seed: int | None = None, options: Mapping[str, Any] | None = None
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Reset every random generator and rebuild the episode from scratch.

        ``options`` may name a ``scenario_id`` inside the configured set and a
        ``scenario_seed``. Nothing else is accepted: an unrecognised option would
        silently change what an experiment manifest describes.
        """
        super().reset(seed=seed)
        chosen = dict(options or {})
        unknown = set(chosen) - {"scenario_id", "scenario_seed"}
        if unknown:
            raise ValueError(f"unrecognised reset options {sorted(unknown)}")

        scenario_id = chosen.get("scenario_id")
        if scenario_id is None:
            index = int(self.np_random.integers(0, len(self._scenario_ids)))
            scenario_id = self._scenario_ids[index]
        elif scenario_id not in self._scenario_ids:
            raise ValueError(f"scenario {scenario_id!r} is not part of this environment instance")

        spec = self._config.scenario(str(scenario_id))
        scenario_seed = chosen.get("scenario_seed")
        if scenario_seed is None:
            index = int(self.np_random.integers(0, len(spec.seeds)))
            scenario_seed = spec.seeds[index]
        scenario_seed = int(scenario_seed)
        self._np_random_seed_used = scenario_seed

        bundle = resolve_bundle(spec.scenario_id, seed=scenario_seed)
        assert_field_size_supported(self._reward, len(bundle.scenario.car_ids))
        simulator = Simulator()
        simulator.reset(bundle, seed=scenario_seed)

        self._bundle = bundle
        self._spec = spec
        self._simulator = simulator
        self._pack = load_rule_pack(spec.rule_pack)
        self._bridge = ObservationBridge(
            bundle=bundle,
            pack=self._pack,
            session_id=f"{self._session_id}:{spec.scenario_id}:{scenario_seed}",
            seed=scenario_seed,
            remaining_distance_m=spec.race_distance_m,
        )
        if self._config.planner_mode != "disabled":
            rivals = bundle.scenario.rival_ids
            self._planning_world = PlanningWorld(
                bundle=bundle,
                ego_car_id=bundle.scenario.ego_car_id,
                rival_car_id=rivals[0] if rivals else None,
                seed=scenario_seed,
            )
        else:
            self._planning_world = None

        ego = bundle.scenario.ego_car_id
        self._start_progress_m = float(bundle.scenario.initial_states[ego].progress_m.value)
        self._start_time_s = simulator.session_time_s
        self._active_plan = None
        self._last_profile = None
        self._last_budget_j = None
        self._steps = 0
        self._instruction_changes_total = 0
        self._withdrawn_total = 0
        self._diagnostics = EnvDiagnostics()

        settle_s = max(self._config.physics_step_s, float(bundle.scenario.observation.delay_s.value))
        warmup_s = self._warm_up(settle_s)

        self._start_progress_m = float(simulator.world.cars[ego].progress_m)
        self._start_time_s = simulator.session_time_s
        self._bridge.start_progress_m = self._start_progress_m

        tick = self._observe()
        encoded = self._encoder.encode(tick.estimate, tick.feature_context)
        self._tick = tick
        self._encoded = encoded

        info: dict[str, Any] = {
            "scenario_id": spec.scenario_id,
            "scenario_family": spec.family,
            "scenario_seed": scenario_seed,
            "environment_version": self.environment_version,
            "feature_hash": self._encoder.feature_hash,
            "reward_revision": self._reward.revision,
            "observation_diagnostics": encoded.diagnostics(),
            "warmup_s": warmup_s,
            "start_progress_m": self._start_progress_m,
            "eligibility": tick.eligibility.value,
        }
        return encoded.observation, info

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if self._simulator is None or self._tick is None or self._encoded is None:
            raise RuntimeError("step() called before reset()")
        assert self._bridge is not None
        assert self._spec is not None
        assert self._bundle is not None

        tick = self._tick
        raw_action = np.asarray(action, dtype=np.float32).reshape(-1)

        bounds = compute_bounds(
            tick.estimate,
            tick.rule_context.applicable_limits if tick.rule_context is not None else None,
            window_s=self._config.preference_window_s,
            checkpoint_interval_s=self._config.checkpoint_interval_s,
        )
        decoded = decode_action(raw_action, bounds)
        if not decoded.learned_enabled:
            self._diagnostics.learned_disabled_ticks += 1
        self._bridge.record_decoded_preferences(decoded.budget_j, decoded.reserve_target_j)

        planning = self._plan_or_reuse(tick, decoded)

        driver_action, instruction_changed = self._driver_action(planning, decoded, tick)
        if instruction_changed:
            self._instruction_changes_total += 1
            self._diagnostics.instruction_changes += 1
            self._bridge.record_instruction_change(self._simulator.session_time_s)

        previous_remaining = self._remaining_reference_time_s(tick.estimate)
        elapsed_s, report = self._integrate(
            self._config.policy_interval_s,
            {self._bundle.scenario.ego_car_id: driver_action} if driver_action is not None else None,
        )
        if driver_action is not None:
            self._diagnostics.instructions_issued += 1
            if (
                self._simulator.world.cars[self._bundle.scenario.ego_car_id].active_profile
                is driver_action.profile
            ):
                self._diagnostics.observed_executions += 1
        if report is not None and report.profile_downgrades:
            self._diagnostics.missed_executions += 1
            self._bridge.record_missed_execution(self._simulator.session_time_s)

        next_tick = self._observe()
        next_encoded = self._encoder.encode(next_tick.estimate, next_tick.feature_context)
        self._diagnostics.clip_events += next_encoded.clip_count

        self._steps += 1
        finished, failed = self._terminal_state(report)
        truncated = (not finished and not failed) and self._steps >= self._config.max_episode_steps
        terminated = finished or failed

        finish_position = self._position() if finished else None
        terms = step_reward(
            self._reward,
            elapsed_s=elapsed_s,
            instruction_changes=1 if instruction_changed else 0,
            remaining_reference_time_s=previous_remaining,
            next_remaining_reference_time_s=self._remaining_reference_time_s(next_tick.estimate),
            terminated=terminated,
            truncated=truncated,
            finished=finished,
            finish_position=finish_position,
            failed=failed,
        )

        self._tick = next_tick
        self._encoded = next_encoded

        info = self._build_info(
            decoded, planning, terms, next_encoded, terminated=terminated, truncated=truncated
        )
        return next_encoded.observation, float(terms.total), terminated, truncated, info

    def close(self) -> None:
        self._closed = True
        self._simulator = None
        self._planning_world = None

    def _warm_up(self, settle_s: float) -> float:
        """Integrate to the declared episode starting state.

        The shipped rule pack resolves an overtake permission only at a
        detection line, and the independent checker returns ``unknown`` — never
        acceptance — until it has. A scenario whose ego starts well before that
        line would spend most of its episode with every candidate rejected, so
        the environment first integrates forward to the scenario's declared
        starting progress under a conserving warm-up profile.

        This is part of the *scenario starting state*: it is identical for every
        controller, it is reported in the reset info, and it is not a learned
        decision. Nothing is scored during it.
        """
        assert self._simulator is not None
        assert self._spec is not None
        assert self._bundle is not None
        ego = self._bundle.scenario.ego_car_id
        target = self._spec.warmup_to_progress_m
        action = DriverAction(
            profile=DeploymentProfile(self._config.warmup_profile),
            pace_scale=_MAX_PACE_SCALE,
            issued_at_s=self._simulator.session_time_s,
            label="warmup",
        )

        elapsed = 0.0
        self._simulator.step({ego: action}, settle_s)
        elapsed += settle_s
        self._observe()
        if target is None:
            return elapsed

        step_s = self._config.physics_step_s
        since_observation = 0.0
        while self._simulator.world.cars[ego].progress_m < target:
            if elapsed >= self._config.warmup_limit_s:
                raise RuntimeError(
                    f"scenario {self._spec.scenario_id!r} did not reach its declared warm-up "
                    f"progress {target} m within {self._config.warmup_limit_s} s; the declared "
                    "starting state is unreachable and the episode is not run"
                )
            self._simulator.step(None, step_s)
            elapsed += step_s
            since_observation += step_s
            if since_observation + 1e-12 >= self._config.policy_interval_s:
                since_observation = 0.0
                self._observe()
        self._observe()
        return elapsed

    def _observe(self) -> BridgeTick:
        assert self._simulator is not None
        assert self._bridge is not None
        assert self._bundle is not None
        ego = self._bundle.scenario.ego_car_id
        observation = self._simulator.observe(car_id=ego)[ego]
        return self._bridge.observe(observation)

    def _integrate(self, duration_s: float, actions: dict[str, DriverAction] | None) -> tuple[float, Any]:
        """Advance the simulator in physics sub-steps, returning actual elapsed time.

        The instruction is queued once, at the head of the interval. Sub-steps do
        not re-queue it: a driver does not receive a new call every 50 ms.
        """
        assert self._simulator is not None
        remaining = duration_s
        elapsed = 0.0
        report = None
        first = True
        while remaining > 1e-12:
            step_s = min(self._config.physics_step_s, remaining)
            if self._finished_now():
                break
            report = self._simulator.step(actions if first else None, step_s)
            first = False
            elapsed += step_s
            remaining -= step_s
            if self._finished_now():
                break
        return elapsed, report

    def _finished_now(self) -> bool:
        if self._simulator is None or self._spec is None or self._bundle is None:
            return False
        ego = self._bundle.scenario.ego_car_id
        travelled = self._simulator.world.cars[ego].progress_m - self._start_progress_m
        return travelled >= self._spec.race_distance_m

    def _terminal_state(self, report: Any) -> tuple[bool, bool]:
        """``(finished, failed)`` for the state the simulator is now in.

        A finish is the ego car completing the declared segment distance. A
        failure is a *physical invalidity abort with evidence*: the simulator
        recorded a state its reduced model cannot support. A software error or a
        missing mandatory source is not a policy DNF; it raises and the episode
        is excluded from learning transitions by the caller.
        """
        finished = self._finished_now()
        failed = False
        if report is not None and getattr(report, "envelope_exceedances", None):
            failed = True
            finished = False
        return finished, failed

    def _position(self) -> int:
        assert self._simulator is not None
        assert self._bundle is not None
        ego = self._bundle.scenario.ego_car_id
        ego_progress = self._simulator.world.cars[ego].progress_m
        return 1 + sum(
            1
            for car_id, state in self._simulator.world.cars.items()
            if car_id != ego and state.progress_m > ego_progress
        )

    def _remaining_reference_time_s(self, estimate: StateEstimate) -> float | None:
        """Reference remaining time from a fixed pace model and observed progress.

        This is not future race truth and it is not a prediction of the actual
        finish time. It is a declared pace applied to the belief's own remaining
        distance, which is what makes ``Phi`` a function of the observed state.
        """
        assert self._spec is not None
        remaining = estimate.race_context.remaining_distance_m.value
        if remaining is None:
            return None
        return max(0.0, float(remaining)) / self._spec.reference_pace_mps

    def _plan_or_reuse(self, tick: BridgeTick, decoded: DecodedPreferences) -> dict[str, Any]:
        """Solve a new plan, or keep the eligible one already in force."""
        assert self._simulator is not None
        assert self._spec is not None
        now_s = self._simulator.session_time_s

        if self._config.planner_mode == "disabled" or tick.rule_context is None:
            return {
                "status": None,
                "reused": False,
                "selected_plan_id": None,
                "head_profile": None,
                "projected_budget_j": None,
                "learned_enabled": False,
                "reason_codes": (),
                "detail": (
                    "planner disabled by configuration"
                    if self._config.planner_mode == "disabled"
                    else "no resolved rule context at this tick"
                ),
            }

        if self._can_reuse(now_s, decoded):
            self._diagnostics.reuses += 1
            assert self._active_plan is not None
            return {
                "status": PlanningStatus.OK.value,
                "reused": True,
                "selected_plan_id": self._active_plan.plan_id,
                "head_profile": self._active_plan.head_profile.value,
                "projected_budget_j": self._last_budget_j,
                "learned_enabled": decoded.learned_enabled,
                "reason_codes": (),
                "detail": "the instruction in force is still eligible",
            }

        proposal = self._proposal(decoded)
        result = run_planner(
            tick.estimate,
            tick.rule_context,
            self._continuation,
            self._config.planner_deadline_s,
            world=self._planning_world,
            current_plan=self._active_plan,
            proposal=proposal,
            terminal_target_energy_j=decoded.reserve_target_j,
            admissible=tick.rule_context.admissible_profiles or None,
            now_s=now_s,
            seed=self._np_random_seed_used or 0,
            rollout_enabled=self._config.planner_mode == "full",
        )
        self._diagnostics.solves += 1

        if result.status is PlanningStatus.DEADLINE_EXCEEDED:
            self._diagnostics.solver_timeouts += 1
        if result.status is not PlanningStatus.OK or result.selected_plan_id is None:
            self._withdrawn_total += 1
            self._diagnostics.withdrawals += 1
            self._active_plan = None
            return {
                "status": result.status.value,
                "reused": False,
                "selected_plan_id": None,
                "head_profile": None,
                "projected_budget_j": None,
                "learned_enabled": False,
                "reason_codes": tuple(code.value for code in result.reason_codes),
                "detail": result.detail,
            }

        chosen = next(c for c in result.accepted if c.id == result.selected_plan_id)
        head = chosen.profile_segments[0]
        projected = float(head.requested_budget_j)
        if decoded.budget_j is not None:
            self._diagnostics.projection_distance_j += abs(projected - decoded.budget_j)
            self._diagnostics.projection_samples += 1
        self._last_budget_j = projected
        self._active_plan = active_plan_from(
            result,
            tick.rule_context,
            selected_at_s=now_s,
            validity_s=self._config.plan_validity_s,
        )
        learned = any(
            code is ReasonCode.LEARNED_MODEL_DISABLED or code is ReasonCode.LEARNED_MODEL_OUT_OF_SUPPORT
            for code in chosen.reason_codes
        )
        return {
            "status": result.status.value,
            "reused": False,
            "selected_plan_id": chosen.id,
            "head_profile": head.profile_id.value,
            "projected_budget_j": projected,
            "learned_enabled": decoded.learned_enabled and not learned,
            "reason_codes": tuple(code.value for code in chosen.reason_codes),
            "detail": result.detail,
        }

    def _can_reuse(self, now_s: float, decoded: DecodedPreferences) -> bool:
        if self._active_plan is None:
            return False
        if now_s >= self._active_plan.expires_at_s:
            return False
        if decoded.budget_j is None or self._last_budget_j is None:
            return False
        return abs(decoded.budget_j - self._last_budget_j) <= self._config.replan_energy_tolerance_j

    def _proposal(self, decoded: DecodedPreferences) -> BudgetProposal | None:
        """Turn a decoded preference into a warm-start proposal.

        A proposal moves only the solver's starting point. The feasible set, the
        independent checker and the baseline candidates are untouched, so a
        preference cannot buy an illegal plan.
        """
        if decoded.budget_j is None:
            return None
        return BudgetProposal(
            deploy_j=(float(decoded.budget_j),),
            harvest_j=(0.0,),
            source="learned-actor/energy-v1",
        )

    def _driver_action(
        self, planning: Mapping[str, Any], decoded: DecodedPreferences, tick: BridgeTick
    ) -> tuple[DriverAction | None, bool]:
        """Publish the accepted plan's head profile as one driver instruction."""
        assert self._simulator is not None
        head = planning.get("head_profile")
        if head is None:
            return None, False
        profile = DeploymentProfile(str(head))
        admissible = tick.rule_context.admissible_profiles if tick.rule_context is not None else ()
        if admissible and profile not in admissible:  # pragma: no cover - checker already refused
            return None, False
        changed = self._last_profile is None or profile is not self._last_profile
        self._last_profile = profile
        action = DriverAction(
            profile=profile,
            pace_scale=_MAX_PACE_SCALE,
            issued_at_s=self._simulator.session_time_s,
            label=f"learned:{planning.get('selected_plan_id')}",
        )
        del decoded
        return action, changed

    def _build_info(
        self,
        decoded: DecodedPreferences,
        planning: Mapping[str, Any],
        terms: RewardTerms,
        encoded: EncodedObservation,
        *,
        terminated: bool,
        truncated: bool,
    ) -> dict[str, Any]:
        info: dict[str, Any] = {
            "reward_terms": terms.as_dict(),
            "action": decoded.as_dict(),
            "planning": dict(planning),
            "observation_diagnostics": encoded.diagnostics(),
            "diagnostics": self._diagnostics.as_dict(),
            "environment_version": self.environment_version,
        }
        if terminated or truncated:
            info["episode_outcome"] = self._episode_outcome(terms, truncated=truncated).as_dict()
        return info

    def _episode_outcome(self, terms: RewardTerms, *, truncated: bool) -> EpisodeOutcome:
        assert self._simulator is not None
        assert self._bundle is not None
        ego = self._bundle.scenario.ego_car_id
        state = self._simulator.world.cars[ego]
        return EpisodeOutcome(
            finished=terms.finish_position is not None,
            failed=terms.terminal_failure < 0.0,
            truncated=truncated,
            finish_position=terms.finish_position,
            elapsed_time_s=self._simulator.session_time_s - self._start_time_s,
            distance_travelled_m=state.progress_m - self._start_progress_m,
            final_energy_j=self._simulator.world.ledgers[ego].energy_j,
            instruction_changes=self._instruction_changes_total,
            withdrawn_decisions=self._withdrawn_total,
            steps=self._steps,
        )

    @property
    def action_bounds(self) -> ActionBounds | None:
        if self._tick is None:
            return None
        return compute_bounds(
            self._tick.estimate,
            self._tick.rule_context.applicable_limits if self._tick.rule_context is not None else None,
            window_s=self._config.preference_window_s,
            checkpoint_interval_s=self._config.checkpoint_interval_s,
        )

    @property
    def simulator(self) -> Simulator:
        """The simulator, for tests that deliberately mutate hidden truth."""
        if self._simulator is None:
            raise RuntimeError("the environment has not been reset")
        return self._simulator

    @property
    def rule_context(self) -> RuleContext | None:
        return None if self._tick is None else self._tick.rule_context

    @property
    def encoded(self) -> EncodedObservation | None:
        return self._encoded

    @property
    def opponent_family(self) -> str:
        """The scenario's declared opponent policy kinds, as a reporting group.

        Configuration, not truth: the policies are named in the scenario
        document, which an experiment manifest already records.
        """
        if self._bundle is None:
            return "unknown"
        kinds = sorted({spec.kind for spec in self._bundle.scenario.opponent_policies.values()})
        return "+".join(kinds) if kinds else "none"

    @property
    def tick(self) -> BridgeTick | None:
        """The controller-visible inputs of the current tick.

        Public so an isolation test can re-encode from exactly the belief and
        context the environment used, without reaching into private state.
        """
        return self._tick


def make_env(
    scenario_id: str | None = None,
    *,
    config: EnvConfig | None = None,
    seed: int | None = None,
    continuation_model: ContinuationModel | None = None,
    session_id: str = "learning",
) -> AfterlapEnv:
    """Construct one environment. Vectorised training wraps this."""
    env = AfterlapEnv(
        config=config,
        scenario_id=scenario_id,
        continuation_model=continuation_model,
        session_id=session_id,
    )
    if seed is not None:
        env.reset(seed=seed)
    return env
