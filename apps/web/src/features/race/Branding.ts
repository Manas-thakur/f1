import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

import type { Sponsor } from './sponsors';
import { SPONSORS, wordmarkCanvas } from './sponsors';
import type { CircuitMap } from './types';
import { trackPose } from './worldGeometry';

const BAND_CENTRE_M = 9;
const BAND_HALF_M = 1.6;
const PAINT_HEIGHT_M = 0.018;
const DECAL_GAP_M = 44;
const MAX_DECAL_M = 26;
const TESSELLATION_M = 1.2;
const MAX_EDGE_RATIO = 2.1;
const MIN_EDGE_SCALE = 0.24;

interface BandTable {
  progress: number[];
  distance: number[];
  total: number;
}

interface Artwork {
  texture: THREE.Texture;
  aspect: number;
}

interface Footprint {
  length: number;
  half: number;
}

interface Placement {
  sponsor: number;
  from: number;
  to: number;
}

function bandTable(map: CircuitMap, lateral: number): BandTable {
  const samples = Math.max(map.points.length * 3, Math.ceil(map.length_m / 2));
  const progress = [0];
  const distance = [0];
  let total = 0;
  let previous = trackPose(map, 0, lateral).position;
  for (let sample = 1; sample <= samples; sample++) {
    const s = sample / samples * map.length_m;
    const point = trackPose(map, s, lateral).position;
    total += point.distanceTo(previous);
    previous = point;
    progress.push(s);
    distance.push(total);
  }
  return { progress, distance, total };
}

function progressAt(table: BandTable, walked: number) {
  let low = 0;
  let high = table.distance.length - 1;
  while (high - low > 1) {
    const middle = (low + high) >> 1;
    if ((table.distance[middle] ?? 0) <= walked) {
      low = middle;
    } else {
      high = middle;
    }
  }
  const start = table.distance[low] ?? 0;
  const end = table.distance[high] ?? start;
  const span = end - start;
  const fraction = span > 1e-6 ? (walked - start) / span : 0;
  const from = table.progress[low] ?? 0;
  return from + fraction * ((table.progress[high] ?? from) - from);
}

