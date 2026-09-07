import { describe, expect, it } from 'vitest';

import { CHANNELS, channel, fromDisplay, toDisplay } from './channels';
import {
  UNAVAILABLE_TEXT,
  formatAge,
  formatChannelValue,
  formatInterval,
  formatScalar,
  isBlockingQuality,
} from './units';

describe('unit conversion table', () => {
  const cases: readonly [string, number, string][] = [
    ['electrical_power_w', 350_000, '350 kW'],
    ['battery_energy_j', 1_500_000, '1.50 MJ'],
    ['speed_mps', 90, '324 km/h'],
    ['battery_temperature_k', 273.15, '0 °C'],
  ];

  for (const [channelName, si, expected] of cases) {
    it(`${si} ${channel(channelName).unit} renders as "${expected}"`, () => {
      expect(formatChannelValue(channelName, si).text).toBe(expected);
    });
  }

  it('round-trips display values through the registry', () => {
    for (const spec of CHANNELS) {
      const si = 1234.5;
      expect(fromDisplay(spec, toDisplay(spec, si))).toBeCloseTo(si, 6);
    }
  });

  it('normalises negative zero', () => {
    expect(formatChannelValue('electrical_power_w', -0.4).text).toBe('0 kW');
    expect(formatChannelValue('electrical_power_w', -0.4).text).not.toContain('-0');
  });

  it('does not invent a conversion for an unregistered channel', () => {
    const result = formatChannelValue('not_a_channel', 42, { fallbackUnit: 'widgets' });
    expect(result.text).toBe('42.000 widgets');
  });
});

describe('null is never zero', () => {
  it('formats a null value as unavailable text', () => {
    const result = formatChannelValue('battery_energy_j', null);
    expect(result.available).toBe(false);
    expect(result.value).toBeNull();
    expect(result.text).toBe(UNAVAILABLE_TEXT);
    expect(result.text).not.toContain('0');
  });

  it('formats an undefined and a non-finite value as unavailable', () => {
    expect(formatChannelValue('speed_mps', undefined).available).toBe(false);
    expect(formatChannelValue('speed_mps', Number.NaN).available).toBe(false);
    expect(formatChannelValue('speed_mps', Number.POSITIVE_INFINITY).available).toBe(false);
  });

  it('keeps the unit available so the label can still show it', () => {
    expect(formatChannelValue('battery_energy_j', null).unit).toBe('MJ');
  });
});

describe('formatScalar', () => {
  it('reads the value out of a contract ScalarValue', () => {
    const result = formatScalar('electrical_power_w', {
      value: 350_000,
      unit: 'W',
      provenance: 'simulated',
      quality: 'valid',
    });
    expect(result.text).toBe('350 kW');
  });

  it('reports a null-valued scalar as unavailable', () => {
    const result = formatScalar('battery_energy_j', {
      value: null,
      unit: 'J',
      provenance: 'estimated',
      quality: 'missing',
    });
    expect(result.text).toBe(UNAVAILABLE_TEXT);
  });
});

describe('formatInterval', () => {
  it('formats a two-sided interval in display units', () => {
    const result = formatInterval('battery_energy_j', {
      lower: 1_000_000,
      upper: 2_500_000,
      unit: 'J',
      kind: 'quantile',
      coverage: 0.8,
      provenance: 'estimated',
    });
    expect(result.text).toBe('1.00 – 2.50 MJ');
  });

  it('reports an open interval as unavailable rather than guessing a bound', () => {
    const result = formatInterval('battery_energy_j', {
      lower: null,
      upper: 2_500_000,
      unit: 'J',
      kind: 'physical_bounds',
      provenance: 'estimated',
    });
    expect(result.available).toBe(false);
    expect(result.text).toBe(UNAVAILABLE_TEXT);
  });
});

describe('formatAge', () => {
  it('says the age is unknown when there is none', () => {
    expect(formatAge(null)).toBe('age unknown');
    expect(formatAge(undefined)).toBe('age unknown');
  });

  it('formats sub-second, second and minute ages', () => {
    expect(formatAge(0.25)).toBe('250 ms ago');
    expect(formatAge(4.25)).toBe('4.3 s ago');
    expect(formatAge(125)).toBe('2 min 5 s ago');
  });
});

describe('blocking quality', () => {
  it('treats stale, missing and invalid as blocking', () => {
    expect(isBlockingQuality('stale')).toBe(true);
    expect(isBlockingQuality('missing')).toBe(true);
    expect(isBlockingQuality('invalid')).toBe(true);
  });

  it('does not treat valid, degraded or unknown as blocking', () => {
    expect(isBlockingQuality('valid')).toBe(false);
    expect(isBlockingQuality('degraded')).toBe(false);
    expect(isBlockingQuality(null)).toBe(false);
  });
});
