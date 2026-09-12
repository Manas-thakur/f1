from pydantic import BaseModel, ConfigDict, Field


class RaceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    circuit: str = Field(default="silverstone", pattern=r"^[a-z0-9-]+$")
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    cars: int = Field(default=20, ge=1, le=20)
    laps: int = Field(default=3, ge=1, le=80)
    dt_s: float = Field(default=0.01, ge=0.005, le=0.02)
    wetness: float = Field(default=0.0, ge=0.0, le=1.0)
    temperature_k: float = Field(default=303.15, ge=273.15, le=323.15)
    wind_mps: float = Field(default=0.0, ge=-20, le=20)
    wake: bool = True
    time_limit_s: float = Field(default=1800, ge=1, le=14400)
