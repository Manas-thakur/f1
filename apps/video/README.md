# @afterlap/video

Remotion composition for the AFTERLAP concept promo, `ApexLedgerPromo`:
1920x1080, 30 fps, 942 frames (31.4 s), no audio track.

## Commands

```
bun run --filter @afterlap/video dev
bun run --filter @afterlap/video render
bun run --filter @afterlap/video typecheck
```

`dev` opens Remotion Studio. `render` writes `out/apexledger-promo.mp4`.

## Structure

| Path | Contents |
| --- | --- |
| `src/three/camera.ts` | Pinhole camera, `lookAt` basis, point projection, ground rings, plane corners |
| `src/three/homography.ts` | Four-point projective solve emitting a CSS `matrix3d` |
| `src/three/Ground.tsx` | `GroundPolygon`, `GroundEllipse`, `GroundPlate`, `WireBox` |
| `src/timeline.ts` | Shot cuts, overlay beats and the caption track, all in frames |
| `src/Plate.tsx` | Source footage plus the per-frame grade that suppresses its baked-in graphics |
| `src/shots/` | One module per overlay beat |
| `src/ui/` | Caption, chips, scrims, decision card |

## Geometry

The corridor wedges are a real ground-plane projection, not a drawn fan. The
camera was solved against half-heights measured off the reference frames:
`eye (1, 5.45894, 0)`, `target (0, 0, 0)`, `up (0, 0, 1)`, vertical fov
1.3722 rad, apex at world x 0.99355, upstream slope 0.3301, downstream slope
0.43342. Residual against the measured curve is 3.8 px RMS at 1080p.

Ground ellipses, the ground-plane HUD and the rule-mask billboard use the same
projector, so their perspective stays consistent with the wedges.

## Plate

`public/plate.mp4` is the reference footage. It carries the original overlays
baked in, so `Plate.tsx` runs a per-beat grade (desaturate, darken, raise
contrast) and each rebuilt element sits on a blurred scrim that hides the
original underneath it. Scrim strength is the knob to touch if a ghost shows.
