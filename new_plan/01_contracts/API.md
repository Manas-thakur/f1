# Control plane and stream contract

Base `/api/v1`. All mutable routes require an operator identity, session control lease and `Idempotency-Key`; replay/live-team capabilities are checked server-side. Return typed errors with `code`, `message`, `retryable`, `request_id`, `details`. Never expose exception traces to the UI.

| Method and route | Input | Response / semantics |
|---|---|---|
| POST /sessions | mode, manifest references, seed | 201 immutable manifest and initial state |
| GET /sessions | cursor, mode | paginated session summaries |
| GET /sessions/{id}/snapshot | none | StateEstimate, recommendation, last_sequence, server_time |
| POST /sessions/{id}/control-lease | expected lease revision | short-lived single-operator lease |
| POST /sessions/{id}/commands | start/pause/resume/stop, expected_revision | accepted event or 409 stale revision |
| POST /sessions/{id}/recommendations/{rid}/actions | select/reject/mark_communicated, expected_revision, reason | updated lifecycle; selection does not actuate |
| POST /sessions/{id}/simulator/driver-action | profile_id, observed_at_s, recommendation_id | simulator-only deliberate driver input |
| POST /sessions/{id}/snapshots | label | complete immutable simulation snapshot reference |
| POST /experiments | snapshot_id, treatments, seeds, evaluator_version | 202 job id |
| GET /experiments/{id} | none | queued/running/completed/failed plus report references |
| POST /experiments/{id}/cancel | reason | terminal cancelled status; partial results labelled |
| GET /decisions/{id} | none | evidence record and rule checks |
| GET /rulesets/{id} | none | immutable source manifest and supported checks |
| GET /models | filter | manifests and measured approval state |
| POST /exports | session_id, format, selected_range | local export job, hashes and provenance |
| GET /health/live and /health/ready | none | process liveness / dependency readiness |

## WebSocket

`/api/v1/sessions/{id}/stream?after_sequence=N` uses authenticated same-origin session access. Messages: `snapshot`, `telemetry_view`, `estimate_updated`, `recommendation_updated`, `execution_observed`, `rule_context_changed`, `quality_changed`, `experiment_progress`, `heartbeat`, `resync_required`. Envelope fields: schema_version, session_id, sequence, event_type, session_time_s, payload.

Client must not apply a delta to the wrong snapshot revision. Server retains a bounded reconnect buffer; older cursors trigger `resync_required`. High-rate telemetry views may be coalesced with explicit sequence-range metadata; decision/quality/operator events are lossless. Slow clients receive a snapshot rather than an unbounded queue. A heartbeat proves a connection exists, not that telemetry is fresh.

## Concurrency and errors

Same idempotency key plus same body returns the prior result; same key with another body is 409. Expected-revision mismatch is 409. Expired/invalidated recommendation is 422 with a current snapshot reference. Missing required telemetry/rules is 503 capability unavailable. A `live_team` session invoking a simulator driver command is 403 regardless of frontend controls. If selection arrives with a rule invalidation at the same time, process invalidation first.

## Frontend integration

Use generated REST types, one stream reducer and one session store. Cache immutable manifests separately. Never optimistically label a recommendation selected until the server acknowledges it. Disable repeat submission while pending; after disconnect show pending reconciliation and resync. All controls have loading, disabled, error and success semantics. The standalone HTML mockups only illustrate these transitions locally.
