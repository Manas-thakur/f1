# Show Shah

A reveal.js presentation and a captioned Remotion product demo of AFTERLAP. Both use one implementation story, with speaker notes, reusable 3D car geometry and actual product captures. The movie is 2 minutes 24 seconds at 1920 × 1080, 30 fps. It is deliberately silent, with readable on-screen explanations and an optional WebVTT caption file.

## Open and export

From the repository root:

```sh
bun install --frozen-lockfile
bun run show-shah
```

Open http://127.0.0.1:18940. Arrow keys change slides, `Esc` opens the overview, `F` enters fullscreen and `S` opens speaker notes. Sources are linked on each slide. Reduced-motion preferences stop the illustrative animation. This is an HTML presentation using reveal.js, not a PowerPoint binary.

From `show-shah`:

```sh
bun run check
bun run preview
```

While the preview is running, use another terminal:

```sh
bun run export
bun run render
```

`check` builds the portable presentation into `dist/`. `export` writes the PDF, twelve slide images, speaker notes and WebVTT captions there. `render` writes `dist/show-shah.mp4`. Run the build before exporting: another build clears `dist/`. Serve the built folder over HTTP; runtime assets are local and no CDN is required. `bun run studio` opens the editable Remotion timeline on port 18941.

## What the movie shows

| Time | Content |
| --- | --- |
| 00:00 | Reused 3D car and the implementation premise |
| 00:12 | Actual race configuration and start |
| 00:24 | Actual circuit overview |
| 00:36 | Actual chase camera |
| 00:48 | Actual energy telemetry |
| 01:00 | Actual second-car telemetry |
| 01:12 | Actual energy recommendation panel |
| 01:24 | Actual selected-car boost request |
| 01:36 | Actual engineer console, including its visible mock labels |
| 01:48 | Actual cockpit camera |
| 02:00 | Training and evaluation explanation |
| 02:12 | Verification and modelling boundaries |

The nine product clips run at their recorded wall-clock speed. The source captures are 1280 × 720, taken on software WebGL in Performance graphics. They are not a GPU performance benchmark. The three explanatory inserts use deterministic, frame-indexed 3D animation. Their positions, energy cells and moving markers are illustrations, not telemetry or measured performance. No success statistics or trained performance gains are invented.

The deck uses actual screenshots for the setup, race, boost, engineer and cockpit slides. Other slides use 3D explanations. The underlying story includes the current HTTP boost flow, SQLite selection, energy guard, observation masks, separate learning contracts, battery latch, animation timing and known limitations. Engineer predictions and execution cards marked `SCENARIO MOCK` or `MOCK` are placeholders; the recording leaves those labels intact.

## Re-record the product

Use a dedicated local race runtime. Capture changes its selected car, settings and running state. It must not point at someone else's active race.

```sh
RACE_WEB_PORT=18950 RACE_SIM_PORT=18951 RACE_CARS=3 uv run python scripts/race_stack.py
```

In another terminal, from this folder:

```sh
bunx playwright install chromium
RACE_DEMO_URL=http://127.0.0.1:18950 bun run scripts/capture.ts
```

FFmpeg must be on PATH, or set `FFMPEG_PATH` to its executable. The script uses real UI controls and the normal HTTP boost route, records browser video, trims loading time, writes the product screenshots and records the source revision and trims in `public/capture.json`. Source video files are replaced only by this explicit capture command. The selected-car boost response is retained locally in `.build/boost-response.json`. Capture failures stop the command instead of silently substituting mock screens.

## Implementation

`src/story.ts` is the shared chapter, notes and source registry. `src/Scene.tsx` adapts the earlier video project's car cloning/material approach and CC0 GLB. `src/deck.tsx` supplies reveal.js navigation and the current slide's 3D scene. `src/video.tsx` uses Remotion's frame clock, sequences and local video clips. `scripts/export.ts` opens every slide in Chromium before producing the PDF and slide images. `scripts/check.ts` verifies sources and capture completeness.

Read [SOURCES.md](SOURCES.md) for the document review and asset provenance. Generated exports are downloadable from the PR evidence comment and the successful presentation workflow's artifact. `dist/` and raw recordings are not committed.
