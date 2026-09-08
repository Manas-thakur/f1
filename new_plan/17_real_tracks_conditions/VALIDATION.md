# Track and condition acceptance

## Geometry checks

- Closure error below 0.5 m after periodic fitting; start and finish coincide without a curvature spike.
- Compiled length within 0.1% or 5 m of the chosen official event reference, whichever is larger. A disagreement blocks publication until source review.
- Direction, start line, sector boundaries and corner order checked against the latest FIA map.
- Elevation/grade visually and numerically reviewed; no coordinate-unit or datum jump.
- Curvature stable under source resampling and smoothing; chicanes remain identifiable.
- Corridor width never inferred from the centreline. Unknown width disables lateral/contact claims.
- A real telemetry lap projected to the centreline has residual distributions within declared package thresholds.

## Event-overlay checks

Two reviewers transcribe each detection/activation line, straight-mode range, event power curve and recharge value from the same hashed FIA document. A generated diff highlights disagreement. Boundary tests calculate expected values independently of the production parser. Recalled/revised documents invalidate the prior overlay.

Test just before/at/after each lap-distance line and speed breakpoint. Test overtake eligible/ineligible, yellow-sector disable, SC/VSC/restart, qualifying/race/out-lap context and lap-ledger reset. Unknown supporting conditions return unknown.

## Condition checks

Weather distributions reproduce marginal ranges, correlations and persistence for their source sessions. Hold out complete sessions. Wind projection around the lap must reverse correctly as heading rotates. Air-density calculations match a separate reference implementation. Wetness/grip changes must affect braking and recovery in the same physical direction.

Traffic tests compare free air, tow and wake at controlled gaps/lateral offsets. A symmetric side-by-side scenario must not gain an arbitrary one-car advantage. Opponent response must change when our action changes; hidden truth mutation cannot change our policy with fixed observations.

## Circuit benchmark set

Before broad training, qualify six contrasting packages: Monza, Monaco, Spa, Suzuka, Mexico City and Singapore. This set exercises long deployment, low passability, elevation/weather, linked corners, altitude and heat/humidity. It does not imply the remaining calendar is complete. Each additional track passes the same suite.

Use hand-computed microcases at real track landmarks, then complete-lap baselines. For Monza, verify long-straight deployment and heavy-braking recovery without using the Formula1.com “80% full throttle” statement as a simulator input. For Monaco, confirm that corridor uncertainty suppresses precise passing risk. For Mexico City, test density sensitivity. For Spa, test spatially changing wind and weather transitions.

## Definition of complete

A track is complete only when its package, source register, validation report and event overlay are hash-pinned and a deterministic baseline lap runs. “Map displayed in UI” is not completion. The real-track module is complete for the season only when every supported calendar circuit has an eligible package. Unsupported/new/revised events remain visible as unavailable.

Release evidence includes package hashes, raw-source permissions, extraction/review identities, numerical tolerances, residual plots and rerun commands. No benchmark may combine circuits that failed geometry or rule validation.
