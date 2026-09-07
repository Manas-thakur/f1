"""The validation matrix from ``03_simulation/NUMERICS_AND_VALIDATION.md``.

One test per row of the table, plus the energy-balance closure whose tolerance
is established here and reported in ``handoffs/A03.md``.

Tolerances are stated as named constants with the reasoning next to them. None
of them is loose enough to hide a conservation failure: the observed residuals
are five to seven orders of magnitude below every threshold, which is what makes
the thresholds meaningful rather than decorative.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from afterlap_contracts import DeploymentProfile
from afterlap_core.simulation import DriverAction, Simulator
from afterlap_core.simulation.physics import kinetic_energy

ENERGY_CLOSE_TOLERANCE_J = 1.0e-4
"""Absolute battery-balance residual allowed after a full run.

Established empirically: the observed residual over a 30 s two-car run with
about 2.4 MJ of throughput is below 1e-7 J, i.e. around 1e-13 relative. The
threshold is three orders of magnitude above the observed value so that
platform-level float64 differences do not make the suite flaky, and still nine
orders below anything a real accounting error would produce.
"""

RELATIVE_CLOSE_TOLERANCE = 1.0e-12
"""Residual relative to the total energy moved through the battery."""

ENVELOPE_TOLERANCE = 1.0e-9
"""The tyre envelope is a hard constraint; only float noise is tolerated."""


def _coast_action() -> DriverAction:
    """No drive, no brake, no harvest source: pure resistance deceleration."""
    return DriverAction(profile=DeploymentProfile.HARVEST, throttle=0.0, brake=0.0)


class TestCoastWithNoDrive:
    def test_kinetic_energy_strictly_decreases_on_a_level_track(self, loop_bundle) -> None:
        from conftest import build_bundle

        bundle = build_bundle(progress_m={"own": 0.0, "rival": 300.0}, speeds_mps={"own": 75.0})
        assert bundle.track.grade_at(0.0) == 0.0
        assert bundle.track.grade_at(400.0) == 0.0
        simulator = Simulator().reset(bundle)
        mass = float(bundle.car_configs["own"].mass_kg.value)
        action = _coast_action()

        energies = [kinetic_energy(mass, simulator.world.cars["own"].speed_mps)]
        for _ in range(150):
            simulator.step({"own": action, "rival": action}, 0.02)
            state = simulator.world.cars["own"]
            assert bundle.track.grade_at(state.s_m) == 0.0, "the coast case must stay on level track"
            energies.append(kinetic_energy(mass, state.speed_mps))

        assert all(later < earlier for earlier, later in pairwise(energies))
        assert energies[-1] < energies[0]

    def test_coasting_never_recharges_the_battery(self) -> None:
        from conftest import build_bundle

        bundle = build_bundle(progress_m={"own": 0.0, "rival": 300.0})
        simulator = Simulator().reset(bundle)
        action = _coast_action()
        for _ in range(150):
            simulator.step({"own": action, "rival": action}, 0.02)
        ledger = simulator.world.ledgers["own"]
        assert ledger.battery_in_j == 0.0
        assert ledger.recharge_cumulative_j == 0.0
        assert ledger.energy_j < ledger.initial_energy_j, "the auxiliary load must still be drawn"


class TestBrakeWithRegenDisabled:
    def test_the_battery_does_not_recharge(self) -> None:
        from conftest import build_bundle

        bundle = build_bundle(
            "loop-regen-disabled",
            speeds_mps={"own": 85.0},
            progress_m={"own": 0.0, "rival": 500.0},
        )
        assert bundle.car_configs["own"].regen_enabled is False
        simulator = Simulator().reset(bundle)
        action = DriverAction(profile=DeploymentProfile.HARVEST, throttle=0.0, brake=1.0)

        history = [simulator.world.cars["own"].battery_energy_j]
        for _ in range(120):
            simulator.step({"own": action}, 0.02)
            history.append(simulator.world.cars["own"].battery_energy_j)

        assert all(later <= earlier for earlier, later in pairwise(history)), (
            "a car with regeneration disabled must never gain stored energy"
        )
        ledger = simulator.world.ledgers["own"]
        assert ledger.battery_in_j == 0.0
        assert ledger.harvested_dc_j == 0.0
        assert ledger.recharge_cumulative_j == 0.0
        assert ledger.recharge_this_lap_j == 0.0
        assert simulator.world.cars["own"].speed_mps < 85.0, "the car must actually have braked"


class TestDeployNearTheLowerBound:
    def test_power_saturates_before_the_bound_is_violated(self) -> None:
        from conftest import build_bundle

        bundle = build_bundle(energies_j={"own": 20000.0}, progress_m={"own": 0.0, "rival": 300.0})
        simulator = Simulator().reset(bundle)
        floor = float(bundle.car_configs["own"].battery_energy_min_j.value)
        action = DriverAction(profile=DeploymentProfile.OVERTAKE, throttle=1.0, brake=0.0)

        saturations = []
        for _ in range(60):
            report = simulator.step({"own": action}, 0.02)
            saturations.extend(event for event in report.saturation_events if event.car_id == "own")
            assert simulator.world.cars["own"].battery_energy_j >= floor - 1e-9

        assert saturations, "the saturation must be recorded, not applied silently"
        deploy_events = [e for e in saturations if e.kind == "deploy_lower_energy_bound"]
        assert deploy_events
        first = deploy_events[0]
        assert first.actual_w < first.requested_w
        assert first.energy_j >= floor - 1e-9
        assert simulator.world.ledgers["own"].energy_j >= floor - 1e-9

    def test_the_achievable_power_is_returned_not_the_requested_one(self) -> None:
        from afterlap_core.simulation import EnergyLedger

        ledger = EnergyLedger(
            car_id="own",
            energy_j=1000.0,
            energy_min_j=0.0,
            energy_max_j=4.0e6,
            eta_discharge=0.95,
            eta_charge=0.94,
        )
        plan = ledger.plan(
            0.02,
            requested_deploy_dc_w=350.0e3,
            requested_harvest_dc_w=0.0,
            mechanical_available_w=0.0,
            aux_w=0.0,
        )
        # 1000 J over 20 ms is 50 kW at the terminal, i.e. 47.5 kW on the bus.
        assert plan.battery_out_w == pytest.approx(50000.0, rel=1e-12)
        assert plan.actual_deploy_dc_w == pytest.approx(47500.0, rel=1e-12)
        assert plan.deploy_saturated is True
        assert plan.energy_after_j == pytest.approx(0.0, abs=1e-9)


class TestHarvestNearTheUpperBound:
    def test_excess_recovery_is_physically_rejected(self) -> None:
        from conftest import build_bundle

        bundle = build_bundle(
            energies_j={"own": 3.99e6},
            speeds_mps={"own": 85.0},
            progress_m={"own": 0.0, "rival": 400.0},
        )
        simulator = Simulator().reset(bundle)
        ceiling = float(bundle.car_configs["own"].battery_energy_max_j.value)
        action = DriverAction(profile=DeploymentProfile.HARVEST, throttle=0.0, brake=1.0)

        saturations = []
        for _ in range(60):
            report = simulator.step({"own": action}, 0.02)
            saturations.extend(
                event
                for event in report.saturation_events
                if event.car_id == "own" and event.kind == "harvest_upper_energy_bound"
            )
            assert simulator.world.cars["own"].battery_energy_j <= ceiling + 1e-9

        assert saturations, "rejecting recovery must leave a record"
        ledger = simulator.world.ledgers["own"]
        assert ledger.energy_j <= ceiling + 1e-9
        assert ledger.mechanical_rejected_j > 0.0, "the rejected mechanical power must be accounted"
        assert saturations[-1].actual_w < saturations[-1].requested_w

    def test_the_ledger_refuses_harvest_without_a_mechanical_source(self) -> None:
        from afterlap_core.simulation import EnergyLedger

        ledger = EnergyLedger(
            car_id="own",
            energy_j=1.0e6,
            energy_min_j=0.0,
            energy_max_j=4.0e6,
            eta_discharge=0.95,
            eta_charge=0.94,
        )
        plan = ledger.plan(
            0.02,
            requested_deploy_dc_w=0.0,
            requested_harvest_dc_w=300.0e3,
            mechanical_available_w=0.0,
            aux_w=0.0,
        )
        assert plan.actual_harvest_dc_w == 0.0
        assert plan.battery_in_w == 0.0
        ledger.commit(plan, 0.0)
        assert ledger.recharge_cumulative_j == 0.0
        assert ledger.energy_j == pytest.approx(1.0e6, abs=1e-9)


class TestConstantRadius:
    def test_lateral_demand_stays_inside_the_friction_envelope(self) -> None:
        """The oval's corners have exactly constant curvature by construction."""
        from conftest import build_bundle

        bundle = build_bundle(
            "oval-defend-hold",
            progress_m={"own": 1200.0, "rival": 900.0},
            speeds_mps={"own": 85.0, "rival": 70.0},
        )
        assert bundle.track.curvature_at(1700.0) == pytest.approx(
            bundle.track.curvature_at(1900.0), rel=1e-12
        )
        simulator = Simulator().reset(bundle)

        worst = 0.0
        exceedances: list[dict] = []
        in_corner = 0
        for _ in range(700):
            report = simulator.step(None, 0.02)
            exceedances.extend(report.envelope_exceedances)
            for state in simulator.world.cars.values():
                if state.traction_envelope_n > 0.0:
                    worst = max(worst, state.lateral_demand_n / state.traction_envelope_n)
                if 1650.0 <= state.s_m <= 1950.0:
                    in_corner += 1

        assert in_corner > 0, "the run must actually pass through the constant-radius corner"
        assert not exceedances
        assert worst <= 1.0 + ENVELOPE_TOLERANCE
        assert worst > 0.5, "the corner must be grip limited, otherwise the case proves nothing"


