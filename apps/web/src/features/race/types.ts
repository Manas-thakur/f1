export interface RaceSettings {
  circuit: string;
  seed: number;
  cars: number;
  laps: number;
  dt_s: number;
  wetness: number;
  temperature_k: number;
  wind_mps: number;
  wake: boolean;
  contact_mode: 'ignore' | 'terminate';
  variability: { preset: 'baseline' | 'mild' | 'training' | 'stress' };
  racing_line: RacingLineSettings;
  time_limit_s: number;
}

export interface RacingLineSettings {
  enabled: boolean;
  corner_strength: number;
  randomness: number;
  wander_m: number;
  lookahead_m: number;
  smoothing_m: number;
  overtake_in_corners: boolean;
}

export interface CircuitMap {
  id: string;
  name: string;
  length_m: number;
  points: [number, number][];
}

export interface LapPreset {
  id: string;
  default_laps: number;
  label: string;
  source_url: string;
}

export type CircuitSummary = Omit<CircuitMap, 'points'> & { lap_presets: LapPreset[] };

export interface RaceCar {
  id: string;
  channels: Record<string, number | undefined>;
  observed_at_s: number;
  requested_profile: string;
  active_profile?: string | null;
  battery_window_j?: [number, number];
  energy_laps?: { lap: number; deployed_j: number; recharged_j: number; boost_s: number }[];
  finish_time_s: number | null;
}

export interface RaceFrame {
  type: 'frame';
  generation: number;
  settings: RaceSettings;
  time_s: number;
  steps: number;
  status: string;
  failure: string | null;
  cars: RaceCar[];
  requested_rate: number;
  actual_rate: number;
  playback_rate?: number;
  has_checkpoint: boolean;
  circuit_map: CircuitMap;
  events: {
    kind: string;
    overtaking_car_id: string;
    overtaken_car_id: string;
    session_time_s: number;
  }[];
}

export type Message =
  | RaceFrame
  | { type: 'catalogue'; circuits: CircuitSummary[]; map: CircuitMap }
  | { type: 'map'; map: CircuitMap }
  | { type: 'error'; message: string; id: string | null }
  | { type: 'ack'; id: string };
