import { expect, test } from '@playwright/test';

import { RaceMotion, rankedCar } from '../src/features/race/motion';
import { ribbon, trackPose } from '../src/features/race/worldGeometry';
import type { RaceFrame } from '../src/features/race/types';

function frame(time: number, progress: number, status = 'running', generation = 1): RaceFrame {
  return {
    type: 'frame', time_s: time, generation, status, steps: 0, failure: null,
    requested_rate: 1, actual_rate: 1, has_checkpoint: false, events: [],
    settings: { circuit: 'test', seed: 1, cars: 1, laps: 3, dt_s: 0.01,
      wetness: 0, temperature_k: 300, wind_mps: 0, wake: false, variability: { preset: 'mild' }, time_limit_s: 100 },
    circuit_map: { id: 'test', name: 'Test', length_m: 1000,
      points: [[0, 0], [100, 0], [100, 100], [0, 100]] },
    cars: [{ id: 'car-01', channels: { s_m: progress % 1000, progress_m: progress },
      observed_at_s: time, requested_profile: 'neutral', finish_time_s: null }],
  };
}

test('motion interpolates continuously without easing at each received point', () => {
  const motion = new RaceMotion();
  for (let i = 0; i < 5; i++) {
    motion.push(frame(i * 0.1, i * 10), i * 150);
  }
  const positions = [600, 630, 660, 690, 720].map((now) => motion.sample(now).get('car-01')?.progress);
  positions.forEach((position, i) => expect(position).toBeCloseTo(15 + i * 2));
  expect(motion.sample(5000).get('car-01')?.progress).toBe(40);
});

test('motion crosses the finish line forwards and resets immediately on pause and restore', () => {
  const motion = new RaceMotion();
  motion.push(frame(1, 995), 0);
  motion.push(frame(1.1, 1005), 150);
  expect(motion.sample(450).get('car-01')?.progress).toBeCloseTo(1000);
  motion.push(frame(1.1, 1005, 'paused'), 460);
  expect(motion.sample(460).get('car-01')?.progress).toBe(1005);
  motion.push(frame(0, 5, 'paused', 2), 500);
  expect(motion.sample(500).get('car-01')?.progress).toBe(5);
  const unknown = frame(0.1, 0, 'paused', 2);
  for (const car of unknown.cars) {
    car.channels = {};
  }
  motion.push(unknown, 600);
  expect(motion.sample(600).size).toBe(0);
});

test('arrival jitter does not turn constant motion into packet-sized jumps', () => {
  const motion = new RaceMotion();
  const arrivals = [0, 150, 260, 480, 550, 760, 840, 1080, 1130, 1370, 1480, 1650, 1800];
  let next = 0;
  const positions: number[] = [];
  for (let now = 0; now <= 1800; now += 10) {
    while (next < arrivals.length && (arrivals[next] ?? Infinity) <= now) {
      motion.push(frame(next * 0.1, next * 10), arrivals[next] ?? 0);
      next++;
    }
    const position = motion.sample(now).get('car-01')?.progress ?? 0;
    if (now >= 500) {
      positions.push(position);
    }
  }
  const increments = positions.slice(1).map((position, i) => position - (positions[i] ?? 0));
  expect(Math.min(...increments)).toBeGreaterThan(0.5);
  expect(Math.max(...increments)).toBeLessThan(0.8);
  expect(motion.sample(9000).get('car-01')?.progress).toBe(120);
});

test('buffer fills before playback and all cars share the same render time', () => {
  const motion = new RaceMotion();
  for (let i = 0; i < 8; i++) {
    const update = frame(i * 0.1, i * 10);
    update.cars.push({ id: 'car-02', observed_at_s: i * 0.1,
      requested_profile: 'neutral', finish_time_s: null,
      channels: { progress_m: i * 10 - 6, lateral_d_m: 0 } });
    motion.push(update, i * 150);
    const poses = motion.sample(i * 150);
    if (i < 3) {
      expect(poses.get('car-01')?.progress).toBe(0);
    }
    expect((poses.get('car-01')?.progress ?? 0) - (poses.get('car-02')?.progress ?? 0)).toBeCloseTo(6);
  }
});

test('noisy telemetry is smoothed without moving backwards or overshooting a stop', () => {
  const motion = new RaceMotion();
  for (let i = 0; i < 10; i++) {
    const update = frame(i * 0.1, i * 2 + (i % 2 ? 0.8 : -0.8));
    const car = update.cars[0];
    if (car) {
      car.channels['speed_mps'] = 20;
    }
    motion.push(update, i * 100);
  }
  const positions = Array.from({ length: 100 }, (_, i) => motion.sample(500 + i * 10).get('car-01')?.progress ?? NaN);
  const increments = positions.slice(1).map((position, i) => position - (positions[i] ?? NaN));
  expect(Math.min(...increments)).toBeGreaterThanOrEqual(0);
  expect(Math.max(...increments)).toBeLessThan(0.35);
  expect(motion.sample(9000).get('car-01')?.progress).toBeLessThanOrEqual(18.8);
});

test('track position and direction stay continuous across artwork nodes', () => {
  const map = frame(0, 0).circuit_map;
  const before = trackPose(map, 249.999);
  const after = trackPose(map, 250.001);
  expect(before.position.distanceTo(after.position)).toBeLessThan(0.01);
  expect(Math.abs(before.yaw - after.yaw)).toBeLessThan(0.001);
});

test('camera switching wraps through the current race order', () => {
  expect(rankedCar(['car-03', 'car-01', 'car-02'], 'car-01', -1)).toBe('car-03');
  expect(rankedCar(['car-03', 'car-01', 'car-02'], 'car-03', -1)).toBe('car-02');
  expect(rankedCar(['car-03', 'car-01', 'car-02'], 'car-02', 1)).toBe('car-03');
});

test('road surface follows the smoothed car path between artwork nodes', () => {
  const map = frame(0, 0).circuit_map;
  const road = ribbon(map, -6, 6, 0);
  const vertices = road.getAttribute('position');
  const segments = vertices.count / 2 - 1;
  for (let i = 0; i < segments; i++) {
    const x = [0, 1, 2, 3].reduce((sum, j) => sum + vertices.getX(i * 2 + j), 0) / 4;
    const z = [0, 1, 2, 3].reduce((sum, j) => sum + vertices.getZ(i * 2 + j), 0) / 4;
    const car = trackPose(map, (i + 0.5) / segments * map.length_m).position;
    expect(Math.hypot(x - car.x, z - car.z)).toBeLessThan(0.05);
  }
  road.dispose();
});
