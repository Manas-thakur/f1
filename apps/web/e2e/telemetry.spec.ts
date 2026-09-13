import { expect, test } from '@playwright/test';

import { LapTimer, lapClock, signedSeconds } from '../src/features/telemetry/lapTiming';
import { flagState, readout } from '../src/features/telemetry/readouts';
import type { RaceCar, RaceFrame } from '../src/features/race/types';

const LENGTH_M = 1000;

function car(id: string, channels: Record<string, number>): RaceCar {
  return {
    id, channels, observed_at_s: 0, requested_profile: 'auto', finish_time_s: null,
    qualifying_position: 1, storyline: 'natural', classified: false,
    regulation_status: 'running', points: 0,
    tyres: { compound: 'medium', condition: 1, grip: 1, sidewall: '#f0c438', phase: 'track',
      requested: false, service_duration_s: 2.5, service_remaining_s: 0, box_progress_m: 0,
      release_waiting: false, stops: 0,
      used_compounds: ['medium'], visual_lateral_m: 0 },
  };
}

function frame(time_s: number, cars: RaceCar[], generation = 1): RaceFrame {
  return {
    type: 'frame', time_s, generation, steps: Math.round(time_s * 100), status: 'running',
    failure: null, requested_rate: 1, actual_rate: 1, has_checkpoint: false, events: [],
    flags: ['green'],
    recommendations: {}, training_metrics: null,
    boost_evaluation: { true_positive: 0, false_positive: 0, true_negative: 0, false_negative: 0,
      accuracy: null, precision: null, recall: null },
    regulations: { name: 'FIA Formula 1 2026 race subset', effective_issue_dates: {}, sources: {},
      enforced: {}, session_limits: {}, limitations: 'test fixture' },
    settings: {
      circuit: 'test', seed: 1, cars: cars.length, laps: 5, dt_s: 0.01, wetness: 0,
      weather: 'sunny', temperature_k: 300, wind_mps: 0, wake: false, contact_mode: 'ignore',
      variability: { preset: 'mild' }, time_limit_s: 1000,
      storyline: { enabled: true, pit_stops: true, tyre_wear_scale: 1,
        event_interval_min_s: 4, event_interval_max_s: 16,
        event_duration_min_s: 1.5, event_duration_max_s: 5 },
      racing_line: { enabled: true, corner_strength: 0.9, randomness: 0.7, wander_m: 0.8,
        lookahead_m: 65, smoothing_m: 30, overtake_in_corners: true },
    },
    circuit_map: {
      id: 'test', name: 'Test', length_m: LENGTH_M,
      points: [[0, 0], [100, 0], [100, 100], [0, 100]],
    },
    cars,
  };
}

function driveLaps(timer: LapTimer, speeds_mps: number[]) {
  let time_s = 0;
  let progress_m = 0;
  for (const speed of speeds_mps) {
    const finish = progress_m + LENGTH_M;
    while (progress_m < finish - 1e-9) {
      const advance_m = Math.min(speed, finish - progress_m);
      progress_m += advance_m;
      time_s += advance_m / speed;
      timer.push(frame(time_s, [car('car-01', { progress_m, s_m: progress_m % LENGTH_M })]), 'car-01');
    }
  }
  return { time_s, progress_m };
}

test('lap timing derives completed laps, the best lap and a live delta from observed progress', () => {
  const timer = new LapTimer();
  const first = timer.push(frame(0, [car('car-01', { progress_m: 0, s_m: 0 })]), 'car-01');
  expect(first.best_s).toBeUndefined();
  expect(first.delta_s).toBeUndefined();

  const after = driveLaps(timer, [10, 12.5]);
  const two = timer.push(frame(after.time_s, [car('car-01',
    { progress_m: after.progress_m, s_m: 0 })]), 'car-01');
  expect(two.laps.map((lap) => Math.round(lap))).toEqual([100, 80]);
  expect(two.best_s).toBeCloseTo(80, 6);
  expect(two.lap).toBe(3);

  let time_s = after.time_s;
  let progress_m = after.progress_m;
  let reading = two;
  while (progress_m < after.progress_m + 500 - 1e-9) {
    progress_m += 10;
    time_s += 1;
    reading = timer.push(frame(time_s, [car('car-01',
      { progress_m, s_m: progress_m % LENGTH_M })]), 'car-01');
  }
  expect(reading.elapsed_s).toBeCloseTo(50, 6);
  expect(reading.delta_s).toBeCloseTo(10, 3);
});