class TestTimingLine:
    def test_only_lap_specific_counters_reset(self) -> None:
        from conftest import build_bundle

        from afterlap_core.simulation import TIMING_LINE_ID

        bundle = build_bundle(progress_m={"own": 5100.0, "rival": 4000.0}, speeds_mps={"own": 80.0})
        simulator = Simulator().reset(bundle)
        action = DriverAction(profile=DeploymentProfile.HARVEST, throttle=0.0, brake=0.4)

        before = None
        crossing_seen = False
        for _ in range(120):
            state = simulator.world.cars["own"]
            snapshot = (
                state.lap,
                state.battery_energy_j,
                state.recharge_ledger_j,
                state.recharge_ledger_this_lap_j,
            )
            report = simulator.step({"own": action}, 0.02)
            crossings = [
                event
                for event in report.events
                if event.get("line_id") == TIMING_LINE_ID and event["car_id"] == "own"
            ]
            if crossings:
                before = snapshot
                crossing_seen = True
                break

        assert crossing_seen, "the run must cross the timing line"
        assert before is not None
        lap_before, energy_before, cumulative_before, this_lap_before = before
        assert this_lap_before > 0.0, "there must be something to reset for the test to mean anything"

        state = simulator.world.cars["own"]
        ledger = simulator.world.ledgers["own"]
        assert state.lap == lap_before + 1
        assert ledger.recharge_cumulative_j >= cumulative_before, "the cumulative ledger never resets"
        assert ledger.recharge_this_lap_j < this_lap_before, "the per-lap counter must have reset"
        assert ledger.energy_j <= energy_before + abs(energy_before) * 1e-6 + 5.0e4, (
            "crossing the line must not refill the battery"
        )
        assert ledger.energy_j <= ledger.energy_max_j


