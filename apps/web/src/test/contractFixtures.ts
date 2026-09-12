
import type {
  ExecutionEvent,
  Recommendation,
  RuleContext,
  SessionSnapshot,
  StateEstimate,
} from '@contracts';


export const SESSION_SNAPSHOT = {
  "capabilities": {
    "driver_link": "unavailable",
    "lateral_geometry": "unavailable",
    "learned_model": "unavailable",
    "notes": [
      "Synthetic fixture. Not measured telemetry, not a calibrated car, not evidence of performance."
    ],
    "own_energy": "available",
    "persistence": "available",
    "rival_energy": "unavailable",
    "rules_coverage": "degraded",
    "solver": "available"
  },
  "estimate": {
    "contributing_event_ids": [
      "fixture-001",
      "fixture-002"
    ],
    "created_at_s": 12.2,
    "cutoff_s": 12.2,
    "own_car": {
      "acceleration_mps2": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "estimated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": null,
        "unit": "m/s^2",
        "value": 0.4
      },
      "active_profile_id": "neutral",
      "battery_energy_interval": null,
      "battery_energy_j": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "simulated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": 15000.0,
        "unit": "J",
        "value": 2400000.0
      },
      "battery_temperature_k": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "simulated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": null,
        "unit": "K",
        "value": 318.0
      },
      "car_id": "car-01",
      "completed_laps": 0,
      "electrical_power_w": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "simulated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": null,
        "unit": "W",
        "value": 120000.0
      },
      "lap_distance_m": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "simulated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": null,
        "unit": "m",
        "value": 1950.0
      },
      "progress_m": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "simulated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": null,
        "unit": "m",
        "value": 1950.0
      },
      "recharge_spent_this_lap_j": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "simulated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": null,
        "unit": "J",
        "value": 2400000.0
      },
      "speed_mps": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "simulated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": 0.3,
        "unit": "m/s",
        "value": 75.0
      },
      "tyre_pace_residual_s_per_lap": null
    },
    "quality": {
      "channels": [
        {
          "age_s": 0.2,
          "car_id": "car-01",
          "channel": "battery_energy_j",
          "expected_period_s": 0.05,
          "last_source_time_s": 12.0,
          "quality": "valid",
          "reason": null
        }
      ],
      "clock_uncertainty_s": 0.02,
      "notes": [],
      "overall": "valid",
      "own_energy_capability": true,
      "residual_alarm": false
    },
    "race_context": {
      "eligibility": "eligible_detected",
      "eligibility_observed_at_s": 11.8,
      "flag_known": true,
      "flag_state": "green",
      "lap": 1,
      "position": 4,
      "remaining_distance_m": {
        "age_s": null,
        "observed_at_s": null,
        "provenance": "configured",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": null,
        "unit": "m",
        "value": 39650.0
      },
      "total_laps": 8,
      "track_length_m": 5200.0
    },
    "revision": 4,
    "rival_beliefs": [
      {
        "car_id": "car-07",
        "energy_interval_j": {
          "age_s": 0.2,
          "coverage": 0.9,
          "kind": "quantile",
          "lower": 1800000.0,
          "observed_at_s": 12.0,
          "provenance": "estimated",
          "quality": "valid",
          "unit": "J",
          "upper": 3400000.0
        },
        "energy_mean_j": {
          "age_s": 0.2,
          "observed_at_s": 12.0,
          "provenance": "estimated",
          "quality": "valid",
          "source_id": null,
          "standard_deviation": 480000.0,
          "unit": "J",
          "value": 2600000.0
        },
        "gap_m": {
          "age_s": 0.2,
          "observed_at_s": 12.0,
          "provenance": "estimated",
          "quality": "valid",
          "source_id": null,
          "standard_deviation": null,
          "unit": "m",
          "value": 48.75
        },
        "gap_s": {
          "age_s": 0.2,
          "observed_at_s": 12.0,
          "provenance": "estimated",
          "quality": "valid",
          "source_id": null,
          "standard_deviation": 0.08,
          "unit": "s",
          "value": 0.65
        },
        "intentions": {
          "attack": 0.1,
          "conserve": 0.15,
          "defend": 0.3,
          "normal": 0.45
        },
        "is_ahead": true,
        "lateral_geometry_known": false,
        "observation_age_s": 0.2,
        "pace_bias_s_per_lap": {
          "age_s": 0.2,
          "observed_at_s": 12.0,
          "provenance": "estimated",
          "quality": "valid",
          "source_id": null,
          "standard_deviation": null,
          "unit": "s",
          "value": -0.15
        },
        "relative_speed_mps": {
          "age_s": 0.2,
          "observed_at_s": 12.0,
          "provenance": "estimated",
          "quality": "valid",
          "source_id": null,
          "standard_deviation": null,
          "unit": "m/s",
          "value": -0.8
        },
        "slot": "ahead_1"
      },
      {
        "car_id": "car-07",
        "energy_interval_j": {
          "age_s": 0.2,
          "coverage": 0.9,
          "kind": "quantile",
          "lower": 1800000.0,
          "observed_at_s": 12.0,
          "provenance": "estimated",
          "quality": "valid",
          "unit": "J",
          "upper": 3400000.0
        },
        "energy_mean_j": {
          "age_s": 0.2,
          "observed_at_s": 12.0,
          "provenance": "estimated",
          "quality": "valid",
          "source_id": null,
          "standard_deviation": 480000.0,
          "unit": "J",
          "value": 2600000.0
        },
        "gap_m": {
          "age_s": 0.2,
          "observed_at_s": 12.0,
          "provenance": "estimated",
          "quality": "valid",
          "source_id": null,
          "standard_deviation": null,
          "unit": "m",
          "value": -105.0
        },
        "gap_s": {
          "age_s": 0.2,
          "observed_at_s": 12.0,
          "provenance": "estimated",
          "quality": "valid",
          "source_id": null,
          "standard_deviation": 0.08,
          "unit": "s",
          "value": -1.4
        },
        "intentions": {
          "attack": 0.1,
          "conserve": 0.15,
          "defend": 0.3,
          "normal": 0.45
        },
        "is_ahead": false,
        "lateral_geometry_known": false,
        "observation_age_s": 0.2,
        "pace_bias_s_per_lap": {
          "age_s": 0.2,
          "observed_at_s": 12.0,
          "provenance": "estimated",
          "quality": "valid",
          "source_id": null,
          "standard_deviation": null,
          "unit": "s",
          "value": -0.15
        },
        "relative_speed_mps": {
          "age_s": 0.2,
          "observed_at_s": 12.0,
          "provenance": "estimated",
          "quality": "valid",
          "source_id": null,
          "standard_deviation": null,
          "unit": "m/s",
          "value": -0.8
        },
        "slot": "behind_1"
      }
    ],
    "schema_version": "1.0",
    "session_id": "synthetic-battle-001"
  },
  "last_sequence": 100,
  "lease": {
    "expires_at_s": 130.0,
    "granted_at_s": 10.0,
    "operator_id": "engineer-1",
    "revision": 1,
    "session_id": "synthetic-battle-001"
  },
  "manifest": {
    "car_hashes": {
      "car-01": "sha256:abb29d0e2ba76d3d9f203078ec4442a416838a3b493b6ae046fc810676602ea5",
      "car-07": "sha256:abb29d0e2ba76d3d9f203078ec4442a416838a3b493b6ae046fc810676602ea5"
    },
    "created_at": "2026-09-08T12:00:00Z",
    "id": "synthetic-battle-001",
    "label": "Synthetic counterattack fixture",
    "mode": "simulation",
    "model_hash": null,
    "objective_hash": "sha256:b10f2c6ab53e39a7bef8b24a5bad7075d8bd83044b16e1c9ddca664fd25ee855",
    "ruleset_hash": "sha256:1e323a4f39ae61b15f4202eb53f79c957a26317c6632bf71d1efd1429d41acce",
    "scenario_id": "two-straight-counterattack",
    "schema_version": "1.0",
    "seed": 42,
    "source_capabilities": [
      {
        "clock_error_s": 0.02,
        "license_note": null,
        "limitations": [
          "Synthetic fixture. Not measured telemetry, not a calibrated car, not evidence of performance."
        ],
        "measured_channels": [
          "speed_mps",
          "progress_m",
          "lap_distance_m",
          "gap_ahead_s",
          "gap_behind_s",
          "battery_energy_j",
          "electrical_power_w",
          "battery_temperature_k"
        ],
        "mode": "simulation",
        "source_id": "synthetic-simulator",
        "supported_channels": [
          "speed_mps",
          "progress_m",
          "lap_distance_m",
          "gap_ahead_s",
          "gap_behind_s",
          "battery_energy_j",
          "electrical_power_w",
          "battery_temperature_k"
        ],
        "update_rates_hz": {
          "battery_energy_j": 20.0,
          "battery_temperature_k": 20.0,
          "electrical_power_w": 20.0,
          "gap_ahead_s": 20.0,
          "gap_behind_s": 20.0,
          "lap_distance_m": 20.0,
          "progress_m": 20.0,
          "speed_mps": 20.0
        }
      }
    ],
    "synthetic": true,
    "track_hash": "sha256:61ee43b3c8ac030796fe9c25cbf45393902b73a63cd71d9f9a279693d6f5f2fe"
  },
  "recommendation": {
    "action_code": "attack",
    "baseline_identity": "mpc_baseline",
    "constraint_result": {
      "checked_at_s": 12.25,
      "checker_version": "checker-v1",
      "checks": [
        {
          "at_progress_m": 2000.0,
          "at_session_time_s": null,
          "check_id": "power_ceiling",
          "detail": null,
          "limit": 350000.0,
          "margin": 30000.0,
          "observed": 320000.0,
          "references": [],
          "status": "pass",
          "unit": "W"
        },
        {
          "at_progress_m": 2100.0,
          "at_session_time_s": null,
          "check_id": "battery_energy_window",
          "detail": null,
          "limit": 0.0,
          "margin": 410000.0,
          "observed": 410000.0,
          "references": [],
          "status": "pass",
          "unit": "J"
        }
      ],
      "ruleset_hash": "sha256:1e323a4f39ae61b15f4202eb53f79c957a26317c6632bf71d1efd1429d41acce",
      "schema_version": "1.0",
      "status": "pass",
      "unresolved_conditions": []
    },
    "created_at_s": 12.25,
    "display_text": "Attack into T7, hold through attack-exit",
    "end_condition": "attack-exit checkpoint",
    "expires_at_s": 20.0,
    "id": "rec-001",
    "learned_contribution_enabled": false,
    "model_hash": null,
    "objective_version": "objective-v1",
    "observation_cutoff_s": 12.2,
    "outcomes": [
      {
        "ahead_of_rival": true,
        "checkpoint_id": "attack-exit",
        "elapsed_time_s": 2.1,
        "gap_to_reference_s": null,
        "own_energy_j": 1880000.0,
        "position": null,
        "progress_m": 2100.0
      }
    ],
    "plan_id": "plan-attack-1",
    "probabilities": [
      {
        "calibration_status": "uncalibrated",
        "checkpoint_id": "counterattack-exit",
        "event_definition": "ahead_at(checkpoint=counterattack-exit)",
        "horizon_s": null,
        "model_version": "scenario-ensemble-v1",
        "raw_frequency": 0.48,
        "sample_count": 64,
        "value": 0.48
      }
    ],
    "reason_codes": [],
    "revision": 1,
    "ruleset_hash": "sha256:1e323a4f39ae61b15f4202eb53f79c957a26317c6632bf71d1efd1429d41acce",
    "schema_version": "1.0",
    "session_id": "synthetic-battle-001",
    "state_revision": 4,
    "status": "proposed",
    "trigger": {
      "checkpoint_id": "activate-1",
      "description": "At the activation line",
      "gap_threshold_s": null,
      "kind": "checkpoint",
      "progress_m": 1900.0
    },
    "valid_from_s": 12.3
  },
  "revision": 7,
  "rule_context": {
    "active_curve_id": "baseline-speed-curve",
    "admissible_profiles": [
      "harvest",
      "conserve",
      "neutral",
      "push",
      "overtake"
    ],
    "applicable_limits": {
      "battery_energy_max_j": 4000000.0,
      "battery_energy_min_j": 0.0,
      "deployment_ceiling_w": 350000.0,
      "max_power_ramp_w_per_s": 700000.0,
      "recharge_allowance_remaining_j": 6100000.0,
      "recovery_ceiling_w": 350000.0,
      "thermal_derate_factor": 1.0
    },
    "coverage": [],
    "current_flags": [
      "green"
    ],
    "eligibility": "eligible_detected",
    "eligibility_observed_at_s": 11.8,
    "event_pack_hash": null,
    "progress_m": 1950.0,
    "resolved_at_s": 12.2,
    "ruleset_hash": "sha256:1e323a4f39ae61b15f4202eb53f79c957a26317c6632bf71d1efd1429d41acce",
    "schema_version": "1.0",
    "season_revision": "synthetic-2026-r0",
    "session_id": "synthetic-battle-001",
    "unknown_conditions": []
  },
  "schema_version": "1.0",
  "server_time": "2026-09-08T12:00:00Z",
  "session_id": "synthetic-battle-001",
  "session_time_s": 12.3,
  "status": "running"
} as unknown as SessionSnapshot;

