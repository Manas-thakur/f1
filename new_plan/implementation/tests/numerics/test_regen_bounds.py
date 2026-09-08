"""Regeneration bounds keep the battery balance closed (A16-5).

Adding grip, acceptance and event limits in front of the ledger must not open
the energy balance: the limits only shrink what the ledger is offered, and the
shortfall is friction braking the car still feels.
"""

from __future__ import annotations

from dataclasses import dataclass

from conftest import build_bundle

from afterlap_contracts import DeploymentProfile
from afterlap_core.simulation import DriverAction, ScenarioBundle, Simulator
from afterlap_core.tracks.package import EventOverlay, PowerCurveRow

ENERGY_CLOSE_TOLERANCE_J = 1.0e-4
"""As in ``test_energy_conservation.py``."""


@dataclass(frozen=True)
class _Wet:
    def air_density_kgpm3(self, s_m, session_time_s, fallback):
        return fallback

    def headwind_mps(self, s_m, heading_rad, session_time_s):
        return 0.0

    def grip_multiplier(self, s_m, session_time_s):
        return 0.7

    @property
    def describes(self) -> str:
        return "test double: 0.7 grip"


def _accepting_bundle() -> ScenarioBundle:
    bundle = build_bundle(speeds_mps={"own": 85.0}, progress_m={"own": 0.0, "rival": 500.0})
    cars = {}
    for car_id, cfg in bundle.car_configs.items():
        ramp = cfg.derate_start_temperature_k
        cars[car_id] = cfg.model_copy(
            update={
                "charge_acceptance_start_temperature_k": ramp.model_copy(update={"value": 300.0}),
                "charge_acceptance_end_temperature_k": ramp.model_copy(update={"value": 330.0}),
            }
        )
    return ScenarioBundle(scenario=bundle.scenario, track=bundle.track, car_configs=cars)


OVERLAY = EventOverlay(
    event_id="bounds-event",
    ruleset_hash="bounds",
    standard_curve=(
        PowerCurveRow(speed_kph=0.0, power_kw=250.0),
        PowerCurveRow(speed_kph=360.0, power_kw=100.0),
    ),
    review_status="confirmed",
    reviewers=("a", "b"),
)


def test_every_limit_active_keeps_the_ledger_closed_and_the_harvest_bounded() -> None:
    bundle = _accepting_bundle()
    car = bundle.car_configs["own"]
    simulator = Simulator().reset(bundle, seed=3, environment=_Wet(), event_overlay=OVERLAY)
    brake = DriverAction(profile=DeploymentProfile.HARVEST, throttle=0.0, brake=1.0)
    push = DriverAction(profile=DeploymentProfile.OVERTAKE, throttle=1.0, brake=0.0)

    harvested_any = False
    for index in range(200):
        action = brake if index < 100 else push
        report = simulator.step({"own": action}, 0.02)
        state = simulator.world.cars["own"]
        described = report.electrical_limits["own"]
        # Battery acceptance at 308 K on a 300-330 K ramp is 0.733...; grip 0.7 on a
        # 0.3 floor gives 0.571...; both are in force and both are reported.
        assert 0.0 < described["charge_acceptance_factor"] < 1.0
        assert 0.0 < described["regen_grip_fraction"] < 1.0
        bound = min(
            float(car.max_harvest_power_w.value) * described["charge_acceptance_factor"],
            float(car.regen_share.value) * state.mechanical_braking_power_w,
        )
        assert state.harvest_power_dc_w <= bound + 1e-9
        assert state.deploy_power_dc_w <= 250_000.0 + 1e-9
        harvested_any = harvested_any or state.harvest_power_dc_w > 0.0
    assert harvested_any

    ledger = simulator.world.ledgers["own"]
    assert abs(ledger.close_error()) < ENERGY_CLOSE_TOLERANCE_J
    assert ledger.harvested_dc_j > 0.0
    assert ledger.deployed_dc_j > 0.0
    assert ledger.mechanical_offered_j >= ledger.harvested_dc_j
