# Landscape textures

`leafy-grass.jpg` and `leafy-grass-normal.jpg` are the 1K diffuse and OpenGL normal textures from [Leafy Grass by Poly Haven](https://polyhaven.com/a/leafy_grass).

License: [CC0](https://polyhaven.com/license). Downloaded from Poly Haven on 2026-09-12. Files are served locally; the simulator does not call the Poly Haven API.

## Tree geometry

`broadleaf.glb`: [Tree Small 02](https://polyhaven.com/a/tree_small_02), Poly Haven, CC0.

`fir.glb`: [Fir Tree 01](https://polyhaven.com/a/fir_tree_01), Poly Haven, CC0.

Models include the original 1K textures. Geometry was simplified using gltfpack and packed into local GLB files. Source packages were downloaded on 2026-09-12. Runtime requires no external asset service.

## Spectator head

`spectator-head.json` is a cropped, triangulated and scaled head from the [MakeHuman Community base mesh](https://github.com/makehumancommunity/makehuman/blob/master/makehuman/data/3dobjs/base.obj). The core mesh is released under [CC0](https://github.com/makehumancommunity/makehuman/blob/master/LICENSE.md). Clothing, body geometry, colors and cheering poses are created in the renderer.

## Trackside branding

`branding/` holds sponsor artwork painted onto the run-off strip. This repository ships no artwork there and claims no attribution for it. Files placed in that directory are supplied by the operator, who is responsible for holding the rights to display them. A slot with no file falls back to a wordmark drawn by the renderer.
