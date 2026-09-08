import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';

import { tryChannel } from '../../contracts/channels';
import { formatChannelValue } from '../../contracts/units';
import { EmptyState } from '../EmptyState';
import {
  axesSummary,
  axisSizeFor,
  formatXTick,
  formatYTick,
  toDisplayValue,
  unitGroupsFor,
  xAxisLabel,
} from './axes';
import styles from './chart.module.css';
import { decimateMinMax, interpolateAt } from './decimate';
import { summariseSeries } from './summary';
import type { ChartSeries, EventMarker } from './types';

export interface ChartFrameProps {
  readonly title: string;
  readonly subtitle?: string;
  readonly series: readonly ChartSeries[];
  readonly height?: number;
  /** Shared cursor value on the series' x axis. */
  readonly cursor?: number | null;
  readonly onCursorChange?: (value: number | null) => void;
  /** Maximum points drawn per series before min/max decimation kicks in. */
  readonly maxPoints?: number;
  readonly emptyArtefact?: string;
  readonly emptyAction?: ReactNode;
  readonly actions?: ReactNode;
}

const WELL_COLOUR_FALLBACK = '#6ba7f2';

/** Read a design token, so the plot never carries its own hard-coded palette. */
function token(name: string, fallback: string): string {
  if (typeof globalThis.getComputedStyle !== 'function' || typeof document === 'undefined') {
    return fallback;
  }
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value === '' ? fallback : value;
}

function resolveColour(channel: string): string {
  const spec = tryChannel(channel);
  if (spec === null || spec === undefined) {
    return WELL_COLOUR_FALLBACK;
  }
  // The lighter shade of the same hue, so legend meaning survives the dark well.
  return token(`${spec.plotColourToken}-well`, WELL_COLOUR_FALLBACK);
}

/**
 * Drawable width of the plot mount.
 *
 * The mount is absolutely positioned inside the trace well, so its width comes
 * from the container and never from the canvas uPlot puts inside it.
 */
function availableWidth(mount: HTMLElement): number {
  return Math.max(160, Math.floor(mount.clientWidth || 640));
}

/**
 * Whether this environment can actually paint a 2D canvas.
 *
 * jsdom returns null from `getContext('2d')` and uPlot only discovers that on
 * its first animation frame, well outside any try/catch around the
 * constructor. Probing up front keeps the failure synchronous and lets the
 * panel fall back to its numeric summary instead of throwing asynchronously.
 */
function canPaintCanvas(): boolean {
  if (typeof document === 'undefined') {
    return false;
  }
  try {
    return document.createElement('canvas').getContext('2d') !== null;
  } catch {
    return false;
  }
}

/**
 * One plot panel.
 *
 * Three things this component is responsible for that a plotting library does
 * not give for free:
 *   1. decimation that preserves extrema and event crossings exactly, and says
 *      so, together with the original sampling resolution;
 *   2. a keyboard-operable alternative to the mouse cursor, driving the same
 *      shared x position as every other panel;
 *   3. a textual numeric summary, so the chart is reviewable without sight.
 *
 * The canvas itself is `aria-hidden`: it is a picture of the table below it.
 */
