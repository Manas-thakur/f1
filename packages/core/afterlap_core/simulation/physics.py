"""Pure float64 physics kernels.

Every function here is a total function of its arguments: no globals, no state,
no configuration lookup. That is what makes them independently testable against
hand-computed numbers, which ``tests/numerics/test_physics.py`` does.

Reference equations are the ones in ``simulation/NUMERICS_AND_VALIDATION.md``.
Sign conventions used throughout:

* ``v`` is speed along the track tangent in m/s and is non-negative in the
  supported operating range; reverse motion is not modelled.
* A *force* returned by ``drag_force``/``rolling_force`` is the magnitude of a
  resistance, always non-negative. ``grade_force`` is signed: positive means the
  car is climbing and the component opposes motion.
* Power is in watts at the bus named by the argument. ``p_dc_*`` quantities live
  on the DC bus; ``battery_*`` quantities live at the battery terminal. The two
  are never added together.
"""

from __future__ import annotations

import math

GRAVITY_MPS2: float = 9.80665
"""Standard gravity. Fixed constant, not a fitted parameter."""


def drag_force(rho_kgpm3: float, cda_m2: float, speed_mps: float) -> float:
    """``F_drag = 0.5 * rho * CdA * v^2`` in newtons.

    ``speed_mps`` is air speed; the caller adds any wind component before the
    call so that wake/wind models stay outside this kernel.
    """
    return 0.5 * rho_kgpm3 * cda_m2 * speed_mps * speed_mps


def downforce(rho_kgpm3: float, cla_m2: float, speed_mps: float) -> float:
    """Aerodynamic vertical load ``0.5 * rho * ClA * v^2`` in newtons."""
    return 0.5 * rho_kgpm3 * cla_m2 * speed_mps * speed_mps


def rolling_force(mass_kg: float, g_mps2: float, crr: float, grade_rad: float) -> float:
    """Rolling resistance against the normal load on a slope.

    ``F_roll = crr * m * g * cos(grade)``. Aerodynamic load is deliberately not
    included here: it is added by the caller through ``traction_limit`` where it
    belongs, so the rolling coefficient stays identifiable.
    """
    return crr * mass_kg * g_mps2 * math.cos(grade_rad)


def grade_force(mass_kg: float, g_mps2: float, grade_rad: float) -> float:
    """``F_grade = m * g * sin(grade)``; positive when climbing."""
    return mass_kg * g_mps2 * math.sin(grade_rad)


def traction_limit(mass_kg: float, g_mps2: float, mu: float, downforce_n: float) -> float:
    """Total tyre force envelope ``mu * (m*g + F_down)`` in newtons.

    This is the combined longitudinal/lateral budget: the friction-ellipse split
    is done by :func:`longitudinal_envelope`.
    """
    return mu * (mass_kg * g_mps2 + downforce_n)


def longitudinal_envelope(envelope_n: float, lateral_demand_n: float) -> float:
    """Longitudinal force still available once lateral demand is spent.

    Circular friction ellipse: ``F_long = sqrt(F_env^2 - F_lat^2)``, clamped at
    zero when the corner already consumes the whole envelope.
    """
    remaining = envelope_n * envelope_n - lateral_demand_n * lateral_demand_n
    return math.sqrt(remaining) if remaining > 0.0 else 0.0


def tractive_force(power_w: float, speed_mps: float, max_force_n: float) -> float:
    """Drive force from shaft power with a torque-limited low-speed branch.

    ``P / v`` diverges as ``v -> 0``. Below the breakpoint speed
    ``v_b = power_w / max_force_n`` the powertrain is torque limited, so the
    force is capped at ``max_force_n`` instead. The function is therefore
    continuous at ``v_b`` and finite at ``v = 0``.
    """
    if max_force_n < 0.0:
        raise ValueError("max_force_n must be non-negative")
    if speed_mps <= 0.0:
        return max_force_n
    return min(power_w / speed_mps, max_force_n)


def breakpoint_speed(power_w: float, max_force_n: float) -> float:
    """Speed at which the torque limit hands over to the power limit."""
    if max_force_n <= 0.0:
        return math.inf
    return power_w / max_force_n


