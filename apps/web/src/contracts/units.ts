
import type { IntervalValue, Provenance, Quality, ScalarValue } from '@contracts';

import { toDisplay, tryChannel, type ChannelSpec } from './channels';


export const UNAVAILABLE_TEXT = 'not available';

export interface FormattedValue {
  
  readonly value: string | null;
  
  readonly unit: string | null;
  
  readonly text: string;
  readonly available: boolean;
}

function formatNumber(n: number, decimals: number): string {
  if (!Number.isFinite(n)) {
    return UNAVAILABLE_TEXT;
  }
  const text = n.toFixed(decimals);


  return Number(text) === 0 ? text.replace(/^-/, '') : text;
}

export interface FormatOptions {
  
  readonly decimals?: number;
  
  readonly fallbackUnit?: string | null;
  
  readonly unavailableText?: string;
}


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


export function formatInterval(
  channelName: string,
  interval: IntervalValue | null | undefined,
  options: FormatOptions = {},
): FormattedValue {
  const unavailable = options.unavailableText ?? UNAVAILABLE_TEXT;
  if (
    interval?.lower === null ||
    interval?.lower === undefined ||
    interval?.upper === null ||
    interval?.upper === undefined
  ) {
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


export const BLOCKING_QUALITIES: readonly Quality[] = ['stale', 'missing', 'invalid'];

export function isBlockingQuality(quality: Quality | null | undefined): boolean {
  return quality !== null && quality !== undefined && BLOCKING_QUALITIES.includes(quality);
}


export function channelUnit(channelName: string): string | null {
  return tryChannel(channelName)?.displayUnit ?? null;
}

export function channelLabel(spec: ChannelSpec): string {
  return `${spec.name} (${spec.displayUnit})`;
}
