# Track-data pipeline

## Source priority

1. Latest FIA event decision documents: circuit map, competition notes and Power Unit Information. These define event-specific detection/activation lines, straight-mode areas, sectors and electrical parameters.
2. Licensed survey, CAD or circuit centreline data: metric geometry, elevation, banking, width and boundaries.
3. OpenF1/FastF1 historical location and car telemetry: empirical racing line, speed/braking landmarks and cross-checks. These observations do not define legal boundaries or ERS state.
4. OpenStreetMap geometry under its licence: coarse topology and independent cross-check only unless accuracy validation passes.
5. Formula1.com circuit pages: length, lap count and contextual checks. A rendered map image never becomes authoritative metric geometry by tracing pixels.

The [FIA decision-document portal](https://www.fia.com/documents/formula-1) publishes event documents. The 2026 Australian competition map shows corner/sector and activation information. Event-specific Power Unit Information can define speed-dependent curves and lap-distance activation lines. Ingest document revisions by hash and human review; generic regulations cannot supply event values that the Race Director publishes separately.

## Raw inputs

Store immutable files in `artifacts/tracks/raw/<source>/<sha256>/`. The source record contains URL, retrieval UTC, licence/permission, document title/date/version, page or field locator, original hash and reviewer. Do not scrape around authentication or reuse copyrighted map artwork in public outputs without permission.

For telemetry, save session key, driver, lap, sample time, x/y/z, distance, speed, throttle, brake, gear and source quality. OpenF1 location is approximately 3.7 Hz according to its documentation and can be too sparse for precise curvature. FastF1's source timing/position channels have their own limitations. Keep raw and reconstructed lines separate.

## Geometry compilation

1. Select a clean representative lap or licensed centreline. Reject pit, formation, safety-car, red-flag, deleted and grossly incomplete laps.
2. Transform source coordinates into a local metric ENU frame. Keep original coordinate reference system and transformation.
3. Order samples by lap progress. Remove duplicates and isolated jumps using thresholds derived from sampling cadence and speed, not visual preference.
4. Fit a periodic cubic B-spline to x(s), y(s), z(s). Choose smoothing against held-out point residual and curvature stability. Preserve genuine chicanes.
5. Compute arc length, tangent, yaw, curvature, grade and elevation. Resample at 1 m for canonical storage; solver builds may derive coarser/finer grids.
6. Establish start/finish at official timing line and direction from session progression. Align FIA lap-distance coordinates without changing total length.
7. Add left/right corridor from surveyed boundaries. If only width estimates exist, use a conservative corridor and mark accuracy class. Never infer collision-safe lateral space from centreline alone.
8. Map corner and sector labels to s-ranges. Store event-specific activation/detection lines and straight-mode ranges in the event overlay.
9. Run validation and freeze package hash.

For a 3D centreline r(u), calculate `ds/du = ||dr/du||`, unit tangent and horizontal curvature consistently. Grade uses dz/ds. Do not calculate curvature from unsmoothed low-rate location differences; noise creates fake braking/energy demand.

## Braking and regeneration landmarks

Derive candidate braking windows from several clean laps: sustained negative longitudinal acceleration, brake signal where available, and speed loss relative to distance. Aggregate start/end quantiles by driver/session, then review against circuit geometry. A landmark stores a distribution, not one exact braking point.

The simulator computes recoverable wheel energy through dynamics. Historical deceleration helps calibrate demand but does not reveal MGU-K recovery. Friction braking, tyre grip, battery acceptance, motor limits and regulations determine what portion can be harvested. Public throttle/brake channels cannot identify that split.

## Track package interface

The compiled package contains:

- centreline arrays `s_m,x_m,y_m,z_m,yaw_rad,curvature_1pm,grade`;
- left/right usable corridor and quality class;
- sectors, corners, timing line and pit exclusion;
- elevation/air-density reference and surface zones;
- observed braking/pace distributions with session IDs;
- source records and validation report;
- package schema/version/hash.

The event overlay contains official lines/zones, Power Unit Information tables, race length, session type and revision. Simulator loads physical track plus event overlay. Archived runs retain both hashes.

## Automated compilation commands

The track agent implements:

```text
afterlap tracks ingest --source openf1 --session <key> --track monza
afterlap tracks ingest-fia --event 2026-italy --document <path>
afterlap tracks compile --manifest configs/tracks/monza/source.yaml
afterlap tracks validate --package artifacts/tracks/monza/<hash>
afterlap tracks compare --package-a <hash> --package-b <hash>
```

`ingest-fia` produces a review queue. Optical extraction may suggest values, but a reviewer must confirm each number and coordinate against the document before event-rules validation. The CLI records unknown rather than guessing unreadable fields.
