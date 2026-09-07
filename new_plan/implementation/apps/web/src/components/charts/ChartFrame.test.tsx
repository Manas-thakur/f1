import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { specimenSeries } from '../../fixtures/specimen';
import { ChartFrame } from './ChartFrame';
import type { ChartSeries } from './types';

const SERIES = specimenSeries();

describe('ChartFrame', () => {
  it('exposes a textual numeric summary with units and provenance', () => {
    render(<ChartFrame title="Deployment" series={SERIES} />);

    const summary = screen.getByRole('region', { name: 'Deployment numeric summary' });
    const table = within(summary).getByRole('table');
    expect(within(table).getByRole('columnheader', { name: 'Minimum' })).toBeInTheDocument();
    expect(within(table).getByRole('columnheader', { name: 'Sampling' })).toBeInTheDocument();
    // Values are rendered in display units, not SI.
    expect(within(table).getAllByText(/kW$/).length).toBeGreaterThan(0);
    expect(within(table).getAllByText('simulated').length).toBe(SERIES.length);
  });

  it('states the original sampling resolution and whether it decimated', () => {
    render(<ChartFrame title="Deployment" series={SERIES} maxPoints={40} />);
    const summary = screen.getByRole('region', { name: 'Deployment numeric summary' });
    expect(within(summary).getAllByText(/per sample/).length).toBe(SERIES.length);
  });

  it('names the reference series in the legend and marks it dashed', () => {
    const { container } = render(<ChartFrame title="Deployment" series={SERIES} />);
    expect(screen.getByText(/Reference lap deployment.*reference, dashed/)).toBeInTheDocument();
    expect(container.querySelector('[data-role="reference"]')).not.toBeNull();
  });

  it('offers a labelled keyboard slider for the shared cursor', async () => {
    const user = userEvent.setup();
    const onCursorChange = vi.fn();
    render(
      <ChartFrame
        title="Deployment"
        series={SERIES}
        cursor={2000}
        onCursorChange={onCursorChange}
      />,
    );

    const slider = screen.getByRole('slider', { name: /Shared cursor position/ });
    expect(slider).toHaveAttribute('aria-valuetext', expect.stringContaining('metres'));

    slider.focus();
    expect(slider).toHaveFocus();
    await user.tab({ shift: true });
    slider.focus();
    fireEvent.change(slider, { target: { value: '2500' } });
    expect(onCursorChange).toHaveBeenCalledWith(2500);
  });

  it('reports at the cursor whether a value is a sample or interpolated', () => {
    render(<ChartFrame title="Deployment" series={SERIES} cursor={2000} />);
    expect(screen.getAllByText(/\(interpolated\)|\(sample\)/).length).toBeGreaterThan(0);
  });

  it('lists checkpoint and rule-transition markers as text', () => {
    render(<ChartFrame title="Deployment" series={SERIES} />);
    expect(screen.getByText(/rule_transition: Overtake profile window opens/)).toBeInTheDocument();
    expect(screen.getByText(/checkpoint: T7 entry/)).toBeInTheDocument();
  });

  it('renders a named empty state rather than a fake plot when there is no series', () => {
    render(<ChartFrame title="Deployment" series={[]} emptyArtefact="telemetry view" />);
    expect(screen.getByText(/missing artefact: telemetry view/)).toBeInTheDocument();
    expect(screen.queryByRole('slider')).toBeNull();
  });

  it('says a value is unavailable rather than plotting a zero for a gap', () => {
    const gappy: ChartSeries = {
      id: 'gap',
      channel: 'electrical_power_w',
      label: 'Gappy channel',
      unit: 'W',
      provenance: 'measured',
      xCoordinate: 'progress_m',
      x: [0, 100, 200, 300],
      y: [null, null, null, null],
      nativeResolution: 100,
      sampleCount: 4,
      decimated: false,
      role: 'selected',
    };
    render(<ChartFrame title="Gaps" series={[gappy]} cursor={150} />);
    expect(screen.getByText(/Gappy channel: not available/)).toBeInTheDocument();
  });
});
