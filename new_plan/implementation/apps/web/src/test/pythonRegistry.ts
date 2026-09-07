/**
 * Snapshot of `afterlap_contracts.registry.CHANNELS`, generated from Python.
 *
 * The TypeScript registry in src/contracts/channels.ts must agree with this
 * exactly. A drift test compares them; if this file changes, the mirror is out
 * of date, not the test.
 */
export interface PythonChannelRow {
  readonly name: string;
  readonly unit: string;
  readonly display_unit: string;
  readonly display_scale: number;
  readonly display_offset: number;
  readonly family: string;
  readonly plot_colour_token: string;
  readonly expected_provenance: readonly string[];
  readonly lower_bound: number | null;
  readonly upper_bound: number | null;
}

export const PYTHON_CHANNELS: readonly PythonChannelRow[] = [
  {
    "name": "speed_mps",
    "unit": "m/s",
    "display_unit": "km/h",
    "display_scale": 3.6,
    "display_offset": 0.0,
    "family": "motion",
    "plot_colour_token": "--series-speed",
    "expected_provenance": [
      "measured",
      "simulated"
    ],
    "lower_bound": 0.0,
    "upper_bound": 120.0
  },
  {
    "name": "acceleration_mps2",
    "unit": "m/s^2",
    "display_unit": "m/s\u00b2",
    "display_scale": 1.0,
    "display_offset": 0.0,
    "family": "motion",
    "plot_colour_token": "--series-accel",
    "expected_provenance": [
      "estimated",
      "simulated"
    ],
    "lower_bound": -80.0,
    "upper_bound": 40.0
  },
  {
    "name": "progress_m",
    "unit": "m",
    "display_unit": "m",
    "display_scale": 1.0,
    "display_offset": 0.0,
    "family": "motion",
    "plot_colour_token": "--series-progress",
    "expected_provenance": [
      "measured",
      "simulated"
    ],
    "lower_bound": 0.0,
    "upper_bound": null
  },
  {
    "name": "lap_distance_m",
    "unit": "m",
    "display_unit": "m",
    "display_scale": 1.0,
    "display_offset": 0.0,
    "family": "motion",
    "plot_colour_token": "--series-progress",
    "expected_provenance": [
      "measured",
      "simulated"
    ],
    "lower_bound": 0.0,
    "upper_bound": null
  },
  {
    "name": "battery_energy_j",
    "unit": "J",
    "display_unit": "MJ",
    "display_scale": 1e-06,
    "display_offset": 0.0,
    "family": "electrical",
    "plot_colour_token": "--series-energy",
    "expected_provenance": [
      "measured",
      "simulated",
      "estimated"
    ],
    "lower_bound": 0.0,
    "upper_bound": null
  },
  {
    "name": "electrical_power_w",
    "unit": "W",
    "display_unit": "kW",
    "display_scale": 0.001,
    "display_offset": 0.0,
    "family": "electrical",
    "plot_colour_token": "--series-power",
    "expected_provenance": [
      "measured",
      "simulated"
    ],
    "lower_bound": null,
    "upper_bound": null
  },
  {
    "name": "deploy_power_w",
    "unit": "W",
    "display_unit": "kW",
    "display_scale": 0.001,
    "display_offset": 0.0,
    "family": "electrical",
    "plot_colour_token": "--series-power",
    "expected_provenance": [
      "simulated",
      "measured"
    ],
    "lower_bound": 0.0,
    "upper_bound": null
  },
  {
    "name": "harvest_power_w",
    "unit": "W",
    "display_unit": "kW",
    "display_scale": 0.001,
    "display_offset": 0.0,
    "family": "electrical",
    "plot_colour_token": "--series-harvest",
    "expected_provenance": [
      "simulated",
      "measured"
    ],
    "lower_bound": 0.0,
    "upper_bound": null
  },
  {
    "name": "recharge_ledger_j",
    "unit": "J",
    "display_unit": "MJ",
    "display_scale": 1e-06,
    "display_offset": 0.0,
    "family": "electrical",
    "plot_colour_token": "--series-ledger",
    "expected_provenance": [
      "simulated",
      "estimated"
    ],
    "lower_bound": 0.0,
    "upper_bound": null
  },
  {
    "name": "battery_temperature_k",
    "unit": "K",
    "display_unit": "\u00b0C",
    "display_scale": 1.0,
    "display_offset": -273.15,
    "family": "thermal",
    "plot_colour_token": "--series-thermal",
    "expected_provenance": [
      "measured",
      "simulated"
    ],
    "lower_bound": 200.0,
    "upper_bound": 450.0
  },
  {
    "name": "gap_ahead_s",
    "unit": "s",
    "display_unit": "s",
    "display_scale": 1.0,
    "display_offset": 0.0,
    "family": "battle",
    "plot_colour_token": "--series-gap",
    "expected_provenance": [
      "estimated",
      "simulated"
    ],
    "lower_bound": null,
    "upper_bound": null
  },
  {
    "name": "gap_behind_s",
    "unit": "s",
    "display_unit": "s",
    "display_scale": 1.0,
    "display_offset": 0.0,
    "family": "battle",
    "plot_colour_token": "--series-gap",
    "expected_provenance": [
      "estimated",
      "simulated"
    ],
    "lower_bound": null,
    "upper_bound": null
  },
  {
    "name": "lateral_position_m",
    "unit": "m",
    "display_unit": "m",
    "display_scale": 1.0,
    "display_offset": 0.0,
    "family": "geometry",
    "plot_colour_token": "--series-lateral",
    "expected_provenance": [
      "simulated"
    ],
    "lower_bound": null,
    "upper_bound": null
  }
];
