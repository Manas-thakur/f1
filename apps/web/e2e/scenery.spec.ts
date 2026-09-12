import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { expect, test } from '@playwright/test';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

import { Scenery } from '../src/features/race/Scenery';
import { sceneryProfile } from '../src/features/race/circuitScenery';
import { SceneryClearance } from '../src/features/race/sceneryClearance';
import type { CircuitMap } from '../src/features/race/types';
import { trackPose } from '../src/features/race/worldGeometry';

const map: CircuitMap = { id: 'test', name: 'Test', length_m: 440,
  points: [[0, 0], [100, 0], [100, 20], [0, 20]] };

test('clearance protects segment interiors, closing seam and nearby return lanes', () => {
  const clearance = new SceneryClearance(map);
  expect(clearance.circleClear([50, -4], 1)).toBe(false);
  expect(clearance.circleClear([-3, 10], 1)).toBe(false);
  expect(clearance.circleClear([50, 26], 1)).toBe(false);
  expect(clearance.circleClear([50, 60], 10)).toBe(true);
  expect(clearance.circleClear([50, 45], 20)).toBe(false);
  expect(clearance.segmentClear([50, -50], [50, 60], 0.1)).toBe(false);
  expect(clearance.segmentClear([0, 70], [100, 70], 0.1)).toBe(true);
});

test('clearance bounds the rendered spline including sharp bends and duplicate points', () => {
  const curved: CircuitMap = { ...map, points: [[0, 0], [80, 0], [80, 80], [80, 80], [-20, 30]] };
  const clearance = new SceneryClearance(curved);
  for (let i = 0; i < 4000; i++) {
    const p = trackPose(curved, i / 4000 * curved.length_m, 7.95).position;
    expect(clearance.circleClear([p.x, p.z], 0)).toBe(false);
  }
  const first = clearance.place(curved, 0.5, 10, 25);
  const second = clearance.place(curved, 0.5, 10, 25);
  expect(first?.position.toArray()).toEqual(second?.position.toArray());
  expect(first).not.toBeNull();
  expect(new SceneryClearance(curved, 600).place(curved, 0.5, 10, 25)).toBeNull();
});

function footprintRadius(root: THREE.Object3D) {
  root.updateMatrixWorld(true);
  const origin = root.getWorldPosition(new THREE.Vector3());
  const vertex = new THREE.Vector3();
  const transform = new THREE.Matrix4();
  const instance = new THREE.Matrix4();
  let radius = 0;
  const measure = (point: THREE.Vector3, matrix: THREE.Matrix4) => {
    vertex.copy(point).applyMatrix4(matrix);
    radius = Math.max(radius, Math.hypot(vertex.x - origin.x, vertex.z - origin.z));
  };
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) {
      return;
    }
    const geometry = object.geometry as THREE.BufferGeometry;
    if (object instanceof THREE.InstancedMesh) {
      geometry.computeBoundingBox();
      const bounds = geometry.boundingBox;
      if (!bounds) {
        return;
      }
      for (let i = 0; i < object.count; i++) {
        object.getMatrixAt(i, instance);
        transform.multiplyMatrices(object.matrixWorld, instance);
        for (const x of [bounds.min.x, bounds.max.x]) {
          for (const y of [bounds.min.y, bounds.max.y]) {
            for (const z of [bounds.min.z, bounds.max.z]) {
              measure(new THREE.Vector3(x, y, z), transform);
            }
          }
        }
      }
    } else {
      const positions = geometry.getAttribute('position');
      for (let i = 0; i < positions.count; i++) {
        measure(new THREE.Vector3().fromBufferAttribute(positions, i), object.matrixWorld);
      }
    }
  });
  return radius;
}

test('all23 circuit scenery keeps complete rendered footprints outside the driving corridor', () => {
  test.setTimeout(120000);
  const maps = JSON.parse(execFileSync('uv', ['run', 'python', '-c',
    'import json; from afterlap_core.race.circuit import catalogue, circuit; print(json.dumps([circuit(c["id"])[1] for c in catalogue()]))'],
  { cwd: fileURLToPath(new URL('../../../', import.meta.url)), encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 })) as CircuitMap[];
  expect(maps).toHaveLength(23);
  const originalLoad = GLTFLoader.prototype.load;
  const originalBatch = Reflect.get(Scenery.prototype, 'batchStaticMeshes') as () => void;
  const originalFetch = globalThis.fetch;
  GLTFLoader.prototype.load = () => undefined;
  globalThis.fetch = () => Promise.reject(new Error('offline geometry test'));
  Reflect.set(Scenery.prototype, 'batchStaticMeshes', () => undefined);
  try {
    for (const circuit of maps) {
      const clearance = new SceneryClearance(circuit);
      const scenery = new Scenery(circuit, sceneryProfile(circuit.id), () => undefined);
      for (const object of scenery.children) {
        if (!(object instanceof THREE.Group)
          && !(object instanceof THREE.Mesh && !(object instanceof THREE.InstancedMesh))) {
          continue;
        }
        const origin = object.getWorldPosition(new THREE.Vector3());
        const radius = footprintRadius(object);
        expect(clearance.circleClear([origin.x, origin.z], radius), `${circuit.id} scenery footprint ${radius}`).toBe(true);
      }
      for (let garage = 0; garage < 10; garage++) {
        const pose = clearance.place(circuit, (garage * 10 - 35) / circuit.length_m, -24, 7);
        if (pose) {
          expect(clearance.circleClear([pose.position.x, pose.position.z], Math.hypot(5, 4.25)),
            `${circuit.id} garage ${garage}`).toBe(true);
        }
      }
      scenery.dispose();
    }
  } finally {
    GLTFLoader.prototype.load = originalLoad;
    globalThis.fetch = originalFetch;
    Reflect.set(Scenery.prototype, 'batchStaticMeshes', originalBatch);
  }
});
