
export const CURRENT_RULESET = 'current';

export interface ModuleLink {
  readonly to: string;
  readonly label: string;
  
  readonly matches?: readonly string[];
  readonly needsSession?: boolean;
}

export interface ModuleGroup {
  readonly label: string;
  readonly links: readonly ModuleLink[];
}

export function moduleGroups(
  sessionId: string | null,
  rulesetHash: string | null = null,
): readonly ModuleGroup[] {
  const sessionBase = sessionId === null ? null : `/sessions/${sessionId}`;
  return [
    {
      label: 'Workspace',
      links: [
        { to: '/sessions', label: 'Sessions' },
        ...(sessionBase === null
          ? [{ to: '/lab', label: 'Simulation lab' }]
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
        { to: `/rulesets/${rulesetHash ?? CURRENT_RULESET}`, label: 'Rules' },
      ],
    },
    {
      label: 'Preferences',
      links: [{ to: '/settings', label: 'Settings' }],
    },
  ];
}
