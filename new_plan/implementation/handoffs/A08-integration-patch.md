# A08 — integration patch for `apps/api/afterlap_api/main.py`

`main.py` is coordinator-owned and was not modified. Applying the three hunks
below attaches the session factory, starts the outbox publisher and mounts the
two new routers. Nothing else in the file changes.

The same wiring is exercised in `tests/backend/test_workers_and_routes.py`
(`client` fixture), so the patch is not speculative: the routers, the factory and
the runtime registry are already known to work together against a real app.

---

## Hunk 1 — imports

```diff
--- a/apps/api/afterlap_api/main.py
+++ b/apps/api/afterlap_api/main.py
@@
 from .deps import Database, Settings
 from .errors import install_error_handlers
 from .observability import RequestMetrics, configure_logging, metrics_response
-from .routes import health, models, rulesets, sessions
+from .routes import experiments, exports, health, models, rulesets, sessions
 from .runtime import RuntimeRegistry
+from .session import OutboxPublisher, SessionFactory, SessionRecorder
+from .session.spool import BoundedSpool
 from .stream import StreamHub
```

## Hunk 2 — lifespan: session factory, spool-backed recorder, publisher

```diff
@@ async def lifespan(app: FastAPI) -> AsyncIterator[None]:
     app.state.latest_state = {}
     app.state.started_at = time.monotonic()
     app.state.metrics = RequestMetrics()
+    app.state.reports_root = paths.reports
+
+    def _recorder(session_id: str) -> SessionRecorder:
+        """One durable recorder per session, with a bounded local spool.
+
+        A store outage spools; an exhausted spool halts new recommendations.
+        """
+        return SessionRecorder(
+            app.state.database.factory,
+            session_id=session_id,
+            spool=BoundedSpool(paths.spool, session_id),
+        )
+
+    # Scenario, car, track, rule-pack and objective documents are resolved from
+    # the workspace `configs/` tree (Paths.default()), not from the artifact
+    # root, so a relocated artifact root does not hide the configurations.
+    app.state.session_factory = SessionFactory(recorder_factory=_recorder)
+
+    # Drains the transactional outbox onto the stream hub. Delivery is at least
+    # once; clients deduplicate on (session_id, sequence).
+    app.state.publisher = OutboxPublisher(app.state.database.factory, app.state.hub)
+    app.state.publisher.start()
 
     # Readiness is decided from measured capabilities, not from the fact that
     # the process started.
@@
     try:
         yield
     finally:
+        await app.state.publisher.stop_running()
         app.state.runtimes.stop_all()
         app.state.database.dispose()
```

## Hunk 3 — routers

```diff
@@ def create_app(settings: Settings | None = None) -> FastAPI:
     app.include_router(health.router, prefix=API_PREFIX, tags=["health"])
     app.include_router(sessions.router, prefix=API_PREFIX, tags=["sessions"])
     app.include_router(rulesets.router, prefix=API_PREFIX, tags=["rulesets"])
     app.include_router(models.router, prefix=API_PREFIX, tags=["models"])
+    app.include_router(experiments.router, prefix=API_PREFIX, tags=["experiments"])
+    app.include_router(exports.router, prefix=API_PREFIX, tags=["exports"])
```

---

## What each hunk buys, and what breaks without it

| Hunk | Without it |
|---|---|
| 1 + 3 | `POST /experiments`, `GET /experiments/{id}`, `POST /experiments/{id}/cancel`, `POST /exports` and `GET /exports/{id}` are not routed at all. |
| 2, `session_factory` | `POST /sessions` answers **503 capability_unavailable** for `session_factory` — which is the current behaviour and is honest, but no session can be created. |
| 2, `_recorder` | Sessions run, but no decision, execution or outcome is persisted, so `GET /decisions/{id}` and every export are empty. |
| 2, `publisher` | Lifecycle changes commit but are never delivered to a WebSocket client: the outbox fills and the UI shows nothing after the initial snapshot. |
| 2, `reports_root` | `GET /experiments/{id}` returns `report_path: null` even for a completed job. |

## Notes for the coordinator

1. **`operator_action` outbox rows are undeliverable.** `apply_operator_action`
   writes an outbox row with `event_type="operator_action"`, which is not a
   member of `StreamEventType`, so `envelope_from_outbox` cannot validate it.
   The publisher quarantines such rows, logs them and leaves `published_at` NULL
   rather than renaming them into some other event. Nothing is lost — the
   accompanying `recommendation_updated` row from `_transition` carries the
   lifecycle change — but the rows accumulate. Either add an `OPERATOR_ACTION`
   member to `StreamEventType` with a payload type, or stop writing an outbox
   row for that event. This is a contracts/persistence decision, so it is a
   proposal here, not a change.
2. **`store_decision` and `record_execution` write an outbox payload without the
   discriminator** `StreamEnvelope` needs. The publisher repairs this by
   labelling the payload with the row's own `event_type` and nothing else. A
   one-line change in `repository.py` (adding `"event_type": ...` to those two
   payload dicts, as `_transition` already does) would remove the repair path.
3. The publisher's poll interval defaults to 50 ms. If the coordinator prefers
   event-driven publishing, `OutboxPublisher.drain_once()` can be awaited
   directly after each committed command instead of running the loop.
