# Data ingestion, provenance and replay

## Deliverable

Implement `packages/core/data/` with source adapters, typed ingestion, recording and a replay clock. Inputs are raw source packets and SourceCapability; outputs are TelemetryEvent and quality events. No estimator or battery invention belongs here.

## Adapters

`SimulatorAdapter` subscribes to an observation stream stripped of hidden truth. `PublicReplayAdapter` imports selected public sessions as offline reference data. `TeamFeedAdapter` is an interface plus a synthetic adapter until an authorised feed and its field definitions exist. An unavailable integration is reported as unavailable, not mocked into a live feed.

Each adapter implements `capabilities()`, `open(manifest)`, `events()`, `close()`. Separate raw vendor fields from canonical channels via an explicit mapping table. Validate rate, units, source time and missing-value conventions during import. A historical DRS field must not be silently interpreted as 2026 Overtake eligibility. Preserve unmapped fields in raw archival storage rather than guessing.

## Pipeline

Parse -> structural validation -> source timestamp conversion -> SI conversion -> deduplication -> bounded reorder -> assign session sequence -> quality classification -> append raw/normalised records -> publish. Configure reorder windows per source; report resulting latency. Do not wait indefinitely for a missing packet. A late packet is recorded with an out-of-order label and excluded from already-finalised decision states.

Quality evaluation compares last source observation age, expected cadence, bounds and clock uncertainty. Never derive freshness from stream heartbeats. A gap in battery power integration must widen estimator uncertainty downstream. Monotonic sensor sequences and explicit adapter restarts prevent duplicate packet replay.

## Storage

Partition Parquet by session/car/channel family and bounded time chunk. Keep raw immutable data and canonical normalised data with mapping revision. Atomic write to a task-owned staging file followed by a manifest update; readers only consume completed chunks. Hash chunks and capture original source URL/license/terms review in acquisition manifest. Do not log credentials or account cookies.

Replay uses the canonical session clock with pause, step, seek and speed. Seeking loads a prior estimator snapshot and replays forward; it never evaluates future samples at the current cutoff. Live acquisition, archive replay and counterfactual simulation have different session modes and badges.

## Tests and failure handling

Test duplicate events, backwards clocks, unit conversion, source restart, missing channels, delayed bursts and import interruption. Property: recording then replaying reproduces the same normalised sequence. Property: a replay speed change alters wall-clock pacing, not simulated timestamps or integration results. Emit unavailable when mandatory source capabilities are absent. Backpressure coalesces display data only; preserve decisions and raw observations or stop with a visible recording fault.

## Public data use

OpenF1 documents approximate 3.7 Hz car/location data and no battery-energy channel in its published car-data schema. Its location description excludes reliable lateral placement. Use it for pace/context and calibration; do not claim it provides a fully observed energy controller. See [source register](../sources/SOURCE_REGISTER.md).
