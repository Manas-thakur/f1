/**
 * Display formatting for physical quantities.
 *
 * Rules this module enforces, because they are correctness properties and not
 * styling preferences:
 *   - A null value is never rendered as `0`. It renders as text saying it is
 *     not available.
 *   - Conversion always goes through the channel registry, never through an
 *     ad-hoc factor written at a call site.
 *   - `-0` formats as `0`.
 */
import type { IntervalValue, Provenance, Quality, ScalarValue } from '@contracts';

import { toDisplay, tryChannel, type ChannelSpec } from './channels';

/** The single string used everywhere a value is genuinely not available. */
export const UNAVAILABLE_TEXT = 'not available';

export interface FormattedValue {
  /** Formatted number, or null when there is no value to show. */
  readonly value: string | null;
  /** Display unit, or null when unknown. */
  readonly unit: string | null;
  /** `"350 kW"`, or the unavailable text. Always safe to render directly. */
  readonly text: string;
  readonly available: boolean;
}

function formatNumber(n: number, decimals: number): string {
  if (!Number.isFinite(n)) {
    return UNAVAILABLE_TEXT;
  }
  const text = n.toFixed(decimals);
  // A tiny negative value rounds to "-0" / "-0.00". A signed zero reads as a
  // direction of flow that the measurement does not support, so strip it.
  return Number(text) === 0 ? text.replace(/^-/, '') : text;
}

export interface FormatOptions {
  /** Override the registry's decimal count. */
  readonly decimals?: number;
  /** Unit to show when the channel is not registered. */
  readonly fallbackUnit?: string | null;
  /** Text to show when the value is null. */
  readonly unavailableText?: string;
}

/**
 * Format an SI value for a registered channel.
 *
 * 350000 W -> "350 kW"; 1500000 J -> "1.50 MJ"; 90 m/s -> "324 km/h";
 * 273.15 K -> "0 °C".
 */
export function formatChannelValue(
  channelName: string,
  siValue: number | null | undefined,
  options: FormatOptions = {},
): FormattedValue {
  const spec = tryChannel(channelName);
  const unavailable = options.unavailableText ?? UNAVAILABLE_TEXT;

  if (siValue === null || siValue === undefined || !Number.isFinite(siValue)) {
    return {
      value: null,
      unit: spec?.displayUnit ?? options.fallbackUnit ?? null,
      text: unavailable,
      available: false,
    };
  }

  if (spec === undefined) {
    // Unregistered channel: show the raw value and say so, rather than
    // inventing a conversion factor.
    const decimals = options.decimals ?? 3;
    const unit = options.fallbackUnit ?? null;
    const value = formatNumber(siValue, decimals);
    return {
      value,
      unit,
      text: unit === null ? value : `${value} ${unit}`,
      available: true,
    };
  }

  const decimals = options.decimals ?? spec.displayDecimals;
  const value = formatNumber(toDisplay(spec, siValue), decimals);
  return {
    value,
    unit: spec.displayUnit,
    text: `${value} ${spec.displayUnit}`,
    available: true,
  };
}

/** Format a contract `ScalarValue`, using its `unit` to find the channel. */
export function formatScalar(
  channelName: string,
  scalar: ScalarValue | null | undefined,
  options: FormatOptions = {},
): FormattedValue {
  if (scalar === null || scalar === undefined) {
    return formatChannelValue(channelName, null, options);
  }
  const merged: FormatOptions =
    options.fallbackUnit === undefined ? { ...options, fallbackUnit: scalar.unit } : options;
  return formatChannelValue(channelName, scalar.value, merged);
}

/** Format an interval as `"lo – hi unit"`, or the unavailable text. */
export function formatInterval(
  channelName: string,
  interval: IntervalValue | null | undefined,
  options: FormatOptions = {},
): FormattedValue {
  const unavailable = options.unavailableText ?? UNAVAILABLE_TEXT;
  if (!interval || interval.lower === null || interval.upper === null) {
    const spec = tryChannel(channelName);
    return {
      value: null,
      unit: spec?.displayUnit ?? interval?.unit ?? null,
      text: unavailable,
      available: false,
    };
  }
  const low = formatChannelValue(channelName, interval.lower, options);
  const high = formatChannelValue(channelName, interval.upper, options);
  if (!low.available || !high.available) {
    return { value: null, unit: low.unit, text: unavailable, available: false };
  }
  const unit = low.unit === null ? '' : ` ${low.unit}`;
  return {
    value: `${low.value} – ${high.value}`,
    unit: low.unit,
    text: `${low.value} – ${high.value}${unit}`,
    available: true,
  };
}

/** Human wording for an age in seconds. Null age is unknown, not "0 s ago". */
export function formatAge(ageS: number | null | undefined): string {
  if (ageS === null || ageS === undefined || !Number.isFinite(ageS) || ageS < 0) {
    return 'age unknown';
  }
  if (ageS < 1) {
    return `${(ageS * 1000).toFixed(0)} ms ago`;
  }
  if (ageS < 60) {
    return `${ageS.toFixed(1)} s ago`;
  }
  const minutes = Math.floor(ageS / 60);
  const seconds = Math.round(ageS % 60);
  return `${minutes} min ${seconds} s ago`;
}

export const PROVENANCE_TEXT: Record<Provenance, string> = {
  measured: 'measured',
  estimated: 'estimated',
  configured: 'configured',
  simulated: 'simulated',
};

export const QUALITY_TEXT: Record<Quality, string> = {
  valid: 'valid',
  degraded: 'degraded',
  stale: 'stale',
  missing: 'missing',
  invalid: 'invalid',
};

/**
 * Quality values that make a time-sensitive action unsafe. A recommendation
 * cannot be acted on when the evidence behind it is stale, missing or invalid.
 */
export const BLOCKING_QUALITIES: readonly Quality[] = ['stale', 'missing', 'invalid'];

export function isBlockingQuality(quality: Quality | null | undefined): boolean {
  return quality !== null && quality !== undefined && BLOCKING_QUALITIES.includes(quality);
}

/** Unit shown for a channel without formatting a value. */
export function channelUnit(channelName: string): string | null {
  return tryChannel(channelName)?.displayUnit ?? null;
}

export function channelLabel(spec: ChannelSpec): string {
  return `${spec.name} (${spec.displayUnit})`;
}
