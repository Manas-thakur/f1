import { useState } from 'react';

import { Button } from '../components/Button';
import { Dialog } from '../components/Dialog';
import { Notice, Panel } from '../components/Panel';
import { ValueReadout } from '../components/ValueReadout';
import { useSessionStore } from '../state/sessionStore';
import type { Density, MotionPreference } from '../state/types';
import styles from '../app/shell.module.css';

const DENSITY_OPTIONS: readonly { value: Density; label: string; description: string }[] = [
  {
    value: 'comfortable',
    label: 'Comfortable',
    description: 'Default spacing. Best for a desk monitor at a normal viewing distance.',
  },
  {
    value: 'compact',
    label: 'Compact',
    description: 'Tighter spacing so more channels fit on one screen. Type sizes do not change.',
  },
];

const MOTION_OPTIONS: readonly { value: MotionPreference; label: string; description: string }[] = [
  {
    value: 'system',
    label: 'Follow the operating system',
    description: 'Uses the browser prefers-reduced-motion setting.',
  },
  {
    value: 'reduce',
    label: 'Reduce motion',
    description: 'Disables every non-essential transition regardless of the system setting.',
  },
];

/** `/settings` — density and reduced-motion preferences, with a live preview. */
export function SettingsPage() {
  const density = useSessionStore((s) => s.view.density);
  const motion = useSessionStore((s) => s.view.motion);
  const setDensity = useSessionStore((s) => s.setDensity);
  const setMotion = useSessionStore((s) => s.setMotion);
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <>
      <div className={styles.pageHead}>
        <div>
          <h1>Settings</h1>
          <p>
            Presentation preferences only. Nothing on this page changes simulation state, a
            recommendation, or what the server records.
          </p>
        </div>
      </div>

      <div className={styles.workArea}>
        <div className={styles.stack}>
          <Panel id="density" title="Display density">
            <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="afterlap-visually-hidden">Display density</legend>
              {DENSITY_OPTIONS.map((option) => (
                <div key={option.value} style={{ marginBottom: 'var(--s3)' }}>
                  <label style={{ display: 'flex', gap: 'var(--s2)', alignItems: 'baseline' }}>
                    <input
                      type="radio"
                      name="density"
                      value={option.value}
                      checked={density === option.value}
                      onChange={() => setDensity(option.value)}
                    />
                    <span>
                      <strong>{option.label}</strong>
                      <br />
                      <span className="afterlap-muted afterlap-small">{option.description}</span>
                    </span>
                  </label>
                </div>
              ))}
            </fieldset>
          </Panel>

          <Panel id="motion" title="Motion">
            <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="afterlap-visually-hidden">Motion preference</legend>
              {MOTION_OPTIONS.map((option) => (
                <div key={option.value} style={{ marginBottom: 'var(--s3)' }}>
                  <label style={{ display: 'flex', gap: 'var(--s2)', alignItems: 'baseline' }}>
                    <input
                      type="radio"
                      name="motion"
                      value={option.value}
                      checked={motion === option.value}
                      onChange={() => setMotion(option.value)}
                    />
                    <span>
                      <strong>{option.label}</strong>
                      <br />
                      <span className="afterlap-muted afterlap-small">{option.description}</span>
                    </span>
                  </label>
                </div>
              ))}
            </fieldset>
          </Panel>
        </div>

        <div className={styles.stack}>
          <Panel id="preview" title="Preview" headingLevel={2}>
            <p className="afterlap-muted afterlap-small" style={{ marginBottom: 'var(--s3)' }}>
              These are the shared primitives at the current preference. The right-hand readout
              has no value, so it shows the unavailable text rather than a zero.
            </p>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
                gap: 'var(--s4)',
                marginBottom: 'var(--s4)',
              }}
            >
              <ValueReadout
                label="Stored energy"
                channel="battery_energy_j"
                value={2_940_000}
                provenance="simulated"
                quality="valid"
                ageS={0.2}
              />
              <ValueReadout
                label="Rival stored energy"
                channel="battery_energy_j"
                value={null}
                provenance="estimated"
                quality="missing"
                ageS={null}
                unavailableReason="No feed publishes this quantity."
              />
            </div>
            <Button
              id="settings-open-dialog"
              variant="primary"
              onClick={() => setDialogOpen(true)}
            >
              Open a sample inspector
            </Button>
          </Panel>

          <Notice>
            Preferences are held for this browser session only. They are not sent to the server
            and they are not part of any recorded decision.
          </Notice>
        </div>
      </div>

      <Dialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="Sample inspector"
        description="Escape closes this dialog and focus returns to the control that opened it."
        returnFocusTo="settings-open-dialog"
        footer={
          <Button onClick={() => setDialogOpen(false)} variant="primary">
            Done
          </Button>
        }
      >
        <p>
          The inspector pattern used across the workspace: a titled dialog with a close control,
          Escape handling and focus restoration. Feature routes fill it with the selected
          decision&apos;s observed state, candidate comparison, source labels, rule results and
          expiry.
        </p>
      </Dialog>
    </>
  );
}
