# Deployment, observability and recovery

## Packaging

Use Compose under `infra/`: Next.js web, Python runtime (`python -m afterlap_api.cli serve`), batch worker and PostgreSQL, with task-owned persistent data directories. Next.js is the public origin for pages, `/api/v1` and SSE. Runtime planning works without internet. Pin Python/Node packages and model artefacts. Root scaffolding and lockfiles are coordinator-owned. Training may use GPU; inference/optimisation performance is measured on the actual runtime hardware.

Default development binds `127.0.0.1`; do not expose a public unauthenticated session server. An authorised team installation adds TLS, operator authentication, roles and private network policy. Keep secrets outside version control and source manifests. Archive exports to a configured directory and reject path traversal. Separate simulation truth, operational observations and user-visible report permissions.

## Metrics

Ingestion age, clock uncertainty, queue depth, last sensor age by channel, estimator residuals/coverage, planner duration/candidates/rejections, rule-context unknowns, recommendation expiry/churn, operator-to-execution delay, stream resyncs, disk/spool usage, database latency, failed jobs and model/version mismatch. Report planner time separately from end-to-end observation age. Structured logs carry session/decision/request IDs; do not include credentials.

## Health

Liveness means process loop alive. Readiness means required rules/model/source/storage capabilities available. A healthy HTTP server with stale telemetry is not a ready decision system. Health transitions publish quality events to all clients.

## Recovery

Worker crash -> invalidate expiring advice -> restore consistent snapshot and event offset -> re-estimate -> revalidate baseline -> resume only when ready. Do not replay actuator commands as part of normal reconnection. Database outage -> bounded durable spool -> warning -> stop new recommendations if audit durability cannot be maintained. Disk full -> stop experiment jobs first, preserve operational evidence, then withdraw if necessary.

## Release bundle

Bundle source revision, schema, migrations, frontend assets, approved rules/model manifests, synthetic seed scenario, test report and startup instructions. Verify a clean machine can launch the synthetic demonstration without reading parent-project files. A rollback restores compatible schema/model/rules together; never downgrade one silently. Include licenses for imported tools/data and clearly separate demonstration fixtures from benchmark evidence.

## Acceptance

Cold start, graceful shutdown, database restore, worker termination, network reconnect, disk quota simulation, wrong model hash, absent source credentials, loopback-only binding and export path validation. Performance targets remain targets until this package's implementation is built and benchmarked.
