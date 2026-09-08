"""Planner tuning documents.

The planner reads two configurations and keeps them strictly separate:

* ``configs/objectives/objective-v1.yaml`` — the **frozen, coordinator-owned**
  trade-off. Loaded by :mod:`afterlap_core.planning.objective`. Nothing in this
  module may restate one of its coefficients.
* ``configs/planning/planner-v1.yaml`` — horizons, bounded candidate and
  scenario counts, the smooth surrogate coefficients and the execution-timing
  model. That is what this module loads.

Every physical number carries a unit, a source and a verification status, and
every shipped value is ``synthetic_assumption``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from afterlap_contracts import RivalIntention

from ..config import ConfigDocument, Parameter, load_config
from ..paths import Paths

__all__ = [
    "BudgetSettings",
    "ExecutionSettings",
    "HorizonSettings",
    "PlannerConfig",
    "ScenarioSettings",
    "SolverSettings",
    "SurrogateSettings",
    "load_planner_config",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HorizonSettings(_Frozen):
    """Where the explicit horizon ends and the continuation begins."""

    detailed_horizon_s: Parameter
    min_segment_length_m: Parameter
    max_segments: int = Field(ge=1, le=12)
    continuation_distance_scale_m: Parameter


class BudgetSettings(_Frozen):
    """Bounded candidate, scenario and re-simulation budgets.

    These are the numbers that decide the latency/coverage trade. They are
    reported with every decision so a lower resolution can never be presented as
    the same confidence level.
    """

    max_candidates: int = Field(ge=1, le=32)
    max_scenarios: int = Field(ge=1, le=64)
    rollout_finalists: int = Field(ge=1, le=16)
    rollout_scenarios: int = Field(ge=1, le=32)
    rollout_step_s: Parameter
    rollout_horizon_s: Parameter
    estimate_max_age_s: Parameter


class ExecutionSettings(_Frozen):
    """The human execution model: lead time, instruction window, validity."""

    driver_reaction_time_s: Parameter
    instruction_lead_time_s: Parameter
    instruction_execution_window_s: Parameter
    recommendation_validity_s: Parameter

    @model_validator(mode="after")
    def _lead_covers_reaction(self) -> ExecutionSettings:
        if self.instruction_lead_time_s.value < self.driver_reaction_time_s.value:
            raise ValueError(
                "instruction_lead_time_s is shorter than the driver reaction time; "
                "no plan built from this configuration could ever be executed"
            )
        return self


class SurrogateSettings(_Frozen):
    """Coefficients of the smooth model used inside the continuous solver."""

    air_density_kgpm3: Parameter
    drag_area_m2: Parameter
    drivetrain_efficiency: Parameter
    charge_efficiency: Parameter
    harvest_opportunity_coefficient: Parameter
    regen_availability: Parameter
    max_harvest_power_w: Parameter
    min_speed_mps: Parameter
    gap_logistic_scale_s: Parameter
    position_persistence: Parameter
    counterattack_rate_s_per_j: Parameter
    counterattack_energy_scale_j: Parameter

    @property
    def drag_constant_kg_per_m(self) -> float:
        """``k = 0.5 * rho * CdA``, so that ``F_drag = k v^2`` and ``P_drag = k v^3``."""
        return 0.5 * float(self.air_density_kgpm3.value) * float(self.drag_area_m2.value)


class ScenarioSettings(_Frozen):
    """Deterministic quadrature over the rival belief."""

    energy_quantiles: tuple[float, ...] = Field(min_length=1)
    energy_quantile_weights: tuple[float, ...] = Field(min_length=1)
    unknown_energy_widening: float = Field(ge=0.0, le=1.0)
    max_intentions: int = Field(ge=1, le=4)
    interval_coverage_widening: Parameter
    intention_pace_gain_s: dict[str, Parameter]

    @model_validator(mode="after")
    def _consistent_quadrature(self) -> ScenarioSettings:
        if len(self.energy_quantiles) != len(self.energy_quantile_weights):
            raise ValueError("each energy quantile needs exactly one weight")
        if any(not 0.0 <= q <= 1.0 for q in self.energy_quantiles):
            raise ValueError("energy quantiles must lie in [0, 1]")
        total = sum(self.energy_quantile_weights)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"energy quantile weights must sum to 1.0, got {total}")
        missing = {mode.value for mode in RivalIntention} - set(self.intention_pace_gain_s)
        if missing:
            raise ValueError(f"intention_pace_gain_s is missing modes {sorted(missing)}")
        return self

    def pace_gain_s(self, intention: RivalIntention) -> float:
        return float(self.intention_pace_gain_s[intention.value].value)


class SolverSettings(_Frozen):
    """IPOPT settings. See handoffs/decisions.md D-02 for why IPOPT and not acados."""

    max_iterations: int = Field(ge=1, le=5000)
    tolerance: float = Field(gt=0.0)
    print_level: int = Field(ge=0, le=12)


class PlannerConfig(ConfigDocument):
    """The complete planner tuning document."""

    horizon: HorizonSettings
    budgets: BudgetSettings
    execution: ExecutionSettings
    surrogate: SurrogateSettings
    scenarios: ScenarioSettings
    solver: SolverSettings


@lru_cache(maxsize=8)
def _load_cached(config_id: str, root: str | None) -> PlannerConfig:
    paths = None if root is None else Paths.default(Path(root))
    return PlannerConfig.model_validate(load_config("planning", config_id, paths))


def load_planner_config(config_id: str = "planner-v1", paths: Paths | None = None) -> PlannerConfig:
    """Load ``configs/planning/<config_id>.yaml``.

    The result is cached because the planner is called many times a second and
    the document is immutable.
    """
    return _load_cached(config_id, None if paths is None else str(paths.root))
