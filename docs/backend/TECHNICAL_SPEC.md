# Backend, session authority and persistence

## Deliverable

Implement `apps/api/`, `workers/` and reviewed persistence migrations. Next.js exposes the contract routes by spawning `python -m afterlap_api.cli`. Python has no HTTP server. A single owner processes each session's state transitions. A process pool handles bounded optimisation jobs; batch training/evaluation runs separately. Use a bounded IPC queue and explicit cancellation/deadlines.

## Database model

Tables: sessions, manifests, source_capabilities, operator_leases, operator_events, decisions, plan_candidates, execution_events, outcome_records, experiment_jobs, model_manifests, rule_manifests and export_jobs. IDs are immutable. Use unique `(session_id,idempotency_key)` for commands, optimistic revision checks and foreign keys. Event inserts and lifecycle revision changes occur in one transaction. Decisions retain the original StateEstimate reference; do not update them when later knowledge improves.

Bulk telemetry is written to Parquet with immutable chunk manifests and hashes. PostgreSQL holds chunk indexes and evidence references rather than every 100 Hz physical state. Exports include all hashes needed to reproduce the experiment. Database migrations are coordinator-owned to prevent conflicting versions from parallel agents.

## Lifecycle

Proposed -> selected -> communicated -> executing -> completed. Proposed may be rejected; any nonterminal state may expire/invalidate where appropriate. Selecting validates observation age, ruleset, state revision and control lease atomically. `mark_communicated` records a human action, not an audio transmission. Execution requires matching telemetry or a deliberate simulator input. Unmatched driver action is recorded without forcing a recommendation association.

## Stream and frontend

One SSE envelope and ordered sequence across views. Reconnect gives a bounded delta replay or a snapshot. UI telemetry can coalesce; decisions and quality events cannot disappear. Capture the version the client acknowledged so a stale UI cannot operate an old recommendation. HTTP success requires an accepted state transition, not merely queue insertion; long-running jobs return 202 and a trackable status.

## Security and reliability

Local default binds loopback. Team deployment adds authenticated sessions, role checks, TLS and private network configuration. Reject simulator actuator endpoints in non-simulation modes. Authorise exports and truth endpoints separately. Do not store source credentials in manifests. Validate requested local paths against configured storage roots. Audit human and automated changes distinctly.

Handle worker crash with a visible unavailable state and restore from a consistent snapshot/log offset. Never replay a previously acknowledged human actuator command merely because the process restarted. A temporary DB outage uses a bounded durable spool with sequence continuity; if exhausted, stop issuing new advice. Test concurrent selection, stale revision, duplicate command, disconnect/resync, rule change race, interrupted export and worker restart.