export const STATE_ESTIMATE = {
  "contributing_event_ids": [
    "fixture-001",
    "fixture-002"
  ],
  "created_at_s": 12.2,
  "cutoff_s": 12.2,
  "own_car": {
    "acceleration_mps2": {
      "age_s": 0.2,
      "observed_at_s": 12.0,
      "provenance": "estimated",
      "quality": "valid",
      "source_id": null,
      "standard_deviation": null,
      "unit": "m/s^2",
      "value": 0.4
    },
    "active_profile_id": "neutral",
    "battery_energy_interval": null,
    "battery_energy_j": {
      "age_s": 0.2,
      "observed_at_s": 12.0,
      "provenance": "simulated",
      "quality": "valid",
      "source_id": null,
      "standard_deviation": 15000.0,
      "unit": "J",
      "value": 2400000.0
    },
    "battery_temperature_k": {
      "age_s": 0.2,
      "observed_at_s": 12.0,
      "provenance": "simulated",
      "quality": "valid",
      "source_id": null,
      "standard_deviation": null,
      "unit": "K",
      "value": 318.0
    },
    "car_id": "car-01",
    "completed_laps": 0,
    "electrical_power_w": {
      "age_s": 0.2,
      "observed_at_s": 12.0,
      "provenance": "simulated",
      "quality": "valid",
      "source_id": null,
      "standard_deviation": null,
      "unit": "W",
      "value": 120000.0
    },
    "lap_distance_m": {
      "age_s": 0.2,
      "observed_at_s": 12.0,
      "provenance": "simulated",
      "quality": "valid",
      "source_id": null,
      "standard_deviation": null,
      "unit": "m",
      "value": 1950.0
    },
    "progress_m": {
      "age_s": 0.2,
      "observed_at_s": 12.0,
      "provenance": "simulated",
      "quality": "valid",
      "source_id": null,
      "standard_deviation": null,
      "unit": "m",
      "value": 1950.0
    },
    "recharge_spent_this_lap_j": {
      "age_s": 0.2,
      "observed_at_s": 12.0,
      "provenance": "simulated",
      "quality": "valid",
      "source_id": null,
      "standard_deviation": null,
      "unit": "J",
      "value": 2400000.0
    },
    "speed_mps": {
      "age_s": 0.2,
      "observed_at_s": 12.0,
      "provenance": "simulated",
      "quality": "valid",
      "source_id": null,
      "standard_deviation": 0.3,
      "unit": "m/s",
      "value": 75.0
    },
    "tyre_pace_residual_s_per_lap": null
  },
  "quality": {
    "channels": [
      {
        "age_s": 0.2,
        "car_id": "car-01",
        "channel": "battery_energy_j",
        "expected_period_s": 0.05,
        "last_source_time_s": 12.0,
        "quality": "valid",
        "reason": null
      }
    ],
    "clock_uncertainty_s": 0.02,
    "notes": [],
    "overall": "valid",
    "own_energy_capability": true,
    "residual_alarm": false
  },
  "race_context": {
    "eligibility": "eligible_detected",
    "eligibility_observed_at_s": 11.8,
    "flag_known": true,
    "flag_state": "green",
    "lap": 1,
    "position": 4,
    "remaining_distance_m": {
      "age_s": null,
      "observed_at_s": null,
      "provenance": "configured",
      "quality": "valid",
      "source_id": null,
      "standard_deviation": null,
      "unit": "m",
      "value": 39650.0
    },
    "total_laps": 8,
    "track_length_m": 5200.0
  },
  "revision": 4,
  "rival_beliefs": [
    {
      "car_id": "car-07",
      "energy_interval_j": {
        "age_s": 0.2,
        "coverage": 0.9,
        "kind": "quantile",
        "lower": 1800000.0,
        "observed_at_s": 12.0,
        "provenance": "estimated",
        "quality": "valid",
        "unit": "J",
        "upper": 3400000.0
      },
      "energy_mean_j": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "estimated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": 480000.0,
        "unit": "J",
        "value": 2600000.0
      },
      "gap_m": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "estimated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": null,
        "unit": "m",
        "value": 48.75
      },
      "gap_s": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "estimated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": 0.08,
        "unit": "s",
        "value": 0.65
      },
      "intentions": {
        "attack": 0.1,
        "conserve": 0.15,
        "defend": 0.3,
        "normal": 0.45
      },
      "is_ahead": true,
      "lateral_geometry_known": false,
      "observation_age_s": 0.2,
      "pace_bias_s_per_lap": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "estimated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": null,
        "unit": "s",
        "value": -0.15
      },
      "relative_speed_mps": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "estimated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": null,
        "unit": "m/s",
        "value": -0.8
      },
      "slot": "ahead_1"
    },
    {
      "car_id": "car-07",
      "energy_interval_j": {
        "age_s": 0.2,
        "coverage": 0.9,
        "kind": "quantile",
        "lower": 1800000.0,
        "observed_at_s": 12.0,
        "provenance": "estimated",
        "quality": "valid",
        "unit": "J",
        "upper": 3400000.0
      },
      "energy_mean_j": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "estimated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": 480000.0,
        "unit": "J",
        "value": 2600000.0
      },
      "gap_m": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "estimated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": null,
        "unit": "m",
        "value": -105.0
      },
      "gap_s": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "estimated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": 0.08,
        "unit": "s",
        "value": -1.4
      },
      "intentions": {
        "attack": 0.1,
        "conserve": 0.15,
        "defend": 0.3,
        "normal": 0.45
      },
      "is_ahead": false,
      "lateral_geometry_known": false,
      "observation_age_s": 0.2,
      "pace_bias_s_per_lap": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "estimated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": null,
        "unit": "s",
        "value": -0.15
      },
      "relative_speed_mps": {
        "age_s": 0.2,
        "observed_at_s": 12.0,
        "provenance": "estimated",
        "quality": "valid",
        "source_id": null,
        "standard_deviation": null,
        "unit": "m/s",
        "value": -0.8
      },
      "slot": "behind_1"
    }
  ],
  "schema_version": "1.0",
  "session_id": "synthetic-battle-001"
} as unknown as StateEstimate;

