import { expect, test } from '@playwright/test';

import { RaceMotion, rankedCar } from '../src/features/race/motion';
import { ribbon, trackPose } from '../src/features/race/worldGeometry';
import type { RaceFrame } from '../src/features/race/types';

function frame(time: number, progress: number, status = 'running', generation = 1): RaceFrame {
  return {
    type: 'frame', time_s: time, generation, status, steps: 0, failure: null,
    requested_rate: 1, actual_rate: 1, has_checkpoint: false, events: [],
    boost_evaluation: { true_positive: 0, false_positive: 0, true_negative: 0, false_negative: 0,
      accuracy: null, precision: null, recall: null },
    regulations: { name: 'FIA Formula 1 2026 race subset', effective_issue_dates: {}, sources: {},
      enforced: {}, session_limits: {}, limitations: 'test fixture' },
    settings: { circuit: 'test', seed: 1, cars: 1, laps: 3, dt_s: 0.01,
      wetness: 0, weather: 'sunny', temperature_k: 300, wind_mps: 0, wake: false,
      contact_mode: 'ignore', variability: { preset: 'mild' }, time_limit_s: 100,
      storyline: { enabled: true, pit_stops: true, tyre_wear_scale: 1,
        event_interval_min_s: 4, event_interval_max_s: 16,
        event_duration_min_s: 1.5, event_duration_max_s: 5 },
      racing_line: { enabled: true, corner_strength: 0.9, randomness: 0.7, wander_m: 0.8,
        lookahead_m: 65, smoothing_m: 30, overtake_in_corners: true } },
    circuit_map: { id: 'test', name: 'Test', length_m: 1000,
      points: [[0, 0], [100, 0], [100, 100], [0, 100]] },
    cars: [{ id: 'car-01', channels: { s_m: progress % 1000, progress_m: progress },
      observed_at_s: time, requested_profile: 'neutral', finish_time_s: null,
      qualifying_position: 1, storyline: 'natural', classified: false,
      regulation_status: 'running', points: 0,
      tyres: { compound: 'medium', condition: 1, grip: 1, sidewall: '#f0c438', phase: 'track',
        requested: false, service_duration_s: 2.5, service_remaining_s: 0, stops: 0,
        used_compounds: ['medium'], visual_lateral_m: 0 } }],
  };
}

test('motion interpolates continuously without easing at each received point', () => {
  const motion = new RaceMotion();
  for (let i = 0; i < 5; i++) {
    const update = frame(i * 0.1, i * 10);
    const car = update.cars[0];
    if (car) {
      car.channels['lateral_d_m'] = i;
      car.channels['speed_mps'] = 100;
    }
    motion.push(update, i * 150);
  }
  const poses = [600, 630, 660, 690, 720].map((now) => motion.sample(now).get('car-01'));
  const positions = poses.map((pose) => pose?.progress);
  const lateral = poses.map((pose) => pose?.lateral);
  positions.forEach((position, i) => expect(position).toBeCloseTo(15 + i * 2));
  lateral.forEach((position, i) => expect(position).toBeCloseTo(1.5 + i * 0.2));
  expect(motion.sample(5000).get('car-01')?.progress).toBe(40);
});

test('motion crosses the finish line forwards, settles into a pause and restores immediately', () => {
  const motion = new RaceMotion();
  motion.push(frame(1, 995), 0);
  motion.push(frame(1.1, 1005), 150);
  expect(motion.sample(450).get('car-01')?.progress).toBeCloseTo(1000);
  motion.push(frame(1.1, 1005, 'paused'), 460);
  expect(motion.sample(460).get('car-01')?.progress).toBeLessThan(1001);
  expect(motion.sample(3000).get('car-01')?.progress).toBe(1005);
  motion.push(frame(0, 5, 'paused', 2), 3100);
  expect(motion.sample(3100).get('car-01')?.progress).toBe(5);
  const unknown = frame(0.1, 0, 'paused', 2);
  for (const car of unknown.cars) {
    car.channels = {};
  }
  motion.push(unknown, 3200);
  expect(motion.sample(3200).size).toBe(0);
});

test('pausing drains the observation buffer instead of teleporting the view forward', () => {
  const motion = new RaceMotion();
  const speed = 60;
  let observed = 0;
  let now = 0;
  for (let i = 0; i < 30; i++) {
    observed = i * 0.1;
    const update = frame(observed, observed * speed);
    const car = update.cars[0];
    if (car) {
      car.channels['speed_mps'] = speed;
    }
    motion.push(update, now);
    now += 100;
  }
  const read = (at: number) => motion.sample(at).get('car-01')?.progress ?? NaN;
  const running = Array.from({ length: 25 }, (_, i) => read(now - 400 + i * 16));
  const typical = Math.max(...running.slice(1).map((position, i) => position - (running[i] ?? 0)));
  expect(typical).toBeGreaterThan(0);
  const halted = frame(observed, observed * speed, 'paused');
  const car = halted.cars[0];
  if (car) {
    car.channels['speed_mps'] = speed;
  }
  const shownBeforePause = read(now);
  motion.push(halted, now);
  const after = [shownBeforePause, ...Array.from({ length: 120 }, (_, i) => read(now + i * 16))];
  const steps = after.slice(1).map((position, i) => position - (after[i] ?? 0));
  expect(Math.min(...steps)).toBeGreaterThanOrEqual(0);
  expect(Math.max(...steps)).toBeLessThan(typical * 1.5);
  expect(after.at(-1)).toBeCloseTo(observed * speed);
});

test('pit phases follow the rendered pit-lane lateral path', () => {
  const motion = new RaceMotion();
  const update = frame(1, 200);
  const car = update.cars[0];
  if (car) {
    car.channels['lateral_d_m'] = 1;
    car.tyres.phase = 'service';
    car.tyres.visual_lateral_m = -13;
  }
  motion.push(update, 0);
  expect(motion.sample(0).get('car-01')?.lateral).toBe(-13);
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
      qualifying_position: 2, storyline: 'natural', classified: false,
      regulation_status: 'running', points: 0,
      tyres: { compound: 'hard', condition: 1, grip: 0.97, sidewall: '#f2f2ed', phase: 'track',
        requested: false, service_duration_s: 2.5, service_remaining_s: 0, stops: 0,
        used_compounds: ['hard'], visual_lateral_m: 0 },
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
  expect(trackPose(map, 100, 0, 0.1).yaw).not.toBeCloseTo(trackPose(map, 100, 0).yaw);
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
