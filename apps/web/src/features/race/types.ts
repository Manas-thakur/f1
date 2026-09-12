export interface RaceSettings {
  circuit: string;
  seed: number;
  cars: number;
  laps: number;
  dt_s: number;
  wetness: number;
  weather: 'sunny' | 'rainy';
  temperature_k: number;
  wind_mps: number;
  wake: boolean;
  contact_mode: 'ignore' | 'terminate';
  variability: { preset: 'baseline' | 'mild' | 'training' | 'stress' };
  storyline: {
    enabled: boolean;
    pit_stops: boolean;
    tyre_wear_scale: number;
    event_interval_min_s: number;
    event_interval_max_s: number;
    event_duration_min_s: number;
    event_duration_max_s: number;
  };
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
  qualifying_position: number;
  storyline: string;
  tyres: {
    compound: 'hard' | 'medium' | 'soft';
    condition: number;
    grip: number;
    sidewall: string;
    phase: 'track' | 'entry' | 'service' | 'exit';
    requested: boolean;
    service_duration_s: number;
    service_remaining_s: number;
    box_progress_m: number;
    release_waiting: boolean;
    stops: number;
    used_compounds: ('hard' | 'medium' | 'soft')[];
    visual_lateral_m: number;
  };
  classified: boolean;
  regulation_status: string;
  points: number;
}

export interface BoostEvaluation {
  true_positive: number;
  false_positive: number;
  true_negative: number;
  false_negative: number;
  accuracy: number | null;
  precision: number | null;
  recall: number | null;
}

export interface RaceEvent {
  kind: string;
  session_time_s: number;
  car_id?: string;
  mode?: string;
  compound?: string;
  duration_s?: number;
  overtaking_car_id?: string;
  overtaken_car_id?: string;
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
  events: RaceEvent[];
  boost_evaluation: BoostEvaluation;
  regulations: {
    name: string;
    effective_issue_dates: Record<string, string>;
    sources: Record<string, string>;
    enforced: Record<string, string | number>;
    session_limits: Record<string, string | number>;
    limitations: string;
  };
}

export type Message =
  | RaceFrame
  | { type: 'catalogue'; circuits: CircuitSummary[]; map: CircuitMap }
  | { type: 'map'; map: CircuitMap }
  | { type: 'error'; message: string; id: string | null }
  | { type: 'ack'; id: string };