test('lap timing restarts on a new generation and ignores repeated frames', () => {
  const timer = new LapTimer();
  driveLaps(timer, [10]);
  const repeated = frame(100, [car('car-01', { progress_m: 1000, s_m: 0 })]);
  expect(timer.push(repeated, 'car-01')).toBe(timer.push(repeated, 'car-01'));
  const restarted = timer.push(
    frame(0, [car('car-01', { progress_m: 0, s_m: 0 })], 2), 'car-01');
  expect(restarted.best_s).toBeUndefined();
  expect(restarted.laps).toEqual([]);
  expect(restarted.lap).toBe(1);
});

test('lap timing stays unavailable until it observes a crossing when the display joins mid-lap', () => {
  const timer = new LapTimer();
  let time_s = 500;
  let progress_m = 4500;
  const push = () => timer.push(
    frame(time_s, [car('car-01', { progress_m, s_m: progress_m % LENGTH_M })]), 'car-01');
  let reading = push();
  expect(reading.lap).toBe(5);
  expect(reading.elapsed_s).toBeUndefined();
  expect(reading.delta_s).toBeUndefined();
  while (progress_m < 5100 - 1e-9) {
    progress_m += 10;
    time_s += 1;
    reading = push();
  }
  expect(reading.lap).toBe(6);
  expect(reading.elapsed_s).toBeCloseTo(10, 6);
  expect(reading.laps).toEqual([]);
  expect(reading.best_s).toBeUndefined();
});

test('readouts derive position and both gaps from published per-car progress', () => {
  const cars = [
    car('car-02', { progress_m: 1100, speed_mps: 50 }),
    car('car-01', { progress_m: 1000, speed_mps: 50, applied_throttle: 0.84, applied_brake: 0 }),
    car('car-03', { progress_m: 900, speed_mps: 50 }),
  ];
  const observed = readout(frame(20, cars), 'car-01');
  expect(observed.position).toBe(2);
  expect(observed.field).toBe(3);
  expect(observed.ahead?.id).toBe('car-02');
  expect(observed.ahead?.gap_s).toBeCloseTo(2, 6);
  expect(observed.behind?.id).toBe('car-03');
  expect(observed.behind?.gap_s).toBeCloseTo(2, 6);
  expect(observed.speed_kph).toBeCloseTo(180, 6);
  expect(observed.throttle).toBeCloseTo(0.84, 6);
});

test('unavailable channels and unknown cars stay unavailable rather than reading zero', () => {
  const empty = readout(frame(1, [car('car-01', {})]), 'car-01');
  expect(empty.present).toBe(true);
  expect(empty.speed_kph).toBeUndefined();
  expect(empty.throttle).toBeUndefined();
  expect(empty.energy_percent).toBeUndefined();
  expect(empty.lap).toBeUndefined();

  const missing = readout(frame(1, [car('car-01', {})]), 'car-09');
  expect(missing.present).toBe(false);
  expect(missing.position).toBeUndefined();
  expect(flagState(null, missing, false).label).toBe('NO TELEMETRY');
  expect(flagState(frame(1, [car('car-01', {})]), missing, true).label).toBe('TRACK CLEAR');
  expect(lapClock(undefined)).toBe('--.--');
  expect(lapClock(49.5)).toBe('49.50');
  expect(lapClock(89.8)).toBe('1:29.80');
  expect(signedSeconds(-0.28)).toBe('−0.280');
});