export const RECOMMENDATION = {
  "action_code": "attack",
  "baseline_identity": "mpc_baseline",
  "constraint_result": {
    "checked_at_s": 12.25,
    "checker_version": "checker-v1",
    "checks": [
      {
        "at_progress_m": 2000.0,
        "at_session_time_s": null,
        "check_id": "power_ceiling",
        "detail": null,
        "limit": 350000.0,
        "margin": 30000.0,
        "observed": 320000.0,
        "references": [],
        "status": "pass",
        "unit": "W"
      },
      {
        "at_progress_m": 2100.0,
        "at_session_time_s": null,
        "check_id": "battery_energy_window",
        "detail": null,
        "limit": 0.0,
        "margin": 410000.0,
        "observed": 410000.0,
        "references": [],
        "status": "pass",
        "unit": "J"
      }
    ],
    "ruleset_hash": "sha256:1e323a4f39ae61b15f4202eb53f79c957a26317c6632bf71d1efd1429d41acce",
    "schema_version": "1.0",
    "status": "pass",
    "unresolved_conditions": []
  },
  "created_at_s": 12.25,
  "display_text": "Attack into T7, hold through attack-exit",
  "end_condition": "attack-exit checkpoint",
  "expires_at_s": 20.0,
  "id": "rec-001",
  "learned_contribution_enabled": false,
  "model_hash": null,
  "objective_version": "objective-v1",
  "observation_cutoff_s": 12.2,
  "outcomes": [
    {
      "ahead_of_rival": true,
      "checkpoint_id": "attack-exit",
      "elapsed_time_s": 2.1,
      "gap_to_reference_s": null,
      "own_energy_j": 1880000.0,
      "position": null,
      "progress_m": 2100.0
    }
  ],
  "plan_id": "plan-attack-1",
  "probabilities": [
    {
      "calibration_status": "uncalibrated",
      "checkpoint_id": "counterattack-exit",
      "event_definition": "ahead_at(checkpoint=counterattack-exit)",
      "horizon_s": null,
      "model_version": "scenario-ensemble-v1",
      "raw_frequency": 0.48,
      "sample_count": 64,
      "value": 0.48
    }
  ],
  "reason_codes": [],
  "revision": 1,
  "ruleset_hash": "sha256:1e323a4f39ae61b15f4202eb53f79c957a26317c6632bf71d1efd1429d41acce",
  "schema_version": "1.0",
  "session_id": "synthetic-battle-001",
  "state_revision": 4,
  "status": "proposed",
  "trigger": {
    "checkpoint_id": "activate-1",
    "description": "At the activation line",
    "gap_threshold_s": null,
    "kind": "checkpoint",
    "progress_m": 1900.0
  },
  "valid_from_s": 12.3
} as unknown as Recommendation;

