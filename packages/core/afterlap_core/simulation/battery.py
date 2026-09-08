"""Three separate energy ledgers with an auditable balance.

The three quantities the plan insists on keeping apart:

1. **Battery stored energy** (J at the battery terminal). This is the physical
   state of charge in an explicit operating window.
2. **CU-K DC-bus recharge ledger** (J on the DC bus). A *regulatory* count of
   the quantity measured at its specified bus. It is not battery gain: the two
   differ by the charge efficiency, and mixing them is exactly the error
   ``UNITS_TIME.md`` forbids.
3. **Mechanical/auxiliary accounting** (J). Mechanical energy offered to the
   generator, mechanical energy rejected because the battery could not take it,
   and auxiliary electrical draw.

Everything is planned first (:meth:`EnergyLedger.plan`, a pure function of the
current state) and only then committed (:meth:`EnergyLedger.commit`). That split
is what lets the integrator evaluate a midpoint derivative without the ledger
advancing twice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .physics import battery_in_power, battery_out_power


@dataclass(frozen=True, slots=True)
class LedgerPlan:
    """What the ledger *would* do for one step. Pure; nothing has moved yet."""

    dt_s: float
    requested_deploy_dc_w: float
    actual_deploy_dc_w: float
    requested_harvest_dc_w: float
    actual_harvest_dc_w: float
    mechanical_offered_w: float
    mechanical_rejected_w: float
    aux_w: float
    battery_out_w: float
    battery_in_w: float
    loss_w: float
    deploy_saturated: bool
    harvest_saturated: bool
    energy_after_j: float

    @property
    def net_battery_w(self) -> float:
        """Signed battery terminal flow; positive means the battery is charging.

        The convention is stated here once. It never coexists with the
        non-negative ``battery_out_w``/``battery_in_w`` flows without this label.
        """
        return self.battery_in_w - self.battery_out_w


@dataclass(frozen=True, slots=True)
class SaturationEvent:
    """A recorded refusal to violate a physical bound."""

    session_time_s: float
    car_id: str
    kind: str
    requested_w: float
    actual_w: float
    energy_j: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_time_s": self.session_time_s,
            "car_id": self.car_id,
            "kind": self.kind,
            "requested_w": self.requested_w,
            "actual_w": self.actual_w,
            "energy_j": self.energy_j,
        }


@dataclass(slots=True)
class EnergyLedger:
    """Battery state plus the independent regulatory and mechanical ledgers."""

    car_id: str
    energy_j: float
    energy_min_j: float
    energy_max_j: float
    eta_discharge: float
    eta_charge: float

    recharge_cumulative_j: float = 0.0
    recharge_this_lap_j: float = 0.0

    deployed_dc_j: float = 0.0
    harvested_dc_j: float = 0.0
    mechanical_offered_j: float = 0.0
    mechanical_rejected_j: float = 0.0
    auxiliary_j: float = 0.0
    conversion_loss_j: float = 0.0

    battery_out_j: float = 0.0
    battery_in_j: float = 0.0
    initial_energy_j: float = math.nan

    saturation_events: list[SaturationEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.energy_min_j >= self.energy_max_j:
            raise ValueError("battery energy window is empty")
        if not self.energy_min_j <= self.energy_j <= self.energy_max_j:
            raise ValueError(
                f"initial energy {self.energy_j} is outside the window "
                f"[{self.energy_min_j}, {self.energy_max_j}]"
            )
        if math.isnan(self.initial_energy_j):
            self.initial_energy_j = self.energy_j

    def plan(
        self,
        dt_s: float,
        *,
        requested_deploy_dc_w: float,
        requested_harvest_dc_w: float,
        mechanical_available_w: float,
        aux_w: float,
    ) -> LedgerPlan:
        """Saturate the requests against the energy window without mutating state.

        Ordering inside a step is fixed so the result never depends on call
        order: auxiliary draw first (it is not optional), then deployment, then
        harvest into whatever headroom remains.
        """
        if dt_s <= 0.0:
            raise ValueError("ledger steps need a positive duration")
        if requested_deploy_dc_w < 0.0 or requested_harvest_dc_w < 0.0:
            raise ValueError("deploy and harvest requests are non-negative flows")
        if mechanical_available_w < 0.0:
            raise ValueError("mechanical power offered to the generator cannot be negative")
        if aux_w < 0.0:
            raise ValueError("auxiliary load cannot be negative")

        energy = self.energy_j

        aux_capacity_w = max(0.0, (energy - self.energy_min_j) / dt_s)
        actual_aux_w = min(aux_w, aux_capacity_w)
        energy -= actual_aux_w * dt_s

        requested_out_w = battery_out_power(requested_deploy_dc_w, self.eta_discharge)
        available_out_w = max(0.0, (energy - self.energy_min_j) / dt_s)
        actual_out_w = min(requested_out_w, available_out_w)
        actual_deploy_dc_w = actual_out_w * self.eta_discharge
        deploy_saturated = requested_deploy_dc_w - actual_deploy_dc_w > 1e-9
        energy -= actual_out_w * dt_s

        source_limited_dc_w = min(requested_harvest_dc_w, mechanical_available_w)
        requested_in_w = battery_in_power(source_limited_dc_w, self.eta_charge)
        headroom_in_w = max(0.0, (self.energy_max_j - energy) / dt_s)
        actual_in_w = min(requested_in_w, headroom_in_w)
        actual_harvest_dc_w = actual_in_w / self.eta_charge
        harvest_saturated = source_limited_dc_w - actual_harvest_dc_w > 1e-9
        energy += actual_in_w * dt_s

        mechanical_rejected_w = max(0.0, mechanical_available_w - actual_harvest_dc_w)
        loss_w = (actual_out_w - actual_deploy_dc_w) + (actual_harvest_dc_w - actual_in_w)

        return LedgerPlan(
            dt_s=dt_s,
            requested_deploy_dc_w=requested_deploy_dc_w,
            actual_deploy_dc_w=actual_deploy_dc_w,
            requested_harvest_dc_w=requested_harvest_dc_w,
            actual_harvest_dc_w=actual_harvest_dc_w,
            mechanical_offered_w=mechanical_available_w,
            mechanical_rejected_w=mechanical_rejected_w,
            aux_w=actual_aux_w,
            battery_out_w=actual_out_w + actual_aux_w,
            battery_in_w=actual_in_w,
            loss_w=loss_w,
            deploy_saturated=deploy_saturated,
            harvest_saturated=harvest_saturated,
            energy_after_j=energy,
        )

    def commit(self, plan: LedgerPlan, session_time_s: float) -> LedgerPlan:
        """Apply a plan and record every ledger it touches."""
        dt = plan.dt_s
        self.energy_j = min(self.energy_max_j, max(self.energy_min_j, plan.energy_after_j))

        self.battery_out_j += plan.battery_out_w * dt
        self.battery_in_j += plan.battery_in_w * dt
        self.auxiliary_j += plan.aux_w * dt
        self.deployed_dc_j += plan.actual_deploy_dc_w * dt
        self.conversion_loss_j += plan.loss_w * dt

        harvested_dc_j = plan.actual_harvest_dc_w * dt
        self.harvested_dc_j += harvested_dc_j
        self.recharge_cumulative_j += harvested_dc_j
        self.recharge_this_lap_j += harvested_dc_j

        self.mechanical_offered_j += plan.mechanical_offered_w * dt
        self.mechanical_rejected_j += plan.mechanical_rejected_w * dt

        if plan.deploy_saturated:
            self.saturation_events.append(
                SaturationEvent(
                    session_time_s=session_time_s,
                    car_id=self.car_id,
                    kind="deploy_lower_energy_bound",
                    requested_w=plan.requested_deploy_dc_w,
                    actual_w=plan.actual_deploy_dc_w,
                    energy_j=self.energy_j,
                )
            )
        if plan.harvest_saturated:
            self.saturation_events.append(
                SaturationEvent(
                    session_time_s=session_time_s,
                    car_id=self.car_id,
                    kind="harvest_upper_energy_bound",
                    requested_w=plan.requested_harvest_dc_w,
                    actual_w=plan.actual_harvest_dc_w,
                    energy_j=self.energy_j,
                )
            )
        return plan

    def reset_lap_counters(self) -> None:
        """Reset only the per-lap regulatory counter.

        Crossing the timing line resets the per-lap recharge count. It does not
        refill the battery and it does not clear the cumulative ledger.
        """
        self.recharge_this_lap_j = 0.0

    def close_error(self) -> float:
        """Residual of the battery energy balance, in joules.

        ``E_final - (E_initial + battery_in - battery_out)``. ``battery_out``
        already includes the auxiliary draw. A non-zero residual beyond floating
        point noise means energy appeared or vanished, and the conservation test
        asserts against it directly.
        """
        expected = self.initial_energy_j + self.battery_in_j - self.battery_out_j
        return self.energy_j - expected

    def as_dict(self) -> dict[str, Any]:
        return {
            "car_id": self.car_id,
            "energy_j": self.energy_j,
            "energy_min_j": self.energy_min_j,
            "energy_max_j": self.energy_max_j,
            "eta_discharge": self.eta_discharge,
            "eta_charge": self.eta_charge,
            "recharge_cumulative_j": self.recharge_cumulative_j,
            "recharge_this_lap_j": self.recharge_this_lap_j,
            "deployed_dc_j": self.deployed_dc_j,
            "harvested_dc_j": self.harvested_dc_j,
            "mechanical_offered_j": self.mechanical_offered_j,
            "mechanical_rejected_j": self.mechanical_rejected_j,
            "auxiliary_j": self.auxiliary_j,
            "conversion_loss_j": self.conversion_loss_j,
            "battery_out_j": self.battery_out_j,
            "battery_in_j": self.battery_in_j,
            "initial_energy_j": self.initial_energy_j,
            "saturation_events": [event.as_dict() for event in self.saturation_events],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EnergyLedger:
        ledger = cls(
            car_id=payload["car_id"],
            energy_j=payload["energy_j"],
            energy_min_j=payload["energy_min_j"],
            energy_max_j=payload["energy_max_j"],
            eta_discharge=payload["eta_discharge"],
            eta_charge=payload["eta_charge"],
            initial_energy_j=payload["initial_energy_j"],
        )
        ledger.recharge_cumulative_j = payload["recharge_cumulative_j"]
        ledger.recharge_this_lap_j = payload["recharge_this_lap_j"]
        ledger.deployed_dc_j = payload["deployed_dc_j"]
        ledger.harvested_dc_j = payload["harvested_dc_j"]
        ledger.mechanical_offered_j = payload["mechanical_offered_j"]
        ledger.mechanical_rejected_j = payload["mechanical_rejected_j"]
        ledger.auxiliary_j = payload["auxiliary_j"]
        ledger.conversion_loss_j = payload["conversion_loss_j"]
        ledger.battery_out_j = payload["battery_out_j"]
        ledger.battery_in_j = payload["battery_in_j"]
        ledger.saturation_events = [SaturationEvent(**event) for event in payload["saturation_events"]]
        return ledger


__all__ = ["EnergyLedger", "LedgerPlan", "SaturationEvent"]