test('the telemetry screen streams one car, scales to the display and starts the race', async ({
  page,
}) => {
  test.slow();
  await page.goto('/race');
  await page.getByRole('button', { name: 'Race controls', exact: true }).click();
  await page.getByRole('combobox', { name: 'Circuit', exact: true }).selectOption('madring');
  await page.getByLabel('Cars', { exact: true }).fill('3');
  await page.getByRole('button', { name: 'Reset race', exact: true }).click();

  await page.setViewportSize({ width: 800, height: 480 });
  await page.goto('/tel/car-01');
  await expect(page.getByLabel('Live telemetry for car-01')).toBeVisible();
  await page.getByRole('combobox', { name: 'Telemetry car', exact: true }).selectOption('car-02');
  await expect(page).toHaveURL(/\/tel\/car-02$/);
  await expect(page.getByLabel('Live telemetry for car-02')).toBeVisible();
  await expect(page.getByLabel('Position and lap')).toContainText('/3');
  const stageSize = async () => page.evaluate(() => {
    const box = document.querySelector('[class*="dashboard"]')?.getBoundingClientRect();
    return box ? { width: Math.round(box.width), height: Math.round(box.height) } : null;
  });
  await expect.poll(stageSize).toEqual({ width: 800, height: 480 });

  await expect(page.getByRole('button', { name: 'Start race', exact: true }))
    .toHaveAttribute('aria-keyshortcuts', 'Space');
  await page.keyboard.press('Space');
  await expect(page.getByRole('button', { name: 'Pause race', exact: true })).toBeVisible();
  const boostRequest = page.waitForRequest((request) => (
    request.method() === 'POST' && new URL(request.url()).pathname === '/race/boost/car-02'
  ));
  const boost = page.getByRole('button', { name: 'Apply boost to car-02', exact: true });
  await expect(boost).toBeEnabled();
  await boost.click();
  await boostRequest;
  await expect(boost).toHaveAttribute('data-active', 'true');
  const speed = page.getByLabel('Speed, electrical power and deployment profile');
  await expect.poll(async () => Number(await speed.locator('strong').nth(1).innerText()))
    .toBeGreaterThan(0);
  await expect(page.getByLabel('Throttle and brake')).not.toContainText('--');
  await expect(page.getByLabel('Energy store')).not.toContainText('--');

  await page.setViewportSize({ width: 400, height: 900 });
  await expect.poll(stageSize).toEqual({ width: 400, height: 240 });
  await page.keyboard.press('Space');
  await expect(page.getByRole('button', { name: 'Start race', exact: true })).toBeVisible();
});

test('the race overlay prioritizes essential telemetry and links to the selected car display', async ({
  page,
}) => {
  await page.goto('/race');
  await page.getByRole('button', { name: 'Race controls', exact: true }).click();
  await page.getByLabel('Cars', { exact: true }).fill('2');
  await page.getByRole('button', { name: 'Reset race', exact: true }).click();
  await page.getByRole('button', { name: 'Close race controls', exact: true }).click();
  await page.keyboard.press('Space');
  await expect(page.getByRole('button', { name: 'Pause race', exact: true })).toBeVisible();
  await page.keyboard.press('Space');
  await expect(page.getByRole('button', { name: 'Start race', exact: true })).toBeVisible();
  const summary = page.getByLabel('Race telemetry for car-01');
  await expect(summary).toBeVisible();
  await expect(summary.getByLabel('Current speed')).toContainText('KM/H');
  await expect(summary.getByLabel('Battery charge', { exact: true })).toContainText('BATTERY');
  await expect(summary.getByLabel('Race position, lap and power')).toContainText('POSITION');
  await expect(summary.getByLabel('Throttle and brake')).toContainText('THROTTLE');
  const fullView = summary.getByRole('link', {
    name: 'Open full telemetry for car-01 in a new tab',
  });
  await expect(fullView).toHaveAttribute('href', '/tel/car-01');
  await expect(fullView).toHaveAttribute('target', '_blank');
  await expect(summary).toHaveCSS('width', '360px');
  await expect(summary).toHaveCSS('height', '216px');

  await page.getByRole('button', { name: 'Watch car behind', exact: true }).click();
  const nextSummary = page.getByLabel('Race telemetry for car-02');
  await expect(nextSummary).toBeVisible();
  const nextFullView = nextSummary.getByRole('link', {
    name: 'Open full telemetry for car-02 in a new tab',
  });
  await expect(nextFullView).toHaveAttribute('href', '/tel/car-02');
  const opened = page.context().waitForEvent('page');
  await nextFullView.click();
  const telemetryPage = await opened;
  await expect(telemetryPage).toHaveURL(/\/tel\/car-02$/);
  await telemetryPage.close();
});