export const RULE_CONTEXT = {
  "active_curve_id": "baseline-speed-curve",
  "admissible_profiles": [
    "harvest",
    "conserve",
    "neutral",
    "push",
    "overtake"
  ],
  "applicable_limits": {
    "battery_energy_max_j": 4000000.0,
    "battery_energy_min_j": 0.0,
    "deployment_ceiling_w": 350000.0,
    "max_power_ramp_w_per_s": 700000.0,
    "recharge_allowance_remaining_j": 6100000.0,
    "recovery_ceiling_w": 350000.0,
    "thermal_derate_factor": 1.0
  },
  "coverage": [],
  "current_flags": [
    "green"
  ],
  "eligibility": "eligible_detected",
  "eligibility_observed_at_s": 11.8,
  "event_pack_hash": null,
  "progress_m": 1950.0,
  "resolved_at_s": 12.2,
  "ruleset_hash": "sha256:1e323a4f39ae61b15f4202eb53f79c957a26317c6632bf71d1efd1429d41acce",
  "schema_version": "1.0",
  "season_revision": "synthetic-2026-r0",
  "session_id": "synthetic-battle-001",
  "unknown_conditions": []
} as unknown as RuleContext;

export const EXECUTION_EVENT = {
  "delay_from_communication_s": 0.5,
  "end_time_s": null,
  "evidence_event_ids": [
    "fixture-010"
  ],
  "id": "exec-001",
  "match_status": "matched",
  "observed_profile_id": "overtake",
  "recommendation_id": "rec-001",
  "schema_version": "1.0",
  "sequence": 45,
  "session_id": "synthetic-battle-001",
  "source": "simulated",
  "start_time_s": 13.1
} as unknown as ExecutionEvent;