export function ChartFrame({
  title,
  subtitle,
  series,
  height = 220,
  cursor = null,
  onCursorChange,
  maxPoints = 900,
  emptyArtefact = 'telemetry series',
  emptyAction,
  actions,
}: ChartFrameProps) {
  const id = useId();
  const wellRef = useRef<HTMLDivElement | null>(null);
  const plotRef = useRef<uPlot | null>(null);
  const [plotAvailable, setPlotAvailable] = useState(true);

  const axis = series[0]?.xCoordinate ?? 'progress_m';

  const prepared = useMemo(
    () =>
      series.map((s) => {
        const preserveX = (s.events ?? [])
          .filter((e) => e.preserveExactly !== false)
          .map((e) => e.x);
        const result = decimateMinMax({ x: s.x, y: s.y, maxPoints, preserveX });
        return { series: s, decimated: result };
      }),
    [series, maxPoints],
  );

  const unitGroups = useMemo(() => unitGroupsFor(series), [series]);

  const domain = useMemo(() => {
    let min = Number.POSITIVE_INFINITY;
    let max = Number.NEGATIVE_INFINITY;
    for (const s of series) {
      if (s.x.length === 0) continue;
      min = Math.min(min, s.x[0] as number);
      max = Math.max(max, s.x[s.x.length - 1] as number);
    }
    return Number.isFinite(min) && Number.isFinite(max) ? { min, max } : null;
  }, [series]);

  const step = useMemo(() => {
    if (domain === null) return 1;
    const spread = domain.max - domain.min;
    if (spread <= 0) return 1;
    return Number((spread / 200).toPrecision(2));
  }, [domain]);

  useEffect(() => {
    const mount = wellRef.current;
    if (mount === null || prepared.length === 0 || domain === null) {
      return;
    }
    if (!canPaintCanvas()) {
      setPlotAvailable(false);
      return;
    }
    // Build one shared x grid by unioning every series' decimated x values, so
    // uPlot can align traces that were sampled independently. Y values are
    // converted to their display unit here, so the painted axis, the legend and
    // the summary table all read in the same unit.
    const xs = [...new Set(prepared.flatMap((p) => p.decimated.x))].sort((a, b) => a - b);
    const data: uPlot.AlignedData = [
      xs,
      ...prepared.map((p) =>
        xs.map((xv) => {
          const found = p.decimated.x.indexOf(xv);
          const si =
            found >= 0
              ? (p.decimated.y[found] ?? null)
              : interpolateAt(p.decimated.x, p.decimated.y, xv).value;
          return toDisplayValue(p.series.channel, si);
        }),
      ),
    ] as uPlot.AlignedData;

    const axisInk = token('--well-muted', '#afb9c2');
    const gridInk = token('--well-grid', '#2b363f');
    const axisFont = '12px "Segoe UI", Arial, sans-serif';
    const width = availableWidth(mount);
    const scaleKeyBySeries = new Map<number, string>();
    for (const group of unitGroups) {
      for (const index of group.seriesIndices) {
        scaleKeyBySeries.set(index, group.key);
      }
    }

    let instance: uPlot | null = null;
    let observer: ResizeObserver | null = null;
    try {
      instance = new uPlot(
        {
          width,
          height: mount.clientHeight || height,
          padding: [8, 12, 4, 4],
          legend: { show: false },
          cursor: { show: true, x: true, y: false },
          // The x coordinate is distance or session time, never a timestamp.
          // Without this uPlot formats it as a wall-clock time on 1/1/70.
          scales: { x: { time: false } },
          axes: [
            {
              scale: 'x',
              stroke: axisInk,
              font: axisFont,
              labelFont: axisFont,
              label: xAxisLabel(axis),
              labelSize: 22,
              size: 46,
              grid: { stroke: gridInk },
              ticks: { stroke: gridInk },
              values: (_self, splits) => splits.map((v) => formatXTick(v, axis)),
            },
            ...unitGroups.map((group) => ({
              scale: group.key,
              side: group.side,
              stroke: axisInk,
              font: axisFont,
              labelFont: axisFont,
              label: group.unit,
              labelSize: 20,
              // Reserve room from the widest label actually produced, so no
              // tick is clipped at its leading digit.
              size: (_self: uPlot, values: string[] | null) =>
                axisSizeFor(values ?? [], group.unit),
              grid: { show: group.side === 3, stroke: gridInk },
              ticks: { stroke: gridInk },
              values: (_self: uPlot, splits: number[]) =>
                splits.map((v) => formatYTick(v, group.decimals)),
            })),
          ],
          series: [
            {},
            ...prepared.map((p, index) => ({
              label: p.series.label,
              scale: scaleKeyBySeries.get(index) ?? 'y',
              stroke: resolveColour(p.series.channel),
              width: p.series.role === 'reference' ? 1.5 : 2,
              ...(p.series.role === 'reference' ? { dash: [6, 4] } : {}),
              spanGaps: false,
            })),
          ],
        },
        data,
        mount,
      );
      plotRef.current = instance;
      setPlotAvailable(true);
      // Keep the canvas inside its container when the viewport changes; a
      // fixed-width canvas is the classic source of horizontal page overflow.
      if (typeof ResizeObserver === 'function') {
        observer = new ResizeObserver(() => {
          const plot = plotRef.current;
          if (plot !== null) {
            plot.setSize({ width: availableWidth(mount), height: mount.clientHeight || height });
          }
        });
        observer.observe(mount);
      }
    } catch {
      // jsdom and headless environments without a 2D canvas context cannot
      // paint. The accessible summary below is the source of truth anyway, so
      // the panel degrades to it rather than failing.
      setPlotAvailable(false);
    }

    return () => {
      observer?.disconnect();
      instance?.destroy();
      plotRef.current = null;
    };
  }, [prepared, domain, height, axis, unitGroups]);

  const summaries = useMemo(() => series.map(summariseSeries), [series]);

  // Two series may carry the same checkpoint. List each marker once.
  const markers = useMemo(() => {
    const byId = new Map<string, EventMarker>();
    for (const s of series) {
      for (const event of s.events ?? []) {
        byId.set(`${event.kind}-${event.id}`, event);
      }
    }
    return [...byId.values()].sort((a, b) => a.x - b.x);
  }, [series]);

  if (series.length === 0) {
    return (
      <figure className={styles.frame} aria-labelledby={`${id}-title`}>
        <figcaption className={styles.head}>
          <div>
            <h3 className={styles.title} id={`${id}-title`}>
              {title}
            </h3>
            {subtitle === undefined ? null : <p className={styles.subtitle}>{subtitle}</p>}
          </div>
          {actions}
        </figcaption>
        <div style={{ padding: 'var(--s4)' }}>
          <EmptyState
            artefact={emptyArtefact}
            heading="No series to plot"
            reason="No channel has delivered samples for this panel's x range."
            action={emptyAction}
          />
        </div>
      </figure>
    );
  }

  const cursorValue = cursor ?? domain?.min ?? 0;

  return (
    <figure className={styles.frame} aria-labelledby={`${id}-title`}>
      <figcaption className={styles.head}>
        <div>
          <h3 className={styles.title} id={`${id}-title`}>
            {title}
          </h3>
          <p className={styles.subtitle}>
            {axesSummary(axis, unitGroups)}
            {subtitle === undefined ? '' : ` — ${subtitle}`}
          </p>
        </div>
        {actions}
      </figcaption>

      <ul className={styles.legend}>
        {series.map((s) => {
          const spec = tryChannel(s.channel);
          return (
            <li key={s.id} className={styles.legendItem}>
              <span
                className={styles.swatch}
                data-role={s.role}
                style={{
                  borderTopColor: spec
                    ? `var(${spec.plotColourToken})`
                    : 'var(--series-progress)',
                }}
                aria-hidden="true"
              />
              <span>
                {s.label} ({spec?.displayUnit ?? s.unit}, {s.provenance}
                {s.role === 'reference' ? ', reference, dashed' : ''})
              </span>
            </li>
          );
        })}
      </ul>

      <div className={styles.well} style={{ height }}>
        <div className={styles.wellPlot} ref={wellRef} aria-hidden="true" />
        {plotAvailable ? null : (
          <p className={styles.wellFallback}>
            Plot canvas unavailable in this environment. The numeric summary below carries the
            same data.
          </p>
        )}
      </div>

      {domain === null ? null : (
        <div className={styles.cursorRow}>
          <label htmlFor={`${id}-cursor`}>
            Shared cursor position ({xAxisLabel(axis)})
          </label>
          <input
            id={`${id}-cursor`}
            className={styles.cursorSlider}
            type="range"
            min={domain.min}
            max={domain.max}
            step={step}
            value={cursorValue}
            aria-valuetext={`${cursorValue.toFixed(1)} ${axis === 'progress_m' ? 'metres' : 'seconds'}`}
            onChange={(event) => onCursorChange?.(Number(event.target.value))}
          />
          <div className={styles.cursorReadouts}>
            {prepared.map(({ series: s }) => {
              const at = interpolateAt(s.x, s.y, cursorValue);
              const formatted = formatChannelValue(s.channel, at.value);
              return (
                <span key={s.id}>
                  {s.label}: {formatted.text}
                  {at.value === null ? '' : at.exact ? ' (sample)' : ' (interpolated)'}
                </span>
              );
            })}
          </div>
        </div>
      )}

      <details className={styles.summary}>
        <summary>Numeric summary and sampling detail</summary>
        <div className={styles.summaryTableScroll} role="region" aria-label={`${title} numeric summary`} tabIndex={0}>
          <table className={styles.summaryTable}>
            <caption className="afterlap-visually-hidden">{title} numeric summary</caption>
            <thead>
              <tr>
                <th scope="col">Series</th>
                <th scope="col">Provenance</th>
                <th scope="col">Role</th>
                <th scope="col" className={styles.numeric}>
                  Minimum
                </th>
                <th scope="col" className={styles.numeric}>
                  Maximum
                </th>
                <th scope="col" className={styles.numeric}>
                  Mean
                </th>
                <th scope="col" className={styles.numeric}>
                  Last
                </th>
                <th scope="col">x range</th>
                <th scope="col">Sampling</th>
                <th scope="col">Band</th>
              </tr>
            </thead>
            <tbody>
              {summaries.map((s) => (
                <tr key={s.id}>
                  <th scope="row">{s.label}</th>
                  <td>{s.provenance}</td>
                  <td>{s.role}</td>
                  <td className={styles.numeric}>{s.minText}</td>
                  <td className={styles.numeric}>{s.maxText}</td>
                  <td className={styles.numeric}>{s.meanText}</td>
                  <td className={styles.numeric}>{s.lastText}</td>
                  <td>
                    {s.xFromText} to {s.xToText}
                  </td>
                  <td>
                    {s.nativeResolutionText}
                    {s.decimated ? '; min/max envelope drawn' : ''}
                    {s.gapCount > 0 ? `; ${s.gapCount} gaps` : ''}
                  </td>
                  <td>{s.quantileDefinition ?? 'none'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      {markers.length === 0 ? null : (
        <ul className={styles.eventList}>
          {markers.map((event) => (
            <li key={`${event.kind}-${event.id}`}>
              {event.kind}: {event.label} at {event.x.toFixed(0)}
            </li>
          ))}
        </ul>
      )}
    </figure>
  );
}
