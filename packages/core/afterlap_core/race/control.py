from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from afterlap_contracts import DeploymentProfile

from ..simulation.policies import DriverAction


class DriverControl(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    mode: Literal["automatic", "direct"] = "direct"
    profile: DeploymentProfile = DeploymentProfile.NEUTRAL
    pace_scale: float = Field(default=0.94, ge=0.7, le=1)
    target_lateral_d_m: float = Field(default=0, ge=-5, le=5)
    low_drag: bool = False
    throttle: float | None = Field(default=None, ge=0, le=1)
    brake: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def complete_pedal_pair(self) -> DriverControl:
        if (self.throttle is None) != (self.brake is None):
            raise ValueError("throttle and brake must both be automatic or both be configured")
        return self

    def driver_action(self) -> DriverAction:
        return DriverAction(
            profile=self.profile,
            pace_scale=self.pace_scale,
            target_lateral_d_m=self.target_lateral_d_m,
            low_drag=self.low_drag,
            throttle=self.throttle,
            brake=self.brake,
        )
