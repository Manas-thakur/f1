"""Surface grip multiplier from wetness, track temperature and rubbering-in.

The multiplier scales the track's reference ``mu`` (see the ``EnvironmentField``
contract: 1.0 is the dry reference). It is a **reduced model** in the sense of
``RACE_CONDITION_MODEL.md``: a product of separable factors, each monotone in
its input, clamped to ``[GRIP_FLOOR, GRIP_CEILING]``::

    g = clamp(f_wet(rain) * f_temp(T_track) * f_rubber(r), 0.3, 1.05)

* ``f_wet = 1 - (1 - WET_FLOOR) * rain``, ``rain`` in [0, 1]. Strictly below
  1 for any rainfall. Order of magnitude: wet asphalt friction is commonly
  reported at 50-70 % of dry for road tyres (e.g. Wallman and Astrom, VTI
  meddelande 911A, 2001); the exact value for racing slicks on a wet circuit
  is **not calibrated** here, so the floor carries ``synthetic_assumption``.
* ``f_temp`` is a plateau: 1.0 inside ``[T_PLATEAU_LOW, T_PLATEAU_HIGH]`` and a
  quadratic loss outside it. No track-temperature-to-grip calibration data is
  available to this project; the window and the loss coefficient are
  synthetic and are declared as such.
* ``f_rubber = 1 + RUBBER_GAIN * r``, ``r`` in [0, 1], the rubbering-in
  fraction. Synthetic; gives at most the 1.05 ceiling.

Nothing here is a tyre model; tyre compound and age live in :mod:`tyres`.
Nothing here imports learning code or reward configuration.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Parameter, VerificationStatus

_SYNTHETIC = VerificationStatus.SYNTHETIC_ASSUMPTION
_SOURCE = "synthetic:afterlap-conditions-grip-v1"

DRY_REFERENCE = Parameter(
    value=1.0,
    unit="1",
    source=_SOURCE,
    verification=_SYNTHETIC,
    note="Definition: the EnvironmentField grip multiplier is 1.0 on a dry reference surface.",
)
GRIP_FLOOR = Parameter(
    value=0.3,
    unit="1",
    source=_SOURCE,
    verification=_SYNTHETIC,
    note="Lower clamp on the multiplier; below this the reduced model is not trusted.",
)
GRIP_CEILING = Parameter(
    value=1.05,
    unit="1",
    source=_SOURCE,
    verification=_SYNTHETIC,
    note="Upper clamp; rubbering-in can add at most 5 % over the dry reference.",
)
WET_FLOOR = Parameter(
    value=0.55,
    unit="1",
    source=_SOURCE,
    verification=_SYNTHETIC,
    lower_bound=0.3,
    upper_bound=1.0,
    note=(
        "Multiplier at full rainfall. Road-tyre literature (Wallman & Astrom 2001, VTI 911A) reports "
        "wet asphalt at roughly 50-70 % of dry; not calibrated for racing slicks. Synthetic."
    ),
)
T_PLATEAU_LOW = Parameter(
    value=288.15,
    unit="K",
    source=_SOURCE,
    verification=_SYNTHETIC,
    note="Below 15 C the surface is treated as cold. No calibration data; synthetic window.",
)
T_PLATEAU_HIGH = Parameter(
    value=323.15,
    unit="K",
    source=_SOURCE,
    verification=_SYNTHETIC,
    note="Above 50 C the surface is treated as overheated. No calibration data; synthetic window.",
)
T_LOSS_PER_K2 = Parameter(
    value=2.0e-4,
    unit="1/K^2",
    source=_SOURCE,
    verification=_SYNTHETIC,
    note="Quadratic grip loss per kelvin squared outside the plateau (5 % at 15.8 K outside). Synthetic.",
)
RUBBER_GAIN = Parameter(
    value=0.05,
    unit="1",
    source=_SOURCE,
    verification=_SYNTHETIC,
    lower_bound=0.0,
    upper_bound=0.05,
    note="Maximum gain from a fully rubbered-in line. Synthetic.",
)

COEFFICIENTS: tuple[Parameter, ...] = (
    DRY_REFERENCE,
    GRIP_FLOOR,
    GRIP_CEILING,
    WET_FLOOR,
    T_PLATEAU_LOW,
    T_PLATEAU_HIGH,
    T_LOSS_PER_K2,
    RUBBER_GAIN,
)


def _unit_interval(name: str, value: float) -> float:
    if not (0.0 <= value <= 1.0):
        raise ValueError(f"{name} must lie in [0, 1], got {value}")
    return float(value)


def wetness_factor(rain_intensity: float) -> float:
    """1.0 dry, ``WET_FLOOR`` at full rainfall, linear and monotone between."""
    rain = _unit_interval("rain_intensity", rain_intensity)
    return 1.0 - (1.0 - WET_FLOOR.value) * rain


def temperature_factor(track_temperature_k: float | None) -> float:
    """Plateau at 1.0 with quadratic loss outside; unknown temperature contributes nothing."""
    if track_temperature_k is None:
        return 1.0
    if track_temperature_k < T_PLATEAU_LOW.value:
        excess = T_PLATEAU_LOW.value - track_temperature_k
    elif track_temperature_k > T_PLATEAU_HIGH.value:
        excess = track_temperature_k - T_PLATEAU_HIGH.value
    else:
        return 1.0
    return max(0.0, 1.0 - T_LOSS_PER_K2.value * excess * excess)


def rubber_factor(rubber_fraction: float) -> float:
    return 1.0 + RUBBER_GAIN.value * _unit_interval("rubber_fraction", rubber_fraction)


@dataclass(frozen=True, slots=True)
class GripBreakdown:
    """The factors behind one multiplier, for diagnostics and provenance."""

    wetness: float
    temperature: float
    rubber: float
    multiplier: float


def grip_breakdown(
    *,
    rain_intensity: float = 0.0,
    track_temperature_k: float | None = None,
    rubber_fraction: float = 0.0,
) -> GripBreakdown:
    wet = wetness_factor(rain_intensity)
    temp = temperature_factor(track_temperature_k)
    rubber = rubber_factor(rubber_fraction)
    raw = DRY_REFERENCE.value * wet * temp * rubber
    return GripBreakdown(wet, temp, rubber, min(GRIP_CEILING.value, max(GRIP_FLOOR.value, raw)))


def surface_grip_multiplier(
    *,
    rain_intensity: float = 0.0,
    track_temperature_k: float | None = None,
    rubber_fraction: float = 0.0,
) -> float:
    """Composite multiplier on the reference ``mu``; see the module docstring."""
    return grip_breakdown(
        rain_intensity=rain_intensity,
        track_temperature_k=track_temperature_k,
        rubber_fraction=rubber_fraction,
    ).multiplier


__all__ = [
    "COEFFICIENTS",
    "DRY_REFERENCE",
    "GRIP_CEILING",
    "GRIP_FLOOR",
    "RUBBER_GAIN",
    "T_LOSS_PER_K2",
    "T_PLATEAU_HIGH",
    "T_PLATEAU_LOW",
    "WET_FLOOR",
    "GripBreakdown",
    "grip_breakdown",
    "rubber_factor",
    "surface_grip_multiplier",
    "temperature_factor",
    "wetness_factor",
]