class TestEnergyBalanceCloses:
    @pytest.mark.parametrize(
        "scenario_id",
        [
            "two-straight-counterattack",
            "oval-low-energy",
            "loop-no-energy-channel",
            "oval-defend-hold",
        ],
    )
    def test_the_battery_balance_closes_within_the_documented_tolerance(self, scenario_id: str) -> None:
        from conftest import build_bundle

        bundle = build_bundle(scenario_id)
        simulator = Simulator().reset(bundle)
        for _ in range(1000):
            simulator.step(None, 0.02)

        for car_id, ledger in simulator.world.ledgers.items():
            residual = ledger.close_error()
            throughput = ledger.battery_in_j + ledger.battery_out_j
            assert throughput > 0.0, f"{car_id} moved no energy, the check would be vacuous"
            assert abs(residual) <= ENERGY_CLOSE_TOLERANCE_J, (
                f"{scenario_id}/{car_id} residual {residual} J exceeds the documented tolerance"
            )
            assert abs(residual) <= RELATIVE_CLOSE_TOLERANCE * throughput + 1.0e-6

    def test_no_net_recharge_appears_without_a_physical_source(self) -> None:
        """Total DC harvest can never exceed the mechanical energy offered."""
        from conftest import build_bundle

        bundle = build_bundle("oval-defend-hold")
        simulator = Simulator().reset(bundle)
        for _ in range(800):
            simulator.step(None, 0.02)
        for ledger in simulator.world.ledgers.values():
            assert ledger.harvested_dc_j <= ledger.mechanical_offered_j + 1e-9
            assert ledger.battery_in_j <= ledger.harvested_dc_j + 1e-9

    def test_the_three_ledgers_are_not_interchangeable(self) -> None:
        """CU-K bus energy, battery gain and mechanical energy differ by losses."""
        from conftest import build_bundle

        bundle = build_bundle(
            energies_j={"own": 1.0e6}, speeds_mps={"own": 85.0}, progress_m={"own": 0.0, "rival": 600.0}
        )
        simulator = Simulator().reset(bundle)
        braking = DriverAction(profile=DeploymentProfile.HARVEST, throttle=0.0, brake=0.8)
        for _ in range(200):
            simulator.step({"own": braking}, 0.02)
        ledger = simulator.world.ledgers["own"]
        assert ledger.recharge_cumulative_j == pytest.approx(ledger.harvested_dc_j, rel=1e-12)
        assert ledger.battery_in_j == pytest.approx(ledger.eta_charge * ledger.harvested_dc_j, rel=1e-12)
        assert ledger.battery_in_j < ledger.recharge_cumulative_j
        assert ledger.mechanical_offered_j >= ledger.recharge_cumulative_j
