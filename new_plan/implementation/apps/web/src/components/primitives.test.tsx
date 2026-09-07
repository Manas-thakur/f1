import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { Button, type ButtonState } from './Button';
import { DataTable, type Column } from './DataTable';
import { Dialog } from './Dialog';
import { EmptyState } from './EmptyState';
import { Field } from './Field';
import { ProvenanceLabel } from './ProvenanceLabel';
import { QualityIndicator } from './QualityIndicator';
import { StatusBadge, checkTone, recommendationTone } from './StatusBadge';
import { ValueReadout } from './ValueReadout';
import { UNAVAILABLE_TEXT } from '../contracts/units';

describe('Button implements every declared state', () => {
  const states: readonly ButtonState[] = ['default', 'pending', 'error', 'success', 'disabled'];

  for (const state of states) {
    it(`renders the ${state} state`, () => {
      render(
        <Button
          state={state}
          disabledReason="A stale battery-energy channel blocks time-sensitive actions."
          errorMessage="Selection failed: the session revision moved. Review the refreshed evidence."
          successMessage="Recommendation marked selected."
        >
          Select recommendation
        </Button>,
      );
      const button = screen.getByRole('button');
      expect(button).toHaveAttribute('data-state', state);

      if (state === 'pending') {
        expect(button).toBeDisabled();
        expect(button).toHaveAttribute('aria-busy', 'true');
        expect(button).toHaveTextContent('Working…');
      } else if (state === 'disabled') {
        expect(button).toBeDisabled();
        expect(screen.getByText(/stale battery-energy channel/)).toBeInTheDocument();
      } else if (state === 'error') {
        expect(screen.getByText(/Review the refreshed evidence/)).toBeInTheDocument();
      } else if (state === 'success') {
        expect(screen.getByText('Recommendation marked selected.')).toBeInTheDocument();
      } else {
        expect(button).toBeEnabled();
      }
    });
  }

  it('is reachable and operable from the keyboard', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Mark communicated</Button>);
    await user.tab();
    expect(screen.getByRole('button')).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('never fires while pending', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <Button state="pending" onClick={onClick}>
        Select
      </Button>,
    );
    await user.click(screen.getByRole('button'));
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe('StatusBadge', () => {
  const tones = ['neutral', 'selection', 'verified', 'failure', 'attention', 'reference'] as const;

  for (const tone of tones) {
    it(`renders the ${tone} tone with its text`, () => {
      render(
        <StatusBadge tone={tone} label="Status">
          {tone}
        </StatusBadge>,
      );
      expect(screen.getByText(tone)).toBeInTheDocument();
    });
  }

  it('keeps a proposed recommendation neutral and unknown checks neutral', () => {
    expect(recommendationTone('proposed')).toBe('neutral');
    expect(recommendationTone('selected')).toBe('selection');
    expect(recommendationTone('invalidated')).toBe('failure');
    expect(checkTone('unknown')).toBe('neutral');
    expect(checkTone('pass')).toBe('verified');
    expect(checkTone('fail')).toBe('failure');
  });
});

describe('Field implements every declared state', () => {
  const states = ['default', 'pending', 'error', 'success', 'disabled'] as const;

  for (const state of states) {
    it(`renders the ${state} state with a real label`, () => {
      render(
        <Field
          label="Terminal energy target"
          hint="Joules at the end of the horizon."
          state={state}
          errorMessage="Value is above the ruleset maximum of 4.00 MJ."
          successMessage="Applied to the next solve."
        >
          <input type="number" defaultValue={1000} />
        </Field>,
      );
      const input = screen.getByLabelText(/Terminal energy target/);
      expect(input).toBeInTheDocument();
      if (state === 'disabled') {
        expect(input).toBeDisabled();
      }
      if (state === 'error') {
        expect(input).toHaveAttribute('aria-invalid', 'true');
        expect(screen.getByRole('alert')).toHaveTextContent('4.00 MJ');
      }
      if (state === 'success') {
        expect(screen.getByText('Applied to the next solve.')).toBeInTheDocument();
      }
    });
  }
});

interface Row {
  readonly id: string;
  readonly power: number | null;
}

const COLUMNS: readonly Column<Row>[] = [
  { id: 'id', header: 'Segment', cell: (r) => r.id },
  {
    id: 'power',
    header: 'Requested power',
    unit: 'kW',
    numeric: true,
    cell: (r) => (r.power === null ? UNAVAILABLE_TEXT : String(r.power / 1000)),
  },
];

describe('DataTable', () => {
  it('renders real column headers with scope and units', () => {
    render(
      <DataTable
        caption="Profile segments"
        columns={COLUMNS}
        rows={[{ id: 'seg-1', power: 350_000 }]}
        rowKey={(r) => r.id}
      />,
    );
    const header = screen.getByRole('columnheader', { name: /Requested power/ });
    expect(header).toHaveAttribute('scope', 'col');
    expect(header).toHaveTextContent('kW');
  });

  it('scrolls inside a labelled region rather than widening the page', () => {
    render(
      <DataTable
        caption="Profile segments"
        columns={COLUMNS}
        rows={[{ id: 'seg-1', power: 350_000 }]}
        rowKey={(r) => r.id}
      />,
    );
    const region = screen.getByRole('region', { name: 'Profile segments' });
    expect(region).toHaveAttribute('tabindex', '0');
    expect(within(region).getByRole('table')).toBeInTheDocument();
  });

  it('distinguishes pending, error and empty', () => {
    const { rerender } = render(
      <DataTable
        caption="Profile segments"
        columns={COLUMNS}
        rows={[]}
        rowKey={(r) => r.id}
        state="pending"
      />,
    );
    expect(screen.getByText(/Loading profile segments/)).toBeInTheDocument();

    rerender(
      <DataTable
        caption="Profile segments"
        columns={COLUMNS}
        rows={[]}
        rowKey={(r) => r.id}
        state="error"
        errorMessage="Rule coverage unavailable."
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Rule coverage unavailable.');

    rerender(
      <DataTable
        caption="Profile segments"
        columns={COLUMNS}
        rows={[]}
        rowKey={(r) => r.id}
        emptyArtefact="candidate plan"
      />,
    );
    expect(screen.getByText(/missing artefact: candidate plan/)).toBeInTheDocument();
  });

  it('shows an unavailable cell as text, not as zero', () => {
    render(
      <DataTable
        caption="Profile segments"
        columns={COLUMNS}
        rows={[{ id: 'seg-2', power: null }]}
        rowKey={(r) => r.id}
      />,
    );
    const cell = screen.getByRole('cell', { name: UNAVAILABLE_TEXT });
    expect(cell).toBeInTheDocument();
    expect(cell).not.toHaveTextContent('0');
  });
});

describe('ValueReadout', () => {
  it('renders unavailable text and never "0" when the value is null', () => {
    render(
      <ValueReadout
        label="Rival stored energy"
        channel="battery_energy_j"
        value={null}
        provenance="estimated"
        quality="missing"
        ageS={null}
        unavailableReason="No public feed publishes a rival battery state."
      />,
    );
    expect(screen.getByText(UNAVAILABLE_TEXT)).toBeInTheDocument();
    expect(screen.queryByText('0')).toBeNull();
    expect(screen.queryByText('0.00')).toBeNull();
    expect(screen.queryByText(/^0\.00 MJ$/)).toBeNull();
    expect(screen.getByText(/No public feed publishes/)).toBeInTheDocument();
    expect(screen.getByText('missing')).toBeInTheDocument();
    expect(screen.getByText('age unknown')).toBeInTheDocument();
  });

  it('renders a real value with its display unit and provenance', () => {
    render(
      <ValueReadout
        label="Stored energy"
        channel="battery_energy_j"
        value={2_940_000}
        provenance="simulated"
        quality="valid"
        ageS={0.2}
      />,
    );
    expect(screen.getByText('2.94')).toBeInTheDocument();
    expect(screen.getByText('MJ')).toBeInTheDocument();
    expect(screen.getByText('simulated')).toBeInTheDocument();
    expect(screen.getByText('200 ms ago')).toBeInTheDocument();
  });

  it('distinguishes empty, missing, estimated, stale, invalid and pending', () => {
    const cases = [
      { value: null as number | null, quality: 'missing' as const, expected: 'missing' },
      { value: 1_000_000, quality: 'stale' as const, expected: 'stale' },
      { value: 1_000_000, quality: 'invalid' as const, expected: 'invalid' },
      { value: 1_000_000, quality: 'valid' as const, expected: 'estimated' },
    ];
    for (const testCase of cases) {
      const { container, unmount } = render(
        <ValueReadout
          label="Energy"
          channel="battery_energy_j"
          value={testCase.value}
          provenance="estimated"
          quality={testCase.quality}
          ageS={1}
        />,
      );
      expect(container.querySelector(`[data-state="${testCase.expected}"]`)).not.toBeNull();
      unmount();
    }

    const { container } = render(
      <ValueReadout label="Energy" channel="battery_energy_j" value={null} state="pending" />,
    );
    expect(container.querySelector('[data-state="pending"]')).not.toBeNull();
    expect(screen.getByText('reading…')).toBeInTheDocument();
  });
});

describe('QualityIndicator and ProvenanceLabel carry meaning without colour', () => {
  it('renders unknown quality as the word unknown, not an empty check', () => {
    render(<QualityIndicator quality={null} />);
    expect(screen.getByText('unknown')).toBeInTheDocument();
  });

  for (const quality of ['valid', 'degraded', 'stale', 'missing', 'invalid'] as const) {
    it(`renders ${quality} as text`, () => {
      render(<QualityIndicator quality={quality} />);
      expect(screen.getByText(quality)).toBeInTheDocument();
    });
  }

  it('says provenance unknown rather than guessing', () => {
    render(<ProvenanceLabel provenance={null} />);
    expect(screen.getByText('provenance unknown')).toBeInTheDocument();
  });

  it('shows source and age when asked', () => {
    render(<ProvenanceLabel provenance="measured" sourceId="synthetic-simulator" ageS={2} showAge />);
    expect(screen.getByText('measured')).toBeInTheDocument();
    expect(screen.getByText('· synthetic-simulator')).toBeInTheDocument();
    expect(screen.getByText('· 2.0 s ago')).toBeInTheDocument();
  });
});

describe('EmptyState', () => {
  it('names the missing artefact and the action that would create it', () => {
    render(
      <EmptyState
        artefact="immutable snapshot"
        reason="No snapshot has been taken for this session."
        action={<button type="button">Take a snapshot</button>}
      />,
    );
    expect(screen.getByText(/missing artefact: immutable snapshot/)).toBeInTheDocument();
    expect(screen.getByText('No snapshot has been taken for this session.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Take a snapshot' })).toBeInTheDocument();
  });
});

function DialogHarness({ blockOutsideClose = false }: { blockOutsideClose?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button id="open-evidence" onClick={() => setOpen(true)}>
        Open evidence
      </Button>
      <Button id="other-control">Other control</Button>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title="Decision evidence"
        description="Observed state, candidate comparison, rule results and expiry."
        returnFocusTo="open-evidence"
        blockOutsideClose={blockOutsideClose}
      >
        <p>Evidence body</p>
      </Dialog>
    </>
  );
}

describe('Dialog', () => {
  it('closes on Escape and restores focus to the invoking control', async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);

    const invoker = screen.getByRole('button', { name: 'Open evidence' });
    await user.click(invoker);

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByRole('heading', { name: 'Decision evidence' })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Close dialog' })).toBeInTheDocument();

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(invoker).toHaveFocus();
  });

  it('restores focus after the close control is used', async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    const invoker = screen.getByRole('button', { name: 'Open evidence' });
    await user.click(invoker);
    await user.click(await screen.findByRole('button', { name: 'Close dialog' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(invoker).toHaveFocus();
  });

  it('keeps focus inside the modal', async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    await user.click(screen.getByRole('button', { name: 'Open evidence' }));
    const dialog = await screen.findByRole('dialog');

    for (let i = 0; i < 6; i += 1) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
    // Radix marks everything outside the modal aria-hidden, so the control
    // behind it is not even exposed to assistive technology while it is open.
    const outside = screen.getByRole('button', { name: 'Other control', hidden: true });
    expect(outside).not.toHaveFocus();
    expect(outside.closest('[aria-hidden="true"]')).not.toBeNull();
  });
});
