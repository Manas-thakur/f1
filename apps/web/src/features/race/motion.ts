import type { RaceFrame } from './types';

export interface MotionPose {
  progress: number;
  lateral: number;
  speed?: number;
  lateralRate?: number;
}

interface Sample {
  at: number;
  time: number;
  poses: Map<string, MotionPose>;
}

export class RaceMotion {
  private samples: Sample[] = [];
  private generation = -1;
  private simulationTime = -1;
  private interval = 150;
  private cursor = -Infinity;
  private sampledAt = 0;
  private rate = 1;
  private running = false;
  private length = 1;

  push(frame: RaceFrame, now: number) {
    if (frame.generation !== this.generation || frame.time_s < this.simulationTime
      || (frame.status === 'running') !== this.running) {
      this.samples = [];
      this.cursor = -Infinity;
      this.interval = 150;
      this.rate = frame.requested_rate;
    }
    this.generation = frame.generation;
    this.running = frame.status === 'running';
    this.length = frame.circuit_map.length_m;
    if (frame.time_s === this.simulationTime && this.samples.length) {
      return;
    }
    this.simulationTime = frame.time_s;
    const previous = this.samples.at(-1);
    const time = frame.cars.find((car) => car.channels['progress_m'] !== undefined)?.observed_at_s ?? frame.time_s;
    if (previous && time <= previous.time) {
      return;
    }
    if (previous) {
      this.interval += (Math.min(1000, now - previous.at) - this.interval) * 0.1;
      const start = this.samples[Math.max(0, this.samples.length - 12)] ?? previous;
      const measured = (time - start.time) * 1000 / Math.max(1, now - start.at);
      this.rate = this.samples.length === 1 ? measured : this.rate + (measured - this.rate) * 0.1;
    }
    const poses = new Map<string, MotionPose>();
    for (const car of frame.cars) {
      const progress = car.channels['progress_m'] ?? car.channels['s_m'];
      if (progress === undefined) {
        continue;
      }
      const old = previous?.poses.get(car.id);
      const before = this.samples.at(-2)?.poses.get(car.id);
      let unwrapped = car.channels['progress_m'] !== undefined || !old ? progress
        : old.progress + ((progress - old.progress + this.length * 1.5) % this.length) - this.length / 2;
      const speed = car.channels['speed_mps'];
      if (this.running && previous && old?.speed !== undefined && speed !== undefined) {
        const dt = time - previous.time;
        const prediction = old.progress + (old.speed + speed) * 0.5 * dt;
        if (Math.abs(unwrapped - prediction) < 5) {
          const correction = (unwrapped - prediction) * (1 - Math.exp(-dt / 0.25));
          unwrapped = Math.max(old.progress, prediction + correction);
        }
      }
      const lateral = car.channels['lateral_d_m'] ?? 0;
      const dt = previous ? time - previous.time : 0;
      const lateralRate = old && dt > 0 ? (lateral - old.lateral) / dt : 0;
      if (old && before && previous) {
        const centredDt = time - (this.samples.at(-2)?.time ?? time);
        old.lateralRate = centredDt > 0 ? (lateral - before.lateral) / centredDt : lateralRate;
      }
      poses.set(car.id, { progress: unwrapped, lateral, lateralRate,
        ...(speed === undefined ? {} : { speed: Math.max(0, speed) }) });
    }
    if (!poses.size) {
      this.samples = [];
      this.cursor = -Infinity;
      return;
    }
    this.samples.push({ at: now, time, poses });
    this.samples = this.samples.slice(-64);
  }

  sample(now: number) {
    const last = this.samples.at(-1);
    const first = this.samples[0];
    if (!last || !first) {
      return new Map<string, MotionPose>();
    }
    if (!this.running) {
      return last.poses;
    }
    if (!Number.isFinite(this.cursor)) {
      if (now - first.at < this.delayMs) {
        return first.poses;
      }
      this.cursor = first.time + Math.max(0, now - first.at - this.delayMs) * this.rate / 1000;
    } else {
      const elapsed = Math.max(0, now - this.sampledAt) / 1000;
      const targetBuffer = this.delayMs * this.rate / 1000;
      const backlog = last.time - this.cursor;
      const correction = backlog > targetBuffer * 2 ? 1.05 : 1;
      this.cursor += elapsed * this.rate * correction;
    }
    this.sampledAt = now;
    this.cursor = Math.min(last.time, Math.max(first.time, this.cursor));
    const right = this.samples.findIndex((sample) => sample.time >= this.cursor);
    const b = this.samples[right];
    const a = this.samples[Math.max(0, right - 1)];
    if (!a || !b || a === b) {
      return b?.poses ?? last.poses;
    }
    const duration = Math.max(1e-6, b.time - a.time);
    const t = Math.max(0, Math.min(1, (this.cursor - a.time) / duration));
    const result = new Map<string, MotionPose>();
    for (const [id, destination] of b.poses) {
      const origin = a.poses.get(id);
      if (!origin) {
        continue;
      }
      const delta = destination.progress - origin.progress;
      let progress = origin.progress + delta * t;
      if (delta >= 0 && origin.speed !== undefined && destination.speed !== undefined) {
        const v0 = Math.min(origin.speed * duration, delta * 3);
        const v1 = Math.min(destination.speed * duration, delta * 3);
        const scale = Math.max(1, (v0 + v1) / Math.max(delta * 3, 1e-9));
        progress = (2 * t ** 3 - 3 * t ** 2 + 1) * origin.progress
          + (t ** 3 - 2 * t ** 2 + t) * v0 / scale
          + (-2 * t ** 3 + 3 * t ** 2) * destination.progress + (t ** 3 - t ** 2) * v1 / scale;
      }
      const deltaLateral = destination.lateral - origin.lateral;
      const m0 = (origin.lateralRate ?? deltaLateral / duration) * duration;
      const m1 = (destination.lateralRate ?? deltaLateral / duration) * duration;
      const lateral = Math.max(Math.min(origin.lateral, destination.lateral), Math.min(
        Math.max(origin.lateral, destination.lateral),
        (2 * t ** 3 - 3 * t ** 2 + 1) * origin.lateral
          + (t ** 3 - 2 * t ** 2 + t) * m0
          + (-2 * t ** 3 + 3 * t ** 2) * destination.lateral + (t ** 3 - t ** 2) * m1,
      ));
      const lateralRate = (
        (6 * t ** 2 - 6 * t) * origin.lateral
        + (3 * t ** 2 - 4 * t + 1) * m0
        + (-6 * t ** 2 + 6 * t) * destination.lateral
        + (3 * t ** 2 - 2 * t) * m1
      ) / duration;
      const speed = origin.speed === undefined || destination.speed === undefined
        ? undefined : origin.speed + (destination.speed - origin.speed) * t;
      result.set(id, { progress, lateral, lateralRate, ...(speed === undefined ? {} : { speed }) });
    }
    return result;
  }

  get delayMs() {
    return Math.max(200, Math.min(1200, this.interval * 2.5));
  }
}

export function rankedCar(ids: string[], selected: string, direction: -1 | 1) {
  if (!ids.length) {
    return selected;
  }
  const index = Math.max(0, ids.indexOf(selected));
  return ids[(index + direction + ids.length) % ids.length] ?? selected;
}
