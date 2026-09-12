import { energyMode } from '../race/energyStatus';
import type { RaceCar, RaceFrame } from '../race/types';

export const STAGE_WIDTH = 800;
export const STAGE_HEIGHT = 480;
export const SPEED_SCALE_KPH = 360;
export const POWER_SCALE_KW = 350;
export const LATERAL_LIMIT_M = 5;
export const RECHARGE_ALLOWANCE_MJ = 8.5;

export interface GapReadout {
  id: string;
  position: number;
  gap_s: number | undefined;
}

export interface CarReadout {
  id: string;
  present: boolean;
  position: number | undefined;
  field: number;
  lap: number | undefined;
  laps: number;
  finished: boolean;
  lapFraction: number | undefined;
  speed_kph: number | undefined;
  power_kw: number | undefined;
  throttle: number | undefined;
  brake: number | undefined;
  energy_mj: number | undefined;
  energy_percent: number | undefined;
  deployed_lap_mj: number | undefined;
  recharged_lap_mj: number | undefined;
  boost_lap_s: number | undefined;
  mode: string;
  profile: string;
  grip: number | undefined;
  battery_c: number | undefined;
  lateral_m: number | undefined;
  acceleration_mps2: number | undefined;
  ahead: GapReadout | undefined;
  behind: GapReadout | undefined;
}

export function fixed(value: number | undefined, digits = 1) {
  return value === undefined || !Number.isFinite(value) ? '--' : value.toFixed(digits);
}

export function ratioPercent(value: number | undefined) {
  return value === undefined || !Number.isFinite(value)
    ? '--' : `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

export function clamp01(value: number | undefined) {
  return value === undefined || !Number.isFinite(value) ? 0 : Math.max(0, Math.min(1, value));
}

function scaled(value: number | undefined, scale: number) {
  return value === undefined || !Number.isFinite(value) ? undefined : value / scale;
}

function gapTo(own: RaceCar, other: RaceCar | undefined, index: number): GapReadout | undefined {
  if (!other) {
    return undefined;
  }
  const ownProgress = own.channels['progress_m'];
  const otherProgress = other.channels['progress_m'];
  const speed = own.channels['speed_mps'];
  const separated = ownProgress !== undefined && otherProgress !== undefined
    && speed !== undefined && speed > 1;
  return {
    id: other.id,
    position: index + 1,
    gap_s: separated ? Math.abs(otherProgress - ownProgress) / speed : undefined,
  };
}

function stateOfCharge(car: RaceCar) {
  const energy = car.channels['battery_energy_j'];
  const window = car.battery_window_j;
  if (energy === undefined || !window || window[1] <= window[0]) {
    return undefined;
  }
  return Math.max(0, Math.min(1, (energy - window[0]) / (window[1] - window[0])));
}

export function readout(frame: RaceFrame | null, carId: string): CarReadout {
  const index = frame?.cars.findIndex((item) => item.id === carId) ?? -1;
  const car = index >= 0 ? frame?.cars[index] : undefined;
  const laps = frame?.settings.laps ?? 0;
  if (!frame || !car || index < 0) {
    return {
      id: carId, present: false, position: undefined, field: frame?.cars.length ?? 0,
      lap: undefined, laps, finished: false, lapFraction: undefined, speed_kph: undefined,
      power_kw: undefined, throttle: undefined, brake: undefined, energy_mj: undefined,
      energy_percent: undefined, deployed_lap_mj: undefined, recharged_lap_mj: undefined,
      boost_lap_s: undefined, mode: 'UNAVAILABLE', profile: 'UNAVAILABLE', grip: undefined,
      battery_c: undefined, lateral_m: undefined, acceleration_mps2: undefined,
      ahead: undefined, behind: undefined,
    };
  }
  const channels = car.channels;
  const finished = car.finish_time_s !== null && car.finish_time_s !== undefined;
  const completed = channels['lap'];
  const temperature = channels['battery_temperature_k'];
  return {
    id: carId,
    present: true,
    position: index + 1,
    field: frame.cars.length,
    lap: finished ? laps : completed === undefined ? undefined : Math.min(laps, Math.floor(completed) + 1),
    laps,
    finished,
    lapFraction: channels['s_m'] === undefined || frame.circuit_map.length_m <= 0
      ? undefined : channels['s_m'] / frame.circuit_map.length_m,
    speed_kph: scaled(channels['speed_mps'], 1 / 3.6),
    power_kw: scaled(channels['electrical_power_w'], 1000),
    throttle: channels['applied_throttle'],
    brake: channels['applied_brake'],
    energy_mj: scaled(channels['battery_energy_j'], 1e6),
    energy_percent: stateOfCharge(car),
    deployed_lap_mj: scaled(channels['deployed_this_lap_j'], 1e6),
    recharged_lap_mj: scaled(channels['recharge_this_lap_j'], 1e6),
    boost_lap_s: channels['boost_this_lap_s'],
    mode: energyMode(car),
    profile: (car.active_profile ?? 'unavailable').toUpperCase(),
    grip: channels['grip_multiplier'],
    battery_c: temperature === undefined ? undefined : temperature - 273.15,
    lateral_m: channels['lateral_d_m'],
    acceleration_mps2: channels['acceleration_mps2'],
    ahead: gapTo(car, frame.cars[index - 1], index - 1),
    behind: gapTo(car, frame.cars[index + 1], index + 1),
  };
}

export interface FlagReadout {
  label: string;
  tone: string;
}

const UNKNOWN_FLAG: FlagReadout = { label: 'FLAG UNAVAILABLE', tone: 'unknown' };

const FLAG_LABELS: Record<string, FlagReadout> = {
  green: { label: 'TRACK CLEAR', tone: 'clear' },
  yellow: { label: 'YELLOW FLAG', tone: 'caution' },
  double_yellow: { label: 'DOUBLE YELLOW', tone: 'caution' },
  safety_car: { label: 'SAFETY CAR', tone: 'caution' },
  virtual_safety_car: { label: 'VIRTUAL SC', tone: 'caution' },
  red: { label: 'RED FLAG', tone: 'stopped' },
  chequered: { label: 'CHEQUERED', tone: 'finished' },
  unknown: UNKNOWN_FLAG,
};

export function flagState(frame: RaceFrame | null, car: CarReadout, connected: boolean): FlagReadout {
  if (!connected) {
    return { label: 'NO TELEMETRY', tone: 'unknown' };
  }
  if (frame?.status === 'failed') {
    return { label: 'SESSION STOPPED', tone: 'stopped' };
  }
  if (car.finished || frame?.status === 'finished') {
    return { label: 'CHEQUERED', tone: 'finished' };
  }
  return FLAG_LABELS[frame?.flags?.[0] ?? 'unknown'] ?? UNKNOWN_FLAG;
}