function decalGeometry(map: CircuitMap, side: number, table: BandTable,
  spot: Placement, half: number) {
  const span = spot.to - spot.from;
  const steps = Math.max(4, Math.ceil(span / TESSELLATION_M));
  const nominal = span / steps;
  const inner: THREE.Vector3[] = [];
  const outer: THREE.Vector3[] = [];
  for (let step = 0; step <= steps; step++) {
    const s = progressAt(table, spot.from + span * step / steps);
    inner.push(trackPose(map, s, side * (BAND_CENTRE_M - half)).position);
    outer.push(trackPose(map, s, side * (BAND_CENTRE_M + half)).position);
  }
  for (let step = 0; step < steps; step++) {
    const nearFrom = inner[step];
    const nearTo = inner[step + 1];
    const farFrom = outer[step];
    const farTo = outer[step + 1];
    if (!nearFrom || !nearTo || !farFrom || !farTo) {
      return null;
    }
    const nearStep = nearFrom.distanceTo(nearTo);
    const farStep = farFrom.distanceTo(farTo);
    const shortest = Math.min(nearStep, farStep);
    if (shortest < nominal * MIN_EDGE_SCALE
      || Math.max(nearStep, farStep) > shortest * MAX_EDGE_RATIO
      || nearTo.clone().sub(nearFrom).dot(farTo.clone().sub(farFrom)) <= 0) {
      return null;
    }
  }
  const positions: number[] = [];
  const normals: number[] = [];
  const uv: number[] = [];
  const indices: number[] = [];
  for (let step = 0; step <= steps; step++) {
    const near = inner[step];
    const far = outer[step];
    if (!near || !far) {
      return null;
    }
    const along = step / steps;
    const u = side > 0 ? along : 1 - along;
    positions.push(near.x, PAINT_HEIGHT_M, near.z, far.x, PAINT_HEIGHT_M, far.z);
    normals.push(0, 1, 0, 0, 1, 0);
    uv.push(u, 1, u, 0);
    if (step < steps) {
      const base = step * 2;
      indices.push(base, base + 1, base + 2, base + 1, base + 3, base + 2);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  geometry.setIndex(indices);
  return geometry;
}

function placements(table: BandTable, footprints: Footprint[], offset: number) {
  const spots: Placement[] = [];
  let walked = offset;
  let index = 0;
  while (walked < table.total && footprints.length) {
    const sponsor = index % footprints.length;
    const length = footprints[sponsor]?.length ?? 0;
    if (length <= 0 || walked + length > table.total) {
      break;
    }
    spots.push({ sponsor, from: walked, to: walked + length });
    walked += length + DECAL_GAP_M;
    index++;
  }
  return spots;
}

function configure(texture: THREE.Texture, anisotropy: number) {
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.minFilter = THREE.LinearMipmapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.generateMipmaps = true;
  texture.anisotropy = anisotropy;
  texture.needsUpdate = true;
  return texture;
}

function wordmarkArtwork(sponsor: Sponsor, anisotropy: number): Artwork {
  const canvas = wordmarkCanvas(sponsor);
  const texture = configure(new THREE.CanvasTexture(canvas), anisotropy);
  return { texture, aspect: canvas.width / canvas.height };
}

async function loadArtwork(sponsor: Sponsor, anisotropy: number): Promise<Artwork> {
  if (!sponsor.image) {
    return wordmarkArtwork(sponsor, anisotropy);
  }
  const printed = await new Promise<Artwork | null>((resolve) => {
    new THREE.TextureLoader().load(`/race-assets/branding/${sponsor.image}`, (texture) => {
      const source = texture.image as { width?: number; height?: number } | null;
      const width = source?.width ?? 0;
      const height = source?.height ?? 0;
      if (width <= 0 || height <= 0) {
        texture.dispose();
        resolve(null);
        return;
      }
      resolve({ texture: configure(texture, anisotropy), aspect: width / height });
    }, undefined, () => resolve(null));
  });
  return printed ?? wordmarkArtwork(sponsor, anisotropy);
}

export class Branding extends THREE.Group {
  private disposed = false;
  private decals = 0;

  constructor(private readonly map: CircuitMap, private readonly anisotropy: number,
    private readonly invalidate: () => void) {
    super();
    this.name = 'Trackside branding';
    void this.build();
  }

  get decalCount() {
    return this.decals;
  }

  private async build() {
    const artwork = await Promise.all(SPONSORS.map((sponsor) => loadArtwork(sponsor, this.anisotropy)));
    if (this.disposed) {
      artwork.forEach((item) => item.texture.dispose());
      return;
    }
    const footprints = artwork.map(({ aspect }): Footprint => {
      const length = Math.min(BAND_HALF_M * 2 * aspect, MAX_DECAL_M);
      return { length, half: Math.min(BAND_HALF_M, length / aspect / 2) };
    });
    const period = footprints.reduce((sum, item) => sum + item.length + DECAL_GAP_M, 0)
      / Math.max(1, footprints.length);
    const batches = SPONSORS.map((): THREE.BufferGeometry[] => []);
    for (const side of [-1, 1]) {
      const table = bandTable(this.map, side * BAND_CENTRE_M);
      for (const spot of placements(table, footprints, side > 0 ? 0 : period / 2)) {
        const half = footprints[spot.sponsor]?.half ?? BAND_HALF_M;
        const geometry = decalGeometry(this.map, side, table, spot, half);
        if (geometry) {
          batches[spot.sponsor]?.push(geometry);
        }
      }
    }
    for (const [index, batch] of batches.entries()) {
      const source = artwork[index];
      if (!source || batch.length === 0) {
        continue;
      }
      const geometry = mergeGeometries(batch);
      batch.forEach((item) => item.dispose());
      if (!geometry) {
        source.texture.dispose();
        continue;
      }
      const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
        map: source.texture,
        transparent: true,
        opacity: 0.94,
        alphaTest: 0.02,
        depthWrite: false,
        roughness: 0.92,
        metalness: 0,
        side: THREE.DoubleSide,
        polygonOffset: true,
        polygonOffsetFactor: -4,
        polygonOffsetUnits: -8,
      }));
      mesh.name = `Trackside branding ${SPONSORS[index]?.label ?? ''}`;
      mesh.receiveShadow = true;
      mesh.renderOrder = 2;
      this.add(mesh);
      this.decals += batch.length;
    }
    this.invalidate();
  }

  override dispose() {
    this.disposed = true;
  }
}
