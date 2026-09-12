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
  variability: Variability;
  time_limit_s: number;
}

export interface CircuitMap {
  id: string;
  name: string;
  length_m: number;
  points: [number, number][];
}

export interface Variability {
  preset: 'baseline' | 'mild' | 'training' | 'stress';
  grid_scale?: number;
  driver_scale?: number;
  vehicle_scale?: number;
  sensor_scale?: number;
  surface_scale?: number;
  wind_scale?: number;
  wetness_target?: number | null;
  weather_tau_s?: number;
  drivers?: Record<string, Record<string, number>>;
}

export interface RaceCar {
  driver_name: string;
  id: string;
  channels: Record<string, number | undefined>;
  observed_at_s: number;
  requested_profile: string;
  finish_time_s: number | null;
}

export interface RaceFrame {
  type: 'frame';
  generation: number;
  settings: RaceSettings;
  time_s: number;
  steps: number;
  status: string;
  started: boolean;
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
  | { type: 'catalogue'; circuits: Omit<CircuitMap, 'points'>[]; map: CircuitMap }
  | { type: 'map'; map: CircuitMap }
  | { type: 'error'; message: string; id: string | null }
  | { type: 'ack'; id: string };
