from __future__ import annotations

import math

GRAVITY_MPS2: float = 9.80665


def drag_force(rho_kgpm3: float, cda_m2: float, speed_mps: float) -> float:

    return 0.5 * rho_kgpm3 * cda_m2 * speed_mps * speed_mps


def downforce(rho_kgpm3: float, cla_m2: float, speed_mps: float) -> float:

    return 0.5 * rho_kgpm3 * cla_m2 * speed_mps * speed_mps


def rolling_force(mass_kg: float, g_mps2: float, crr: float, grade_rad: float) -> float:

    return crr * mass_kg * g_mps2 * math.cos(grade_rad)


def grade_force(mass_kg: float, g_mps2: float, grade_rad: float) -> float:

    return mass_kg * g_mps2 * math.sin(grade_rad)


def traction_limit(mass_kg: float, g_mps2: float, mu: float, downforce_n: float) -> float:

    return mu * (mass_kg * g_mps2 + downforce_n)


def longitudinal_envelope(envelope_n: float, lateral_demand_n: float) -> float:

    remaining = envelope_n * envelope_n - lateral_demand_n * lateral_demand_n
    return math.sqrt(remaining) if remaining > 0.0 else 0.0


def tractive_force(power_w: float, speed_mps: float, max_force_n: float) -> float:

    if max_force_n < 0.0:
        raise ValueError("max_force_n must be non-negative")
    if power_w <= 0.0:
        return 0.0
    if speed_mps <= 0.0:
        return max_force_n
    return min(power_w / speed_mps, max_force_n)


def breakpoint_speed(power_w: float, max_force_n: float) -> float:

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

    if mass_kg <= 0.0:
        raise ValueError("mass must be positive")
    applied = max(-traction_limit_n, min(drive_force_n, traction_limit_n))
    return (applied - drag_n - rolling_n - grade_n) / mass_kg, applied


def battery_out_power(p_dc_deploy_w: float, eta_discharge: float) -> float:

    if not 0.0 < eta_discharge <= 1.0:
        raise ValueError("eta_discharge must be in (0, 1]")
    return p_dc_deploy_w / eta_discharge


def battery_in_power(p_dc_harvest_w: float, eta_charge: float) -> float:

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

    k = abs(curvature_inv_m)
    denominator = k - mu * downforce_factor_inv_m
    if denominator <= 0.0:
        return math.inf
    return math.sqrt(mu * g_mps2 / denominator)


def derate_factor(temperature_k: float, start_k: float, end_k: float) -> float:

    if end_k <= start_k:
        raise ValueError("derate end temperature must exceed the start temperature")
    if temperature_k <= start_k:
        return 1.0
    if temperature_k >= end_k:
        return 0.0
    return 1.0 - (temperature_k - start_k) / (end_k - start_k)


def kinetic_energy(mass_kg: float, speed_mps: float) -> float:

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
