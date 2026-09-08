# Frontend components and state recipe

## Shared application architecture

Coordinator owns router, generated API client and session store. A12 supplies tokens, Button, StatusBadge, Dialog, Field, DataTable and ChartFrame. A09 owns RecommendationPanel, BattleView, EnergyTimeline, DecisionHistory and EvidenceInspector. A10 reuses ChartFrame/shared cursor in the replay view rather than writing a second chart-event protocol.

Separate server state (manifest, estimate, recommendation, quality, revision) from view state (selected channel, cursor, inspector, density). A command in flight lives in request state with idempotency key and expected revision. Do not optimistically mutate authoritative recommendation status.

## Reducer rules

`snapshot`: atomically replace session state and last_sequence. `estimate_updated`: accept only the next valid revision. `recommendation_updated`: apply only for matching session and newer revision. `quality_changed`: render warning and disable time-sensitive actions immediately. `resync_required`: pause delta application, fetch snapshot, resume from its sequence. Never deduce good telemetry from heartbeat alone.

## Chart contract

Every series includes unit, provenance, x-axis coordinate, sample timestamps, quantile definition and event markers. One shared cursor sends progress_m to all chart panels; each panel interpolates for display only and shows original sampling resolution. Downsample min/max envelopes to preserve spikes; retain checkpoint/rule transitions exactly. Do not smooth a power limit violation out of view. The backend retains raw arrays for evidence export.

## Interaction details

Select button: disabled if expired/invalid/stale/missing prerequisite; pending while awaiting server; success shows selected state; error keeps current state and explains resolution. `mark communicated` is a separate action. An observed driver action advances execution, including mismatch labels when the driver chose differently. The evidence dialog restores focus to its invoking control and closes on Escape.

## Accessibility

Use semantic landmarks, one h1 per route, labelled controls, table headers, focus-visible rings and aria-live only for significant state changes. Do not announce high-frequency telemetry. Text conveys provenance and stale states independent of colour. Common chart cursor has a keyboard-accessible slider alternative. Provide chart summaries for nonvisual review. At narrow sizes stack views; preserve controls within viewport rather than clipping overflow to hide bugs.

## Testing

Use typed fixtures for every lifecycle/quality state; test reducer gaps and wrong session IDs; browser-test source labels, pending/error, dialog focus, chart cursor, mobile overflow and real backend stream integration. Local HTML is the visual reference; implement with actual shared React state and API contracts.
