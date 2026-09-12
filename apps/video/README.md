# @afterlap/video

Remotion composition for the AFTERLAP explainer, `AfterlapPromo`:
1920x1080, 30 fps, 942 frames (31.4 s), no audio track.

## Commands

```
bun run --filter @afterlap/video dev
bun run --filter @afterlap/video render
bun run --filter @afterlap/video typecheck
```

`dev` opens Remotion Studio. `render` writes `out/afterlap-promo.mp4`.

## Structure

One continuous animated shot, no slides and no title cards, so it drops into a
presentation. `motion.ts` drives the camera and both cars from the frame number;
every other module annotates that motion.

| Path | Contents |
| --- | --- |
| `src/motion.ts` | Car paths, the overtake, and the tracking camera keyframes |
| `src/three/camera.ts` | Pinhole camera, `lookAt` basis, projection |
| `src/three/Car.tsx` | Schematic plan-view car projected through the camera |
| `src/three/Track.tsx` | Scrolling track surface, edges and distance marks |
| `src/three/Ground.tsx` | Ground-plane polygons, rings and lines |
| `src/shots/Corridor.tsx` | Candidate corridor fanned out ahead of the car |
| `src/timeline.ts` | The six beats and their captions |

## Theme

Colours, fonts and spacing come from `docs/design/mockups/tokens.css`:
paper `#eef0f2`, surface `#ffffff`, ink `#20282f`, blue `#155dc1` for selection,
purple `#8855a6` for the reference series, green `#207247` for pass. Segoe UI for
text, Consolas for numerals. Transitions use the `--ease-in-out` curve and are
sequential: a scene fades to paper before the next fades in, so two scenes are
never legible at once.
