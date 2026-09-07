# Race Engineer Console

## Responsibility

Implement `apps/web/src/features/engineer/`. Consume generated API types and the shared session reducer. Default route `/sessions/:id/engineer` shows the next decision, current battle and energy consequences. Do not implement planning or eligibility in React. Design reference: [selected operating workspace](../12_design/mockups/app.html#engineer).

## Information hierarchy

Persistent status: mode, selected car, lap, flag, data age and source quality. Main decision: action, trigger/end checkpoint, reason, expiry and operator status. Battle region: own car and relevant rivals, gap uncertainty, upcoming opportunity. Energy region: projected energy over distance with target/checkpoint, not a decorative battery gauge. Lower region: immutable decision timeline. Inspector: alternative plans, assumptions, rule coverage and predicted/observed outcome.

Use one crosshair/progress selection across energy, speed and gap plots. Series payloads retain provenance and quantile definition; downsampling must preserve extrema and event crossings. A stale source warning is independent of connection state. Operational views never expose rival truth. Do not draw collision likelihood without sufficient lateral information.

## Interaction

Select recommendation sends an idempotent command with expected revision; pending is visible. Acknowledgement changes state to selected. Separate `mark communicated` and execution observation. Reject can take a brief reason. A changed state or rule invalidates obsolete advice immediately and clears the selectable action. Open evidence preserves current session context; live plots should not jump the user's historical inspector position.

Pause in live-team mode pauses the view only and clearly says so; it must not stop acquisition. Lab simulation pause is a different authorised command. Shortcuts require focus-aware handling and must not trigger while typing. Do not auto-select a strategy from a keyboard shortcut without showing the resulting lifecycle state.

## States

Implement disconnected, connecting, healthy, degraded, stale, missing-energy, solver-timeout, no-feasible-plan, rule-unknown, no-recommendation, selected-pending, executing, completed and expired. Preserve the last observation with age when useful but remove time-sensitive advice. Empty state explains which required source is missing. Loading skeleton cannot resemble a live value.

## Acceptance

Fixture tests cover every state and a complete lifecycle. Browser tests prove no actuation on select, expiry rejection, reconnect resync, keyboard navigation, provenance visibility and common chart cursor. At desktop the recommendation is visible without scrolling; at mobile use a read-only summary for operational mode and keep laboratory controls separate. Use accessible names and status announcements without reading every telemetry tick aloud.