def longitudinal_acceleration(
    mass_kg: float,
    drive_force_n: float,
    drag_n: float,
    rolling_n: float,
    grade_n: float,
    traction_limit_n: float,
) -> tuple[float, float]:
    """``a = (F_drive - F_drag - F_roll - F_grade) / m`` in m/s^2.

    The traction limit is applied to ``drive_force_n`` **before** the division,
    so an infeasible drive force can never be integrated into velocity. Returns
    ``(acceleration, applied_drive_force)`` so the caller can log the clamp.
    """
    if mass_kg <= 0.0:
        raise ValueError("mass must be positive")
    applied = max(-traction_limit_n, min(drive_force_n, traction_limit_n))
    return (applied - drag_n - rolling_n - grade_n) / mass_kg, applied


def battery_out_power(p_dc_deploy_w: float, eta_discharge: float) -> float:
    """Battery terminal power required to put ``p_dc_deploy_w`` on the DC bus."""
    if not 0.0 < eta_discharge <= 1.0:
        raise ValueError("eta_discharge must be in (0, 1]")
    return p_dc_deploy_w / eta_discharge


def battery_in_power(p_dc_harvest_w: float, eta_charge: float) -> float:
    """Battery terminal power gained from ``p_dc_harvest_w`` on the DC bus."""
    if not 0.0 < eta_charge <= 1.0:
        raise ValueError("eta_charge must be in (0, 1]")
    return eta_charge * p_dc_harvest_w


def thermal_step(
    temperature_k: float,
    c_th_j_per_k: float,
    loss_power_w: float,
    h_w_per_k: float,
    ambient_k: float,
    dt_s: float,
) -> float:
    """Advance ``C_th dT/dt = P_loss - h (T - T_ambient)`` by ``dt_s``.

    The exact solution of this linear ODE is used rather than an Euler update,
    so the step is unconditionally stable and the result is independent of the
    integration resolution. With ``T_inf = T_ambient + P_loss / h``::

        T(t + dt) = T_inf + (T(t) - T_inf) * exp(-h * dt / C_th)

    When ``h == 0`` the model degenerates to pure accumulation
    ``T + P_loss * dt / C_th``.
    """
    if c_th_j_per_k <= 0.0:
        raise ValueError("thermal capacity must be positive")
    if h_w_per_k < 0.0:
        raise ValueError("heat transfer coefficient must be non-negative")
    if h_w_per_k == 0.0:
        return temperature_k + loss_power_w * dt_s / c_th_j_per_k
    steady_state = ambient_k + loss_power_w / h_w_per_k
    decay = math.exp(-h_w_per_k * dt_s / c_th_j_per_k)
    return steady_state + (temperature_k - steady_state) * decay


def max_lateral_speed(
    curvature_inv_m: float,
    mu: float,
    g_mps2: float,
    downforce_factor_inv_m: float,
) -> float:
    """Highest speed that keeps a constant-radius corner inside the tyre envelope.

    With ``F_lat = m v^2 |k|`` and ``F_avail = mu (m g + 0.5 rho ClA v^2)``,
    writing ``downforce_factor_inv_m = 0.5 rho ClA / m`` (units 1/m) gives::

        v^2 (|k| - mu * downforce_factor) = mu * g

    Returns ``inf`` when downforce alone satisfies the demand at any speed, i.e.
    the corner is not speed limiting in this reduced model.
    """
    k = abs(curvature_inv_m)
    denominator = k - mu * downforce_factor_inv_m
    if denominator <= 0.0:
        return math.inf
    return math.sqrt(mu * g_mps2 / denominator)


def derate_factor(temperature_k: float, start_k: float, end_k: float) -> float:
    """Linear electrical derate ramp between ``start_k`` and ``end_k``.

    Returns 1.0 below ``start_k`` and 0.0 at or above ``end_k``. A reduced model
    ramp, not a measured cell characteristic.
    """
    if end_k <= start_k:
        raise ValueError("derate end temperature must exceed the start temperature")
    if temperature_k <= start_k:
        return 1.0
    if temperature_k >= end_k:
        return 0.0
    return 1.0 - (temperature_k - start_k) / (end_k - start_k)


def kinetic_energy(mass_kg: float, speed_mps: float) -> float:
    """``0.5 m v^2`` in joules."""
    return 0.5 * mass_kg * speed_mps * speed_mps


__all__ = [
    "GRAVITY_MPS2",
    "battery_in_power",
    "battery_out_power",
    "breakpoint_speed",
    "derate_factor",
    "downforce",
    "drag_force",
    "grade_force",
    "kinetic_energy",
    "longitudinal_acceleration",
    "longitudinal_envelope",
    "max_lateral_speed",
    "rolling_force",
    "thermal_step",
    "traction_limit",
    "tractive_force",
]
