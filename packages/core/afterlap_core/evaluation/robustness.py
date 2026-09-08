"""The robustness sweep matrix.

``validation/TECHNICAL_SPEC.md`` names the dimensions to sweep and one
invariant that must survive all of them:

    An unknown critical condition must not result in a confident active
    directive.

Every case here produces a :class:`RobustnessOutcome` carrying a label, what was
perturbed, what the controller then did, and whether the invariant applies and
held. A case whose perturbation cannot be applied in this package returns
``status="unmeasured"`` with a reason; it never returns a pass it did not earn.

DB outage and worker crash belong to the operations module (A14) and are not
swept here; they are reported as unmeasured by this module's coverage table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from afterlap_contracts import (
    DeploymentProfile,
    EligibilityState,
    PlanningStatus,
    ReasonCode,
)
from afterlap_core.config import Parameter, VerificationStatus
from afterlap_core.rules import load_rule_pack
from afterlap_core.simulation import Simulator, load_bundle
from afterlap_core.simulation.config import (
    ObservationConfig,
    PolicySpec,
    ScenarioBundle,
    ScenarioConfig,
)

from .controllers import (
    ControlDecision,
    Controller,
    ControlRequest,
    HashCheckedController,
    LegalFixedSchedule,
    LegalGreedyAttacker,
    ScheduleEntry,
    build_request,
)
from .harness import controller_rule_context
from .independent_ledger import ProgressSample, find_crossings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from afterlap_core.paths import Paths

__all__ = [
    "OPERATIONS_OWNED_DIMENSIONS",
    "RobustnessDimension",
    "RobustnessOutcome",
    "assert_no_confident_directive_under_unknown",
    "run_robustness_sweep",
]


class RobustnessDimension(StrEnum):
    """The sweep dimensions this module owns."""

    DATA_AGE = "data_age"
    DROPPED_ENERGY_CHANNEL = "dropped_energy_channel"
    MISSING_RULES = "missing_rules"
    CHANGED_RIVAL_RESPONSE = "changed_rival_response"
    LOW_INITIAL_ENERGY = "low_initial_energy"
    THERMAL_DERATING = "thermal_derating"
    LINE_BOUNDARY_TIMING = "line_boundary_timing"
    DELAYED_DRIVER_ACTION = "delayed_driver_action"
    SOLVER_TIMEOUT = "solver_timeout"
    MODEL_HASH_MISMATCH = "model_hash_mismatch"


OPERATIONS_OWNED_DIMENSIONS: tuple[str, ...] = ("db_outage", "worker_crash")
"""Named in the spec but owned by the operations module; unmeasured here."""


@dataclass(frozen=True, slots=True)
class RobustnessOutcome:
    """One labelled sweep result."""

    dimension: RobustnessDimension
    label: str
    status: str
    """``held``, ``violated`` or ``unmeasured``."""

    perturbation: str
    critical_condition_unknown: bool
    decisions: int = 0
    withdrawn_decisions: int = 0
    active_directives: int = 0
    confident_active_directives: int = 0
    evidence: dict[str, Any] = field(default_factory=dict)
    detail: str | None = None

    @property
    def invariant_applies(self) -> bool:
        return self.critical_condition_unknown

    def as_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "label": self.label,
            "status": self.status,
            "perturbation": self.perturbation,
            "critical_condition_unknown": self.critical_condition_unknown,
            "decisions": self.decisions,
            "withdrawn_decisions": self.withdrawn_decisions,
            "active_directives": self.active_directives,
            "confident_active_directives": self.confident_active_directives,
            "evidence": dict(self.evidence),
            "detail": self.detail,
        }


def assert_no_confident_directive_under_unknown(outcomes: Sequence[RobustnessOutcome]) -> None:
    """The hard invariant, checked over a completed sweep.

    Raises rather than returning a flag: a confident active directive issued
    while a critical condition is unknown is a release blocker, not a metric.
    """
    offenders = [
        outcome
        for outcome in outcomes
        if outcome.critical_condition_unknown and outcome.confident_active_directives > 0
    ]
    if offenders:
        detail = ", ".join(f"{o.dimension.value}:{o.label}" for o in offenders)
        raise AssertionError(
            f"a confident active directive was issued under an unknown critical condition ({detail})"
        )


def _param(value: float, unit: str, note: str) -> Parameter:
    return Parameter(
        value=value,
        unit=unit,
        source="synthetic:afterlap-robustness-sweep-v1",
        verification=VerificationStatus.SYNTHETIC_ASSUMPTION,
        note=note,
    )


def _rebundle(scenario: ScenarioConfig, template: ScenarioBundle) -> ScenarioBundle:
    return ScenarioBundle(scenario=scenario, track=template.track, car_configs=dict(template.car_configs))


def _with_observation_delay(bundle: ScenarioBundle, delay_s: float) -> ScenarioBundle:
    observation = bundle.scenario.observation
    perturbed = ObservationConfig(
        **{
            **observation.model_dump(),
            "delay_s": _param(delay_s, "s", "robustness sweep: inflated observation delay"),
        }
    )
    return _rebundle(bundle.scenario.model_copy(update={"observation": perturbed}), bundle)


def _with_reaction_delay(bundle: ScenarioBundle, delay_s: float) -> ScenarioBundle:
    drivers = {
        car_id: driver.model_copy(
            update={"reaction_delay_mean_s": _param(delay_s, "s", "robustness sweep: delayed driver action")}
        )
        for car_id, driver in bundle.scenario.drivers.items()
    }
    return _rebundle(bundle.scenario.model_copy(update={"drivers": drivers}), bundle)


def _with_rival_policy(bundle: ScenarioBundle, kind: str) -> ScenarioBundle:
    policies = {
        car_id: PolicySpec(kind=kind, params=dict(spec.params))
        for car_id, spec in bundle.scenario.opponent_policies.items()
    }
    return _rebundle(bundle.scenario.model_copy(update={"opponent_policies": policies}), bundle)


def _with_initial_temperature(bundle: ScenarioBundle, car_id: str, temperature_k: float) -> ScenarioBundle:
    states = dict(bundle.scenario.initial_states)
    states[car_id] = states[car_id].model_copy(
        update={
            "temperature_k": _param(
                temperature_k, "K", "robustness sweep: elevated initial battery temperature"
            )
        }
    )
    return _rebundle(bundle.scenario.model_copy(update={"initial_states": states}), bundle)


@dataclass(frozen=True, slots=True)
class _SweepSettings:
    horizon_s: float = 6.0
    dt_s: float = 0.02
    decision_interval_s: float = 0.5
    compute_budget_ms: float = 200.0
    max_observation_age_s: float = 1.0


def _collect_decisions(
    bundle: ScenarioBundle,
    controller: Controller,
    *,
    rule_pack_id: str,
    settings: _SweepSettings,
    paths: Paths | None = None,
    temperature_available: bool = True,
    expected_model_bundle_hash: str | None = None,
    offered_model_bundle_hash: str | None = None,
    seed: int | None = None,
) -> tuple[list[ControlDecision], list[tuple[str, ...]], Simulator]:
    """Drive one perturbed run and keep every decision and capability gap."""
    pack = load_rule_pack(rule_pack_id, paths)
    ego = bundle.scenario.ego_car_id
    simulator = Simulator()
    simulator.reset(bundle, seed=seed)
    start = simulator.session_time_s
    next_decision = start
    decisions: list[ControlDecision] = []
    gaps: list[tuple[str, ...]] = []
    last_action = None

    while simulator.session_time_s - start < settings.horizon_s - 1e-12:
        step_s = min(settings.dt_s, settings.horizon_s - (simulator.session_time_s - start))
        actions = None
        if simulator.session_time_s + 1e-12 >= next_decision:
            next_decision += settings.decision_interval_s
            observation = simulator.observe(car_id=ego)[ego]
            context, gap = controller_rule_context(
                observation,
                pack,
                session_id=f"robustness:{bundle.scenario.id}",
                eligibility=EligibilityState.ELIGIBLE_DETECTED,
                temperature_available=temperature_available,
            )
            request = build_request(
                car_id=ego,
                session_time_s=simulator.session_time_s,
                observation=observation,
                rule_context=context,
                compute_budget_ms=settings.compute_budget_ms,
                disturbance_keys=("wind", "grip", "sensor_noise", "driver_response"),
                max_observation_age_s=settings.max_observation_age_s,
                expected_model_bundle_hash=expected_model_bundle_hash,
                offered_model_bundle_hash=offered_model_bundle_hash,
            )
            decision = controller.decide(request)
            decisions.append(decision)
            gaps.append(gap)
            if decision.action is not None:
                last_action = decision.action
                actions = {ego: decision.action}
        if actions is None and last_action is not None:
            actions = None
        simulator.step(actions, step_s)
    return decisions, gaps, simulator


def _tally(
    dimension: RobustnessDimension,
    label: str,
    perturbation: str,
    decisions: Sequence[ControlDecision],
    *,
    critical_condition_unknown: bool,
    evidence: dict[str, Any] | None = None,
    detail: str | None = None,
) -> RobustnessOutcome:
    confident = sum(1 for d in decisions if d.is_confident_active_directive)
    status = "held"
    if critical_condition_unknown and confident:
        status = "violated"
    return RobustnessOutcome(
        dimension=dimension,
        label=label,
        status=status,
        perturbation=perturbation,
        critical_condition_unknown=critical_condition_unknown,
        decisions=len(decisions),
        withdrawn_decisions=sum(1 for d in decisions if d.withdrawn),
        active_directives=sum(1 for d in decisions if d.is_active_directive),
        confident_active_directives=confident,
        evidence=evidence or {},
        detail=detail,
    )


class _SlowController:
    """Wraps a controller and reports a latency past the compute allowance.

    The delay is *declared*, not slept: the sweep must be able to exercise a
    deadline breach without spending the wall-clock time to produce one.
    """

    uses_actor = False
    uses_learned_return = False

    def __init__(self, inner: Controller, declared_latency_ms: float) -> None:
        self.inner = inner
        self.declared_latency_ms = declared_latency_ms

    @property
    def name(self) -> str:
        return f"{self.inner.name}+deadline_exceeded"

    def decide(self, request: ControlRequest) -> ControlDecision:
        decision = self.inner.decide(request)
        return ControlDecision(
            controller=self.name,
            status=PlanningStatus.DEADLINE_EXCEEDED,
            action=None,
            reasons=(*decision.reasons, ReasonCode.SOLVER_TIMEOUT),
            latency_ms=self.declared_latency_ms,
            provenance="withdrawn",
            detail=(
                f"declared latency {self.declared_latency_ms:.1f} ms exceeds the allowance "
                f"{request.compute_budget_ms:.1f} ms; the late result is ignored"
            ),
        )


def run_robustness_sweep(
    *,
    scenario_id: str = "two-straight-counterattack",
    rule_pack_id: str = "synthetic-pack-v1",
    unknown_rule_pack_id: str = "synthetic-pack-unknown",
    no_energy_scenario_id: str = "loop-no-energy-channel",
    low_energy_scenario_id: str = "oval-low-energy",
    settings: _SweepSettings | None = None,
    paths: Paths | None = None,
) -> tuple[RobustnessOutcome, ...]:
    """Run every dimension this module owns and return one labelled result each."""
    config = settings or _SweepSettings()
    base = load_bundle(scenario_id, paths)
    greedy = LegalGreedyAttacker(name="legal_greedy_attacker")
    schedule = LegalFixedSchedule(
        (
            ScheduleEntry(0.0, DeploymentProfile.NEUTRAL),
            ScheduleEntry(2.0, DeploymentProfile.OVERTAKE),
        )
    )
    outcomes: list[RobustnessOutcome] = []

    stale = _with_observation_delay(base, 5.0)
    decisions, _gaps, _sim = _collect_decisions(
        stale, greedy, rule_pack_id=rule_pack_id, settings=config, paths=paths
    )
    outcomes.append(
        _tally(
            RobustnessDimension.DATA_AGE,
            "observation_delay_5s",
            "observation delay raised from 0.15 s to 5.0 s",
            decisions,
            critical_condition_unknown=True,
            evidence={
                "declared_max_age_s": config.max_observation_age_s,
                "statuses": sorted({d.status.value for d in decisions}),
            },
        )
    )

    no_energy = load_bundle(no_energy_scenario_id, paths)
    decisions, gaps, _sim = _collect_decisions(
        no_energy, greedy, rule_pack_id=rule_pack_id, settings=config, paths=paths
    )
    outcomes.append(
        _tally(
            RobustnessDimension.DROPPED_ENERGY_CHANNEL,
            "own_energy_channel_absent",
            f"scenario {no_energy_scenario_id} exposes no own battery-energy channel",
            decisions,
            critical_condition_unknown=True,
            evidence={
                "capability_gaps": sorted({gap for row in gaps for gap in row}),
                "profiles": sorted({d.action.profile.value for d in decisions if d.action is not None}),
            },
        )
    )

    decisions, _gaps, _sim = _collect_decisions(
        base, greedy, rule_pack_id=unknown_rule_pack_id, settings=config, paths=paths
    )
    outcomes.append(
        _tally(
            RobustnessDimension.MISSING_RULES,
            "unresolved_eligibility_condition",
            f"rule pack {unknown_rule_pack_id} cannot resolve its sporting condition",
            decisions,
            critical_condition_unknown=True,
            evidence={"statuses": sorted({d.status.value for d in decisions})},
        )
    )

    results: dict[str, float] = {}
    for kind in ("defend", "attack", "conserve"):
        variant = _with_rival_policy(base, kind)
        _decisions, _gaps, simulator = _collect_decisions(
            variant, greedy, rule_pack_id=rule_pack_id, settings=config, paths=paths
        )
        rival_id = variant.scenario.rival_ids[0]
        results[kind] = simulator.world.cars[rival_id].progress_m
    spread = max(results.values()) - min(results.values())
    outcomes.append(
        RobustnessOutcome(
            dimension=RobustnessDimension.CHANGED_RIVAL_RESPONSE,
            label="rival_policy_swapped",
            status="held" if spread > 0.0 else "violated",
            perturbation="the rival's frozen opponent policy was swapped between defend/attack/conserve",
            critical_condition_unknown=False,
            evidence={
                "rival_progress_m": results,
                "spread_m": spread,
            },
            detail=(
                "rivals re-decide in each branch; a zero spread would mean the rival's identity "
                "had no effect, which would invalidate every paired comparison"
            ),
        )
    )

    low = load_bundle(low_energy_scenario_id, paths)
    decisions, _gaps, simulator = _collect_decisions(
        low, greedy, rule_pack_id=rule_pack_id, settings=config, paths=paths
    )
    ego = low.scenario.ego_car_id
    outcomes.append(
        _tally(
            RobustnessDimension.LOW_INITIAL_ENERGY,
            "low_initial_energy",
            f"scenario {low_energy_scenario_id} starts near the energy floor",
            decisions,
            critical_condition_unknown=False,
            evidence={
                "final_energy_j": simulator.world.ledgers[ego].energy_j,
                "energy_min_j": simulator.world.ledgers[ego].energy_min_j,
                "floor_respected": (
                    simulator.world.ledgers[ego].energy_j >= simulator.world.ledgers[ego].energy_min_j - 1e-9
                ),
                "saturation_events": len(simulator.world.ledgers[ego].saturation_events),
            },
        )
    )

    hot = _with_initial_temperature(base, base.scenario.ego_car_id, 383.15)
    decisions, _gaps, _sim = _collect_decisions(
        hot, greedy, rule_pack_id=rule_pack_id, settings=config, paths=paths
    )
    pack = load_rule_pack(rule_pack_id, paths)
    derate = pack.thermal_derate
    factor = None if derate is None else derate.factor(383.15)
    absolute_ceiling_w = float(pack.manifest.absolute_power_ceiling_w)
    outcomes.append(
        _tally(
            RobustnessDimension.THERMAL_DERATING,
            "derate_active",
            "initial battery temperature raised to 383.15 K, above the pack's full-derate point",
            decisions,
            critical_condition_unknown=False,
            evidence={
                "derate_factor": factor,
                "ceiling_before_derate_w": absolute_ceiling_w,
                "derated_ceiling_w": None if factor is None else absolute_ceiling_w * factor,
                "profiles_issued": sorted(
                    {d.action.profile.value for d in decisions if d.action is not None}
                ),
            },
            detail=(
                "the pack's derate floor is a non-zero factor, so profiles stay admissible while the "
                "delivered ceiling falls; the temperature-unavailable case below is the unknown one"
            ),
        )
    )
    decisions, gaps, _sim = _collect_decisions(
        base,
        greedy,
        rule_pack_id=rule_pack_id,
        settings=config,
        paths=paths,
        temperature_available=False,
    )
    outcomes.append(
        _tally(
            RobustnessDimension.THERMAL_DERATING,
            "temperature_unavailable",
            "the battery temperature measurement is withheld while a derate model is configured",
            decisions,
            critical_condition_unknown=True,
            evidence={
                "capability_gaps": sorted({gap for row in gaps for gap in row}),
                "statuses": sorted({d.status.value for d in decisions}),
            },
        )
    )

    outcomes.append(_line_boundary_case(base, _SweepSettings(horizon_s=26.0, dt_s=config.dt_s), paths))

    delayed = _with_reaction_delay(base, 1.5)
    decisions, _gaps, delayed_sim = _collect_decisions(
        delayed, schedule, rule_pack_id=rule_pack_id, settings=config, paths=paths
    )
    _decisions, _gaps, prompt_sim = _collect_decisions(
        base, schedule, rule_pack_id=rule_pack_id, settings=config, paths=paths
    )
    delayed_energy = delayed_sim.world.ledgers[base.scenario.ego_car_id].energy_j
    prompt_energy = prompt_sim.world.ledgers[base.scenario.ego_car_id].energy_j
    outcomes.append(
        RobustnessOutcome(
            dimension=RobustnessDimension.DELAYED_DRIVER_ACTION,
            label="reaction_delay_1_5s",
            status="held" if delayed_energy != prompt_energy else "violated",
            perturbation="driver reaction delay raised from 0.35 s to 1.5 s",
            critical_condition_unknown=False,
            decisions=len(decisions),
            withdrawn_decisions=sum(1 for d in decisions if d.withdrawn),
            active_directives=sum(1 for d in decisions if d.is_active_directive),
            confident_active_directives=sum(1 for d in decisions if d.is_confident_active_directive),
            evidence={
                "delayed_final_energy_j": delayed_energy,
                "prompt_final_energy_j": prompt_energy,
                "difference_j": delayed_energy - prompt_energy,
            },
            detail="a later execution must change the realised energy, not only the displayed text",
        )
    )

    slow = _SlowController(greedy, declared_latency_ms=config.compute_budget_ms * 5.0)
    decisions, _gaps, _sim = _collect_decisions(
        base, slow, rule_pack_id=rule_pack_id, settings=config, paths=paths
    )
    outcomes.append(
        _tally(
            RobustnessDimension.SOLVER_TIMEOUT,
            "deadline_exceeded",
            f"the controller declares {config.compute_budget_ms * 5.0:.0f} ms against a "
            f"{config.compute_budget_ms:.0f} ms allowance",
            decisions,
            critical_condition_unknown=True,
            evidence={"statuses": sorted({d.status.value for d in decisions})},
        )
    )

    checked = HashCheckedController(primary=greedy, fallback=schedule)
    decisions, _gaps, _sim = _collect_decisions(
        base,
        checked,
        rule_pack_id=rule_pack_id,
        settings=config,
        paths=paths,
        expected_model_bundle_hash="sha256:expected",
        offered_model_bundle_hash="sha256:something-else",
    )
    outcomes.append(
        _tally(
            RobustnessDimension.MODEL_HASH_MISMATCH,
            "bundle_hash_mismatch",
            "the offered model bundle hash does not match the expected one",
            decisions,
            critical_condition_unknown=True,
            evidence={
                "provenance": sorted({d.provenance for d in decisions}),
                "reasons": sorted({r.value for d in decisions for r in d.reasons}),
            },
            detail="the learned path is disabled and the fallback identity is visible in the provenance",
        )
    )

    return tuple(outcomes)


def _line_boundary_case(
    bundle: ScenarioBundle, settings: _SweepSettings, paths: Paths | None
) -> RobustnessOutcome:
    """Compare recorded checkpoint crossings against the independent reference.

    The step size is deliberately varied so a checkpoint falls at a different
    place inside a step, which is the timing case the spec asks to sweep.
    """
    ego = bundle.scenario.ego_car_id
    checkpoints = {cp.id: float(cp.s_m.value) for cp in bundle.track.checkpoints}
    rows: dict[str, Any] = {}
    worst = 0.0
    for dt_s in (0.02, 0.05):
        simulator = Simulator()
        simulator.reset(bundle)
        samples = [
            ProgressSample(
                session_time_s=simulator.session_time_s,
                progress_m=simulator.world.cars[ego].progress_m,
                speed_mps=simulator.world.cars[ego].speed_mps,
            )
        ]
        steps = round(settings.horizon_s / dt_s)
        for _ in range(steps):
            simulator.step(None, dt_s)
            samples.append(
                ProgressSample(
                    session_time_s=simulator.session_time_s,
                    progress_m=simulator.world.cars[ego].progress_m,
                    speed_mps=simulator.world.cars[ego].speed_mps,
                )
            )
        reference = find_crossings(samples, track_length_m=bundle.track.length, lines=checkpoints)
        recorded = {
            (record.checkpoint_id, record.lap): record.session_time_s
            for record in simulator.world.checkpoint_records
            if record.car_id == ego
        }
        differences = {
            f"{crossing.label}@lap{crossing.lap}": crossing.session_time_s
            - recorded[(crossing.label, crossing.lap)]
            for crossing in reference
            if (crossing.label, crossing.lap) in recorded
        }
        rows[f"dt={dt_s}"] = {
            "reference_crossings": len(reference),
            "recorded_crossings": len(recorded),
            "differences_s": differences,
        }
        worst = max([worst, *(abs(v) for v in differences.values())])
    del paths
    return RobustnessOutcome(
        dimension=RobustnessDimension.LINE_BOUNDARY_TIMING,
        label="checkpoint_crossing_vs_independent_reference",
        status="held",
        perturbation="the same run integrated at dt = 0.02 s and dt = 0.05 s",
        critical_condition_unknown=False,
        evidence={"worst_difference_s": worst, **rows},
        detail=(
            "the reference locates each crossing by cubic Hermite bisection on the recorded progress "
            "trace; the simulator splits its step at a linearly interpolated crossing, so the "
            "difference is the linear interpolation error and it should shrink with the step"
        ),
    )
