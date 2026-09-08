"""Electrical deployment and recovery limits (A16-5).

Every engine-level case runs twice: on the shipped synthetic ``test-loop``
scenario and on the compiled Monza package (``geometry_validated``), started on
its main straight. Monza remains a *real-circuit synthetic scenario*: the car
is the uncalibrated synthetic sketch, so the numbers below are properties of
the model, not of any real race.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from math import inf

import pytest
from conftest import build_bundle

from afterlap_contracts import DeploymentProfile
from afterlap_core.config import Parameter
from afterlap_core.simulation import DriverAction, EnergyLedger, ScenarioBundle, Simulator, load_track
from afterlap_core.simulation.energy_limits import (
    LABEL_CAR,
    LABEL_EVENT_CONFIRMED,
    LABEL_EVENT_UNKNOWN,
    REGEN_GRIP_FLOOR,
    ElectricalLimits,
    EventEnergyLimits,
    interpolate_curve,
    usable_regen_fraction,
)
from afterlap_core.tracks.package import EventOverlay, PowerCurveRow

DT_S = 0.02
EGO = "own"
MARK_OFFSET_M = 200.0
"""Progress mark, past the start, at which the two branches are compared."""

LEDGER_TOLERANCE_J = 1.0e-4
"""Same absolute closure tolerance as ``tests/numerics/test_energy_conservation.py``."""

STANDARD_ROWS = (
    PowerCurveRow(speed_kph=0.0, power_kw=350.0),
    PowerCurveRow(speed_kph=200.0, power_kw=350.0),
    PowerCurveRow(speed_kph=250.0, power_kw=300.0),
    PowerCurveRow(speed_kph=300.0, power_kw=200.0),
    PowerCurveRow(speed_kph=360.0, power_kw=120.0),
)
"""An invented, speed-dependent standard curve below the 350 kW car ceiling above 200 km/h."""

CONFIRMED_OVERLAY = EventOverlay(
    event_id="test-event",
    ruleset_hash="test-ruleset",
    standard_curve=STANDARD_ROWS,
    recharge_allowance_mj=7.0,
    review_status="confirmed",
    reviewers=("reviewer-a", "reviewer-b"),
)
UNREVIEWED_OVERLAY = CONFIRMED_OVERLAY.model_copy(update={"review_status": "unreviewed", "reviewers": ()})
"""Identical numbers, no review: must change nothing."""


@dataclass(frozen=True)
class _Grip:
    """Test double: reference density and still air, uniform grip multiplier."""

    multiplier: float

    def air_density_kgpm3(self, s_m: float, session_time_s: float, fallback: float) -> float:
        return fallback

    def headwind_mps(self, s_m: float, heading_rad: float, session_time_s: float) -> float:
        return 0.0

    def grip_multiplier(self, s_m: float, session_time_s: float) -> float:
        return self.multiplier

    @property
    def describes(self) -> str:
        return f"test double: grip {self.multiplier}"


def _monza_bundle(**overrides) -> ScenarioBundle:
    """The shipped scenario moved onto the compiled Monza package, ego at 100 m on the main straight."""
    track = load_track("monza")
    shipped = build_bundle(**overrides)
    scenario = shipped.scenario
    states = {}
    for car_id, state in scenario.initial_states.items():
        offset = 0.0 if car_id == scenario.ego_car_id else 60.0
        states[car_id] = state.model_copy(
            update={"progress_m": state.progress_m.model_copy(update={"value": 100.0 + offset})}
        )
    scenario = scenario.model_copy(
        update={
            "track_id": track.id,
            "initial_states": states,
            "gap_ahead_s": None,
            "evaluation_checkpoints": ("sector-1-end", "sector-3-end"),
            "retention_checkpoint_id": "sector-3-end",
        }
    )
    return ScenarioBundle(scenario=scenario, track=track, car_configs=shipped.car_configs)


def _bundle(circuit: str, **overrides) -> ScenarioBundle:
    return build_bundle(**overrides) if circuit == "test-loop" else _monza_bundle(**overrides)


def _with_temperature(bundle: ScenarioBundle, temperature_k: float) -> ScenarioBundle:
    state = bundle.scenario.initial_states[EGO]
    states = dict(bundle.scenario.initial_states)
    states[EGO] = state.model_copy(
        update={"temperature_k": state.temperature_k.model_copy(update={"value": temperature_k})}
    )
    return ScenarioBundle(
        scenario=bundle.scenario.model_copy(update={"initial_states": states}),
        track=bundle.track,
        car_configs=bundle.car_configs,
    )


@dataclass
class _Run:
    rows: list[tuple[float, ...]]
    speed_at_mark_mps: float | None
    ledger: EnergyLedger
    describe: dict


def _run(
    bundle: ScenarioBundle,
    action: DriverAction,
    steps: int,
    *,
    environment=None,
    overlay: EventOverlay | None = None,
) -> _Run:
    simulator = Simulator().reset(bundle, seed=7, environment=environment, event_overlay=overlay)
    start = simulator.world.cars[EGO].progress_m
    rows: list[tuple[float, ...]] = []
    speed_at_mark = None
    describe: dict = {}
    for _ in range(steps):
        report = simulator.step({EGO: action}, DT_S)
        ego = simulator.world.cars[EGO]
        rows.append(
            (
                ego.progress_m,
                ego.speed_mps,
                ego.battery_energy_j,
                ego.deploy_power_dc_w,
                ego.harvest_power_dc_w,
                ego.mechanical_braking_power_w,
            )
        )
        if speed_at_mark is None and ego.progress_m >= start + MARK_OFFSET_M:
            speed_at_mark = ego.speed_mps
        describe = report.electrical_limits[EGO]
    return _Run(rows, speed_at_mark, simulator.world.ledgers[EGO], describe)


CIRCUITS = ("test-loop", "monza")


@pytest.mark.parametrize("circuit", CIRCUITS)
def test_attack_deployment_is_faster_at_the_mark_and_costs_battery_energy(circuit: str) -> None:
    bundle = _bundle(circuit)
    neutral = _run(bundle, DriverAction(profile=DeploymentProfile.NEUTRAL, throttle=1.0, brake=0.0), 150)
    attack = _run(bundle, DriverAction(profile=DeploymentProfile.OVERTAKE, throttle=1.0, brake=0.0), 150)

    assert neutral.speed_at_mark_mps is not None and attack.speed_at_mark_mps is not None
    assert attack.speed_at_mark_mps > neutral.speed_at_mark_mps
    assert attack.rows[-1][2] < neutral.rows[-1][2], "more deployment must leave less stored energy"

    for run in (neutral, attack):
        ledger = run.ledger
        assert abs(ledger.close_error()) < LEDGER_TOLERANCE_J
        assert ledger.battery_out_j - ledger.auxiliary_j == pytest.approx(
            ledger.deployed_dc_j / ledger.eta_discharge, rel=1e-12, abs=LEDGER_TOLERANCE_J
        )
        assert ledger.battery_in_j == 0.0, "full throttle on a straight harvests nothing"


def _braking(circuit: str) -> ScenarioBundle:
    if circuit == "test-loop":
        return build_bundle(speeds_mps={EGO: 85.0}, progress_m={EGO: 0.0, "rival": 500.0})
    return _monza_bundle(speeds_mps={EGO: 85.0})


BRAKE = DriverAction(profile=DeploymentProfile.HARVEST, throttle=0.0, brake=1.0)


@pytest.mark.parametrize("circuit", CIRCUITS)
def test_harvested_power_never_exceeds_the_physical_bounds(circuit: str) -> None:
    bundle = _braking(circuit)
    car = bundle.car_configs[EGO]
    for grip in (1.0, 0.6):
        run = _run(bundle, BRAKE, 100, environment=_Grip(grip))
        assert any(row[4] > 0.0 for row in run.rows), "the braking event must actually harvest"
        for _, _, _, _, harvest_w, mechanical_w in run.rows:
            bound = min(float(car.max_harvest_power_w.value), float(car.regen_share.value) * mechanical_w)
            assert harvest_w <= bound + 1e-9
            assert harvest_w <= mechanical_w + 1e-9, "wheel work cannot enter the battery twice"


@pytest.mark.parametrize("circuit", CIRCUITS)
def test_lower_grip_harvests_strictly_less_and_the_rest_is_friction_braked(circuit: str) -> None:
    bundle = _braking(circuit)
    dry = _run(bundle, BRAKE, 100, environment=_Grip(1.0))
    wet = _run(bundle, BRAKE, 100, environment=_Grip(0.6))

    assert wet.ledger.harvested_dc_j < dry.ledger.harvested_dc_j
    assert wet.describe["regen_grip_fraction"] == pytest.approx(
        usable_regen_fraction(0.6, float(REGEN_GRIP_FLOOR.value), 1.0)
    )
    assert dry.describe["regen_grip_fraction"] == 1.0

    no_regen_cars = {
        car_id: cfg.model_copy(update={"regen_enabled": False}) for car_id, cfg in bundle.car_configs.items()
    }
    friction_only = ScenarioBundle(scenario=bundle.scenario, track=bundle.track, car_configs=no_regen_cars)
    friction = _run(friction_only, BRAKE, 100, environment=_Grip(0.6))
    assert [row[1] for row in friction.rows] == [row[1] for row in wet.rows]
    assert friction.ledger.harvested_dc_j == 0.0
    assert wet.ledger.mechanical_offered_j - wet.ledger.harvested_dc_j >= 0.0


def test_the_grip_law_binds_below_the_max_harvest_ceiling() -> None:
    """Unit view of the same law at a braking power where the grip term is the minimum."""
    car = build_bundle().car_configs[EGO]
    limits_dry = ElectricalLimits(car, EventEnergyLimits.none(), 308.15, 1.0)
    limits_wet = ElectricalLimits(car, EventEnergyLimits.none(), 308.15, 0.6)
    mechanical_w = 400_000.0
    route_w = float(car.regen_share.value) * mechanical_w
    assert limits_dry.harvest_ceiling_dc_w(60.0, mechanical_w) == route_w
    expected = usable_regen_fraction(0.6, float(REGEN_GRIP_FLOOR.value), 1.0) * route_w
    assert limits_wet.harvest_ceiling_dc_w(60.0, mechanical_w) == pytest.approx(expected)
    assert limits_wet.harvest_ceiling_dc_w(60.0, mechanical_w) < route_w
    assert ElectricalLimits(car, EventEnergyLimits.none(), 308.15, 0.3).harvest_ceiling_dc_w(60.0, 1e6) == 0.0
    assert usable_regen_fraction(1.0, 0.3, 1.0) == 1.0
    assert usable_regen_fraction(1.2, 0.3, 1.0) == 1.0


def test_battery_acceptance_limits_harvest_when_the_car_declares_a_ramp() -> None:
    car = build_bundle().car_configs[EGO]
    ramp = car.derate_start_temperature_k
    accepting = car.model_copy(
        update={
            "charge_acceptance_start_temperature_k": ramp.model_copy(update={"value": 300.0}),
            "charge_acceptance_end_temperature_k": ramp.model_copy(update={"value": 320.0}),
        }
    )
    max_harvest = float(car.max_harvest_power_w.value)
    cold = ElectricalLimits(accepting, EventEnergyLimits.none(), 300.0, 1.0)
    warm = ElectricalLimits(accepting, EventEnergyLimits.none(), 310.0, 1.0)
    hot = ElectricalLimits(accepting, EventEnergyLimits.none(), 320.0, 1.0)
    assert cold.harvest_ceiling_dc_w(60.0, 5e6) == max_harvest
    assert warm.harvest_ceiling_dc_w(60.0, 5e6) == pytest.approx(0.5 * max_harvest)
    assert hot.harvest_ceiling_dc_w(60.0, 5e6) == 0.0
    assert warm.describe()["harvest_acceptance"] == LABEL_CAR
    undeclared = ElectricalLimits(car, EventEnergyLimits.none(), 320.0, 1.0)
    assert undeclared.charge_acceptance() == 1.0
    assert undeclared.describe()["harvest_acceptance"] == "none_declared"


def test_a_half_declared_acceptance_ramp_is_refused() -> None:
    car = build_bundle().car_configs[EGO]
    payload = car.model_dump(mode="json")
    payload["charge_acceptance_start_temperature_k"] = car.derate_start_temperature_k.model_dump(mode="json")
    with pytest.raises(ValueError, match="declared together"):
        type(car).model_validate(payload)


ATTACK = DriverAction(profile=DeploymentProfile.OVERTAKE, throttle=1.0, brake=0.0)


@pytest.mark.parametrize("circuit", CIRCUITS)
def test_a_confirmed_standard_curve_below_the_car_ceiling_reduces_deployment(circuit: str) -> None:
    bundle = _bundle(circuit)
    car = bundle.car_configs[EGO]
    baseline = _run(bundle, ATTACK, 150)
    limited = _run(bundle, ATTACK, 150, overlay=CONFIRMED_OVERLAY)

    assert all(row[3] == float(car.max_deploy_power_w.value) for row in baseline.rows[:5])
    assert all(row[3] < float(car.max_deploy_power_w.value) for row in limited.rows)
    assert limited.speed_at_mark_mps is not None and baseline.speed_at_mark_mps is not None
    assert limited.speed_at_mark_mps < baseline.speed_at_mark_mps
    assert limited.rows[-1][2] > baseline.rows[-1][2], "less deployment leaves more energy"
    assert limited.describe["deploy_standard"] == LABEL_EVENT_CONFIRMED
    assert limited.describe["event_id"] == "test-event"
    assert limited.describe["recharge_allowance"] == LABEL_EVENT_CONFIRMED
    assert limited.describe["recharge_allowance_j"] == 7.0e6
    assert baseline.describe["deploy_standard"] == LABEL_CAR
    assert abs(limited.ledger.close_error()) < LEDGER_TOLERANCE_J


@pytest.mark.parametrize("circuit", CIRCUITS)
def test_an_unreviewed_overlay_with_identical_numbers_changes_nothing(circuit: str) -> None:
    bundle = _bundle(circuit)
    baseline = _run(bundle, ATTACK, 150)
    unreviewed = _run(bundle, ATTACK, 150, overlay=UNREVIEWED_OVERLAY)
    assert unreviewed.rows == baseline.rows, "unknown never widens and never tightens: bit-identical"
    assert unreviewed.describe["deploy_standard"] == LABEL_EVENT_UNKNOWN
    assert unreviewed.describe["deploy_overtake"] == LABEL_EVENT_UNKNOWN
    assert unreviewed.describe["recharge_allowance"] == LABEL_EVENT_UNKNOWN
    assert unreviewed.describe["recharge_allowance_j"] is None
    assert unreviewed.describe["review_status"] == "unreviewed"


def test_the_scenario_event_id_loads_the_shipped_monza_overlay_lazily() -> None:
    bundle = _monza_bundle()
    named = ScenarioBundle(
        scenario=bundle.scenario.model_copy(update={"event_id": "2026-italy"}),
        track=bundle.track,
        car_configs=bundle.car_configs,
    )
    baseline = _run(bundle, ATTACK, 50)
    with_event = _run(named, ATTACK, 50)
    assert with_event.describe["event_id"] == "2026-italy"
    assert with_event.describe["review_status"] == "unreviewed"
    assert with_event.describe["deploy_standard"] == LABEL_EVENT_UNKNOWN
    assert with_event.rows == baseline.rows

    missing = ScenarioBundle(
        scenario=bundle.scenario.model_copy(update={"event_id": "no-such-event"}),
        track=bundle.track,
        car_configs=bundle.car_configs,
    )
    absent = _run(missing, ATTACK, 50)
    assert absent.describe["event_id"] is None, "a missing overlay is no overlay, not an error"
    assert absent.rows == baseline.rows


def test_curve_interpolation_and_eligibility_fallback() -> None:
    car = build_bundle().car_configs[EGO]
    limits = ElectricalLimits.build(car, CONFIRMED_OVERLAY, battery_temperature_k=308.15)
    assert limits.deploy_ceiling_dc_w(75.0) == pytest.approx(260_000.0)
    assert limits.deploy_ceiling_dc_w(0.0) == 350_000.0
    assert limits.deploy_ceiling_dc_w(150.0) == pytest.approx(120_000.0)
    assert limits.deploy_ceiling_dc_w(75.0, overtake_eligible=True) == pytest.approx(260_000.0)
    assert limits.describe()["deploy_overtake"] == LABEL_EVENT_CONFIRMED
    with_overtake = CONFIRMED_OVERLAY.model_copy(
        update={"overtake_curve": (PowerCurveRow(speed_kph=0.0, power_kw=300.0),)}
    )
    both = ElectricalLimits.build(car, with_overtake, battery_temperature_k=308.15)
    assert both.deploy_ceiling_dc_w(75.0, overtake_eligible=True) == 300_000.0
    assert both.deploy_ceiling_dc_w(75.0, overtake_eligible=False) == pytest.approx(260_000.0)
    assert interpolate_curve(((), ()), 50.0) == inf
    none_defined = CONFIRMED_OVERLAY.model_copy(update={"standard_curve": ()})
    open_limits = ElectricalLimits.build(car, none_defined, battery_temperature_k=308.15)
    assert open_limits.deploy_ceiling_dc_w(75.0) == 350_000.0
    assert open_limits.describe()["deploy_standard"] == LABEL_CAR


def test_a_confirmed_curve_can_never_widen_the_car_ceiling() -> None:
    car = build_bundle().car_configs[EGO]
    generous = CONFIRMED_OVERLAY.model_copy(
        update={"standard_curve": (PowerCurveRow(speed_kph=0.0, power_kw=900.0),)}
    )
    limits = ElectricalLimits.build(car, generous, battery_temperature_k=308.15)
    assert limits.deploy_ceiling_dc_w(75.0) == float(car.max_deploy_power_w.value)


def test_battery_temperature_derates_deployment_monotonically() -> None:
    car = build_bundle().car_configs[EGO]
    start = float(car.derate_start_temperature_k.value)
    end = float(car.derate_end_temperature_k.value)
    temperatures = [
        start - 20.0,
        start,
        start + 0.25 * (end - start),
        0.5 * (start + end),
        end - 1.0,
        end,
        end + 10,
    ]
    ceilings = [
        ElectricalLimits(car, EventEnergyLimits.none(), t, 1.0).deploy_ceiling_dc_w(75.0)
        for t in temperatures
    ]
    assert ceilings[0] == ceilings[1] == float(car.max_deploy_power_w.value)
    assert all(later <= earlier for earlier, later in pairwise(ceilings))
    assert ceilings[2] > ceilings[3] > ceilings[4] > ceilings[5] == ceilings[6] == 0.0


@pytest.mark.parametrize("circuit", CIRCUITS)
def test_a_hotter_battery_deploys_less_in_the_engine(circuit: str) -> None:
    bundle = _bundle(circuit)
    car = bundle.car_configs[EGO]
    mid_ramp = 0.5 * (float(car.derate_start_temperature_k.value) + float(car.derate_end_temperature_k.value))
    cool = _run(bundle, ATTACK, 50)
    hot = _run(_with_temperature(bundle, mid_ramp), ATTACK, 50)
    assert hot.rows[0][3] < cool.rows[0][3]
    assert hot.describe["thermal_derate_factor"] < cool.describe["thermal_derate_factor"] == 1.0
    assert hot.rows[-1][2] > cool.rows[-1][2]


def test_coefficients_are_labelled_synthetic_assumptions() -> None:
    from afterlap_core.simulation.energy_limits import REGEN_GRIP_EXPONENT

    for parameter in (REGEN_GRIP_FLOOR, REGEN_GRIP_EXPONENT):
        assert isinstance(parameter, Parameter)
        assert parameter.verification.value == "synthetic_assumption"
        assert parameter.unit == "1"
        assert parameter.note


def test_the_simulator_exposes_the_limits_in_force() -> None:
    bundle = build_bundle()
    simulator = Simulator().reset(bundle, seed=1)
    assert simulator.electrical_limits(EGO) is None
    simulator.step({EGO: ATTACK}, DT_S)
    limits = simulator.electrical_limits(EGO)
    assert isinstance(limits, ElectricalLimits)
    assert limits.recharge_allowance_j() is None
    assert limits.describe()["deploy_standard"] == LABEL_CAR
