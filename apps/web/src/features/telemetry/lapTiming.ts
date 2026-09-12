import type { RaceFrame } from '../race/types';

const BUCKETS = 400;
const MAX_BOUNDARIES = BUCKETS * 2;

export interface LapReading {
  lap: number;
  elapsed_s: number | undefined;
  last_s: number | undefined;
  best_s: number | undefined;
  delta_s: number | undefined;
  laps: number[];
}

const EMPTY: LapReading = {
  lap: 1,
  elapsed_s: undefined,
  last_s: undefined,
  best_s: undefined,
  delta_s: undefined,
  laps: [],
};

export function emptyLapReading(): LapReading {
  return EMPTY;
}

export class LapTimer {
  private key = '';
  private generation = -1;
  private carId = '';
  private length = 0;
  private previous: { time_s: number; progress_m: number } | null = null;
  private synced = false;
  private lapStart_s = 0;
  private completed = 0;
  private laps: number[] = [];
  private best: number | undefined = undefined;
  private trace: (number | undefined)[] = [];
  private bestTrace: (number | undefined)[] | null = null;
  private reading: LapReading = EMPTY;

  private reset(frame: RaceFrame, carId: string) {
    this.generation = frame.generation;
    this.carId = carId;
    this.length = frame.circuit_map.length_m;
    this.previous = null;
    this.synced = false;
    this.lapStart_s = 0;
    this.completed = 0;
    this.laps = [];
    this.best = undefined;
    this.trace = new Array<number | undefined>(BUCKETS);
    this.bestTrace = null;
    this.reading = EMPTY;
  }

  private crossBoundaries(time_s: number, progress_m: number) {
    const previous = this.previous;
    if (!previous || progress_m <= previous.progress_m) {
      return;
    }
    const step = this.length / BUCKETS;
    const first = Math.floor(previous.progress_m / step) + 1;
    const last = Math.floor(progress_m / step);
    if (last - first > MAX_BOUNDARIES) {
      return;
    }
    const span_m = progress_m - previous.progress_m;
    const span_s = time_s - previous.time_s;
    for (let index = first; index <= last; index++) {
      const at_s = previous.time_s + ((index * step - previous.progress_m) / span_m) * span_s;
      const bucket = index % BUCKETS;
      if (bucket !== 0) {
        this.trace[bucket] = at_s - this.lapStart_s;
        continue;
      }
      const lap_s = at_s - this.lapStart_s;
      if (this.synced && lap_s > 0) {
        this.laps = [...this.laps, lap_s];
        if (this.best === undefined || lap_s < this.best) {
          this.best = lap_s;
          this.bestTrace = this.trace;
        }
      }
      this.synced = true;
      this.completed = index / BUCKETS;
      this.lapStart_s = at_s;
      this.trace = new Array<number | undefined>(BUCKETS);
      this.trace[0] = 0;
    }
  }

  private liveDelta(elapsed_s: number, progress_m: number) {
    const reference = this.bestTrace;
    if (!reference) {
      return undefined;
    }
    const position = ((progress_m - this.completed * this.length) / this.length) * BUCKETS;
    const bucket = Math.min(BUCKETS - 1, Math.max(0, Math.floor(position)));
    const start = reference[bucket];
    if (start === undefined) {
      return undefined;
    }
    const next = reference[(bucket + 1) % BUCKETS];
    const within = next === undefined || next < start ? start : start + (next - start) * (position - bucket);
    return elapsed_s - within;
  }

  push(frame: RaceFrame, carId: string): LapReading {
    const key = `${frame.generation}:${carId}:${frame.time_s}:${frame.steps}`;
    if (key === this.key) {
      return this.reading;
    }
    this.key = key;
    if (frame.generation !== this.generation || carId !== this.carId
      || frame.circuit_map.length_m !== this.length) {
      this.reset(frame, carId);
    }
    const progress_m = frame.cars.find((car) => car.id === carId)?.channels['progress_m'];
    if (progress_m === undefined || this.length <= 0) {
      return this.reading;
    }
    if (!this.previous) {
      this.completed = Math.floor(progress_m / this.length);
      if (progress_m < this.length / BUCKETS) {
        this.synced = true;
        this.lapStart_s = frame.time_s;
        this.trace[0] = 0;
      }
    }
    this.crossBoundaries(frame.time_s, progress_m);
    this.previous = { time_s: frame.time_s, progress_m };
    const elapsed_s = this.synced ? Math.max(0, frame.time_s - this.lapStart_s) : undefined;
    this.reading = {
      lap: this.completed + 1,
      elapsed_s,
      last_s: this.laps.at(-1),
      best_s: this.best,
      delta_s: elapsed_s === undefined ? undefined : this.liveDelta(elapsed_s, progress_m),
      laps: this.laps,
    };
    return this.reading;
  }
}

export function lapClock(seconds: number | undefined, digits = 2) {
  if (seconds === undefined || !Number.isFinite(seconds) || seconds < 0) {
    return '--.--';
  }
  if (seconds < 60) {
    return seconds.toFixed(digits);
  }
  const minutes = Math.floor(seconds / 60);
  const rest = seconds - minutes * 60;
  return `${minutes}:${rest < 10 ? '0' : ''}${rest.toFixed(digits)}`;
}

export function signedSeconds(seconds: number | undefined, digits = 3) {
  if (seconds === undefined || !Number.isFinite(seconds)) {
    return '--.---';
  }
  return `${seconds < 0 ? '−' : '+'}${Math.abs(seconds).toFixed(digits)}`;
}
