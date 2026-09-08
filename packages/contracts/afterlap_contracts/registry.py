"""Canonical channel registry.

One authority for channel name, SI unit, display unit, plotting scale and
provenance expectation. A vendor field is mapped onto one of these names by an
explicit adapter table; an unmapped field stays raw rather than being guessed.
"""

from __future__ import annotations

from typing import Final

from pydantic import Field

from .base import Contract
from .enums import Provenance


class ChannelSpec(Contract):
    """Definition of one canonical channel."""

    name: str = Field(min_length=1)
    unit: str = Field(min_length=1, description="Internal SI unit.")
    display_unit: str = Field(min_length=1)
    display_scale: float = Field(gt=0.0, description="display_value = si_value * display_scale.")
    display_offset: float = Field(default=0.0, description="Applied after scaling, e.g. K to C.")
    family: str = Field(min_length=1)
    expected_provenance: tuple[Provenance, ...] = ()
    plot_colour_token: str = Field(min_length=1)
    lower_bound: float | None = None
    upper_bound: float | None = None
    note: str | None = None

    def to_display(self, si_value: float) -> float:
        return si_value * self.display_scale + self.display_offset

    def from_display(self, display_value: float) -> float:
        return (display_value - self.display_offset) / self.display_scale


def _spec(**kwargs: object) -> ChannelSpec:
    return ChannelSpec.model_validate(kwargs)


CHANNELS: Final[tuple[ChannelSpec, ...]] = (
    _spec(
        name="speed_mps",
        unit="m/s",
        display_unit="km/h",
        display_scale=3.6,
        family="motion",
        expected_provenance=(Provenance.MEASURED, Provenance.SIMULATED),
        plot_colour_token="--series-speed",
        lower_bound=0.0,
        upper_bound=120.0,
    ),
    _spec(
        name="acceleration_mps2",
        unit="m/s^2",
        display_unit="m/s²",
        display_scale=1.0,
        family="motion",
        expected_provenance=(Provenance.ESTIMATED, Provenance.SIMULATED),
        plot_colour_token="--series-accel",
        lower_bound=-80.0,
        upper_bound=40.0,
    ),
    _spec(
        name="progress_m",
        unit="m",
        display_unit="m",
        display_scale=1.0,
        family="motion",
        expected_provenance=(Provenance.MEASURED, Provenance.SIMULATED),
        plot_colour_token="--series-progress",
        lower_bound=0.0,
    ),
    _spec(
        name="lap_distance_m",
        unit="m",
        display_unit="m",
        display_scale=1.0,
        family="motion",
        expected_provenance=(Provenance.MEASURED, Provenance.SIMULATED),
        plot_colour_token="--series-progress",
        lower_bound=0.0,
    ),
    _spec(
        name="s_m",
        unit="m",
        display_unit="m",
        display_scale=1.0,
        family="motion",
        expected_provenance=(Provenance.MEASURED, Provenance.SIMULATED),
        plot_colour_token="--series-progress",
        lower_bound=0.0,
        note="Along-track distance within the current lap, as emitted by the simulator observation path.",
    ),
    _spec(
        name="battery_energy_j",
        unit="J",
        display_unit="MJ",
        display_scale=1e-6,
        family="electrical",
        expected_provenance=(Provenance.MEASURED, Provenance.SIMULATED, Provenance.ESTIMATED),
        plot_colour_token="--series-energy",
        lower_bound=0.0,
        note="Battery-side stored energy. Not interchangeable with the CU-K recharge ledger.",
    ),
    _spec(
        name="electrical_power_w",
        unit="W",
        display_unit="kW",
        display_scale=1e-3,
        family="electrical",
        expected_provenance=(Provenance.MEASURED, Provenance.SIMULATED),
        plot_colour_token="--series-power",
        note="Signed DC-bus power: positive deploys, negative harvests. Documented convention.",
    ),
    _spec(
        name="deploy_power_w",
        unit="W",
        display_unit="kW",
        display_scale=1e-3,
        family="electrical",
        expected_provenance=(Provenance.SIMULATED, Provenance.MEASURED),
        plot_colour_token="--series-power",
        lower_bound=0.0,
    ),
    _spec(
        name="harvest_power_w",
        unit="W",
        display_unit="kW",
        display_scale=1e-3,
        family="electrical",
        expected_provenance=(Provenance.SIMULATED, Provenance.MEASURED),
        plot_colour_token="--series-harvest",
        lower_bound=0.0,
        note="Separately named nonnegative flow; never netted against deploy without a stated convention.",
    ),
    _spec(
        name="recharge_ledger_j",
        unit="J",
        display_unit="MJ",
        display_scale=1e-6,
        family="electrical",
        expected_provenance=(Provenance.SIMULATED, Provenance.ESTIMATED),
        plot_colour_token="--series-ledger",
        lower_bound=0.0,
        note="Regulatory CU-K bus ledger, integrated at its specified bus, not battery gain.",
    ),
    _spec(
        name="battery_temperature_k",
        unit="K",
        display_unit="°C",
        display_scale=1.0,
        display_offset=-273.15,
        family="thermal",
        expected_provenance=(Provenance.MEASURED, Provenance.SIMULATED),
        plot_colour_token="--series-thermal",
        lower_bound=200.0,
        upper_bound=450.0,
    ),
    _spec(
        name="gap_ahead_s",
        unit="s",
        display_unit="s",
        display_scale=1.0,
        family="battle",
        expected_provenance=(Provenance.ESTIMATED, Provenance.SIMULATED),
        plot_colour_token="--series-gap",
        note="Derived at common progress, not by dividing distance by instantaneous speed.",
    ),
    _spec(
        name="gap_behind_s",
        unit="s",
        display_unit="s",
        display_scale=1.0,
        family="battle",
        expected_provenance=(Provenance.ESTIMATED, Provenance.SIMULATED),
        plot_colour_token="--series-gap",
    ),
    _spec(
        name="lateral_position_m",
        unit="m",
        display_unit="m",
        display_scale=1.0,
        family="geometry",
        expected_provenance=(Provenance.SIMULATED,),
        plot_colour_token="--series-lateral",
        note="Frenet lateral coordinate, positive left. Public feeds cannot supply this reliably.",
    ),
)

CHANNELS_BY_NAME: Final[dict[str, ChannelSpec]] = {c.name: c for c in CHANNELS}

CHANNEL_FAMILIES: Final[tuple[str, ...]] = tuple(sorted({c.family for c in CHANNELS}))


def channel(name: str) -> ChannelSpec:
    """Look up a canonical channel, failing loudly on an unregistered name."""
    try:
        return CHANNELS_BY_NAME[name]
    except KeyError as exc:  # pragma: no cover - defensive
        raise KeyError(
            f"unknown channel {name!r}; register it in afterlap_contracts.registry before use"
        ) from exc


def is_registered(name: str) -> bool:
    return name in CHANNELS_BY_NAME


__all__ = [
    "CHANNELS",
    "CHANNELS_BY_NAME",
    "CHANNEL_FAMILIES",
    "ChannelSpec",
    "channel",
    "is_registered",
]
