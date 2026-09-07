/**
 * The module rail.
 *
 * Plain named modules. There is deliberately no numbering: the operator's
 * workflow has no single ordering, and numbers would assert one.
 */
export interface ModuleLink {
  readonly to: string;
  readonly label: string;
  /** Route patterns that should also mark this module selected. */
  readonly matches?: readonly string[];
  readonly needsSession?: boolean;
}

export interface ModuleGroup {
  readonly label: string;
  readonly links: readonly ModuleLink[];
}

export function moduleGroups(sessionId: string | null): readonly ModuleGroup[] {
  const sessionBase = sessionId === null ? null : `/sessions/${sessionId}`;
  return [
    {
      label: 'Workspace',
      links: [
        { to: '/sessions', label: 'Sessions' },
        ...(sessionBase === null
          ? []
          : [
              { to: `${sessionBase}/engineer`, label: 'Engineer console' },
              { to: `${sessionBase}/lab`, label: 'Simulation lab' },
              { to: `${sessionBase}/replay`, label: 'Replay' },
              { to: `${sessionBase}/driver`, label: 'Driver display' },
            ]),
      ],
    },
    {
      label: 'Evidence',
      links: [
        { to: '/models', label: 'Models' },
        { to: '/rulesets/current', label: 'Rules' },
      ],
    },
    {
      label: 'Preferences',
      links: [{ to: '/settings', label: 'Settings' }],
    },
  ];
}
