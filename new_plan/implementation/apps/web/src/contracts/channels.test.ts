import { describe, expect, it } from 'vitest';

import { PYTHON_CHANNELS } from '../test/pythonRegistry';
import {
  CHANNELS,
  CHANNELS_BY_NAME,
  CHANNEL_FAMILIES,
  channel,
  isRegisteredChannel,
  seriesColourVar,
  toDisplay,
  tryChannel,
} from './channels';

describe('the TypeScript channel registry mirrors the Python one', () => {
  it('has the same channels in the same order', () => {
    expect(CHANNELS.map((c) => c.name)).toEqual(PYTHON_CHANNELS.map((c) => c.name));
  });

  it('derives display values exactly the way ChannelSpec.to_display does', () => {
    for (const row of PYTHON_CHANNELS) {
      const spec = channel(row.name);
      expect(spec.unit, row.name).toBe(row.unit);
      expect(spec.displayUnit, row.name).toBe(row.display_unit);
      expect(spec.displayScale, row.name).toBe(row.display_scale);
      expect(spec.displayOffset, row.name).toBe(row.display_offset);
      expect(spec.family, row.name).toBe(row.family);
      expect(spec.plotColourToken, row.name).toBe(row.plot_colour_token);
      expect([...spec.expectedProvenance], row.name).toEqual([...row.expected_provenance]);
      expect(spec.lowerBound, row.name).toBe(row.lower_bound);
      expect(spec.upperBound, row.name).toBe(row.upper_bound);

      // The conversion itself, on a value the Python side would produce.
      const si = 123.456;
      expect(toDisplay(spec, si)).toBeCloseTo(si * row.display_scale + row.display_offset, 9);
    }
  });

  it('exposes the same families', () => {
    expect([...CHANNEL_FAMILIES]).toEqual([...new Set(PYTHON_CHANNELS.map((c) => c.family))].sort());
  });
});

describe('lookup', () => {
  it('fails loudly on an unregistered name', () => {
    expect(() => channel('made_up_channel')).toThrow(/unknown channel/);
  });

  it('returns undefined rather than guessing', () => {
    expect(tryChannel('made_up_channel')).toBeUndefined();
    expect(isRegisteredChannel('made_up_channel')).toBe(false);
    expect(isRegisteredChannel('speed_mps')).toBe(true);
    expect(CHANNELS_BY_NAME.size).toBe(CHANNELS.length);
  });
});

describe('series identity', () => {
  it('keeps the same hue token in chrome and in a dark well', () => {
    const spec = channel('electrical_power_w');
    expect(seriesColourVar(spec, 'chrome')).toBe('var(--series-power)');
    expect(seriesColourVar(spec, 'well')).toBe('var(--series-power-well)');
  });

  it('gives the two energy-flow channels distinct tokens', () => {
    // Deploy and harvest are separately named nonnegative flows; they must not
    // share a colour, or a netted reading becomes indistinguishable.
    expect(channel('deploy_power_w').plotColourToken).not.toBe(
      channel('harvest_power_w').plotColourToken,
    );
  });
});
