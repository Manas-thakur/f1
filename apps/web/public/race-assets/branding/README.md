# Trackside branding artwork

Sponsor artwork painted onto the run-off strip either side of the racing surface.
Drop files here and the 3D view picks them up on the next load.

| Slot | File | Registry entry |
| --- | --- | --- |
| 1 | `logo-1.png` | `logo-1` |
| 2 | `logo-2.png` | `logo-2` |
| 3 | `logo-3.png` | `logo-3` |
| 4 | none, drawn as a wordmark | `v-max` |

Slots are declared in `apps/web/src/features/race/sponsors.ts`. Change `image` there to use a
different filename or extension, `null` to fall back to a drawn wordmark, and `label` to set the
wordmark text.

Artwork requirements:

- PNG or WebP with an alpha channel, or SVG with an intrinsic `width` and `height`.
- Trim transparent margins to the artwork bounds. The decal footprint is derived from the file
  aspect ratio, so padding inside the file shrinks the painted logo.
- Roughly 4:1 to 8:1 landscape reads best. The painted strip is 3.2 m across and up to 26 m long.
- 1024 px or wider on the long edge. The renderer mipmaps and anisotropically filters the texture.

A missing or unreadable file is not an error. That slot falls back to a drawn wordmark of its
`label`, so the view never renders a blank strip.

Files in this directory are supplied by the operator. This repository ships none, and no
attribution is claimed for them.
