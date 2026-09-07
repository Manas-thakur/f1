# Persistence and worker implementation recipe

## Schema design

Use UUID/string immutable IDs, UTC creation times, integer revisions and JSONB for versioned typed payloads. Index `(session_id, sequence)` uniquely for event history; `(session_id, created_at)` for decision browsing; `(status, created_at)` for job scheduling. Manifests are content-addressed with SHA-256. Include schema_version on stored payloads. Avoid overwriting a decision row's original estimate with newer knowledge.

Minimum relations:

- `session(id, mode, revision, manifest_hash, status, created_at)`.
- `session_event(id, session_id, sequence, event_type, session_time_s, payload, schema_version)`.
- `operator_command(id, session_id, idempotency_key, body_hash, expected_revision, resulting_event_id)`.
- `control_lease(session_id, operator_id, revision, expires_at)`.
- `decision(id, session_id, revision, state_revision, ruleset_hash, model_hash, payload)`.
- `lifecycle_event(id, decision_id, from_state, to_state, evidence_event_id)`.
- `telemetry_chunk(hash, session_id, start_s, end_s, path, mapping_revision, row_count)`.
- `experiment_job(id, manifest_hash, status, worker_lease, progress, report_hash, failure)`.
- `model_bundle(hash, manifest, approval_status, approval_event_id)`.

## Atomic selection pseudocode

```text
begin transaction
  get existing command by session + idempotency key
  if found: require identical body hash; return its prior result
  lock session/control lease and current recommendation revision
  require authorised operator and valid lease
  require expected revision and current ruleset hash
  require nonterminal state, freshness and execution window
  append operator event and lifecycle transition
  increment revision; insert idempotency record
commit
publish committed event
```

Use a transactional outbox so a crash between commit and WebSocket publish does not lose the notification. Publishing twice is harmless when clients deduplicate sequence/event ID. Database transaction order and runtime event ordering must agree.

## Worker protocol

Session worker accepts `Initialise`, `Observe`, `Plan`, `ApplySimulatorInput`, `Pause`, `Snapshot`, `Stop`. Every command carries session ID and revision; stale results are discarded. Optimisation request includes immutable estimate/rules/model hashes and an absolute monotonic deadline. A completed result for an outdated state cannot overwrite a newer invalidation.

Batch worker claims jobs with a lease, heartbeats ownership, writes artefacts to a staging directory and atomically finalises manifest/report. A failed lease leaves restartable checkpoints; two workers must not publish separate successful reports for one job ID. Cancellation is cooperative between rollouts and terminal status records partial output scope.

## Exports

An export contains session manifest, scenario definition, decision/command/execution logs, selected trajectory chunks, rule/model/objective hashes, software versions, provenance and evaluation report. JSON/CSV output must label units. Redact private source credentials and operator secrets; user-authorised private telemetry remains private by default. The demo export is synthetic and explicitly says so.
