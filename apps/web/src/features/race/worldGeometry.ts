import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

import type { CircuitMap } from './types';

export const LIVERIES = ['#e5383b', '#26b7a5', '#ff981f', '#368af5', '#ecebe5'];

function trackPosition(map: CircuitMap, progress: number, lateral: number) {
  const t = (((progress / map.length_m) % 1) + 1) % 1 * map.points.length;
  const i = Math.floor(t);
  const a = map.points[i] ?? [0, 0];
  const b = map.points[(i + 1) % map.points.length] ?? a;
  const previous = map.points[(i - 1 + map.points.length) % map.points.length] ?? a;
  const following = map.points[(i + 2) % map.points.length] ?? b;
  const fraction = t - i;
  const axis = (j: 0 | 1) => {
    const c0 = a[j];
    const c1 = (b[j] - previous[j]) / 2;
    const c2 = previous[j] - 2.5 * a[j] + 2 * b[j] - following[j] / 2;
    const c3 = (following[j] - previous[j]) / 2 + 1.5 * (a[j] - b[j]);
    return [c0 + fraction * (c1 + fraction * (c2 + fraction * c3)),
      c1 + fraction * (2 * c2 + fraction * 3 * c3)] as const;
  };
  const [x, dx] = axis(0);
  const [z, dz] = axis(1);
  const length = Math.hypot(dx, dz) || 1;
  return new THREE.Vector3(x - lateral * dz / length, 0, z + lateral * dx / length);
}

export function trackPose(map: CircuitMap, progress: number, lateral = 0, lateralSlope = 0) {
  const delta = Math.max(0.1, Math.min(1, map.length_m / map.points.length * 0.02));
  const position = trackPosition(map, progress, lateral);
  const before = trackPosition(map, progress - delta, lateral - lateralSlope * delta);
  const after = trackPosition(map, progress + delta, lateral + lateralSlope * delta);
  return { position, yaw: Math.atan2(after.x - before.x, after.z - before.z) };
}

export function box(
  parent: THREE.Object3D, material: THREE.Material,
  size: [number, number, number], position: [number, number, number],
) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material);
  mesh.position.set(...position);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

function strut(parent: THREE.Object3D, a: THREE.Vector3, b: THREE.Vector3, material: THREE.Material) {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(0.028, 0.028, a.distanceTo(b), 8), material);
  mesh.position.copy(a).add(b).multiplyScalar(0.5);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
  parent.add(mesh);
}

function body(material: THREE.Material, sections: [number, number, number, number][]) {
  const vertices: number[] = [];
  const indices: number[] = [];
  for (const [z, width, bottom, top] of sections) {
    for (let j = 0; j < 12; j++) {
      const angle = j / 12 * Math.PI * 2;
      vertices.push(Math.cos(angle) * width, bottom + (Math.sin(angle) + 1) * (top - bottom) / 2, z);
    }
  }
  for (let i = 0; i < sections.length - 1; i++) {
    for (let j = 0; j < 12; j++) {
      const a = i * 12 + j;
      const b = i * 12 + (j + 1) % 12;
      indices.push(a, b, a + 12, b, b + 12, a + 12);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(new Float32Array(vertices.length / 3 * 2), 2));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  const mesh = new THREE.Mesh(geometry, material);
  mesh.castShadow = true;
  return mesh;
}

export function createCar(index: number) {
  const group = new THREE.Group();
  const paint = new THREE.MeshPhysicalMaterial({
    color: LIVERIES[index % LIVERIES.length] ?? '#e5383b', metalness: 0.55, roughness: 0.25, clearcoat: 1,
  });
  const carbon = new THREE.MeshStandardMaterial({ color: '#151a20', roughness: 0.65, metalness: 0.25 });
  const rubber = new THREE.MeshStandardMaterial({ color: '#151619', roughness: 0.92 });
  const alloy = new THREE.MeshStandardMaterial({ color: '#555d66', metalness: 0.95, roughness: 0.27 });
  const tyreRing = new THREE.MeshStandardMaterial({ color: '#e4bb3b', roughness: 0.8 });
  group.userData['tyreRingMaterial'] = tyreRing;
  const stripe = new THREE.MeshStandardMaterial({ color: '#e6e8e7', roughness: 0.35 });
  box(group, carbon, [1.65, 0.1, 3.45], [0, 0.19, -0.2]);
  group.add(body(paint, [
    [-2.15, 0.12, 0.25, 0.65], [-1.2, 0.36, 0.25, 1.08], [-0.45, 0.39, 0.25, 0.72],
    [0.35, 0.32, 0.3, 0.64], [1.35, 0.17, 0.28, 0.48], [2.5, 0.07, 0.26, 0.32],
  ]));
  for (const side of [-1, 1]) {
    const pod = body(paint, [
      [-1.7, 0.08, 0.22, 0.4], [-0.8, 0.3, 0.22, 0.6], [0.3, 0.33, 0.25, 0.64],
      [0.5, 0.22, 0.3, 0.57],
    ]);
    pod.position.x = side * 0.52;
    group.add(pod);
    box(group, carbon, [0.36, 0.19, 0.055], [side * 0.56, 0.46, 0.51]);
    box(group, paint, [0.07, 0.38, 0.75], [side * 0.99, 0.36, 2.05]);
    box(group, paint, [0.06, 0.48, 0.66], [side * 0.8, 0.88, -2.12]);
    for (const z of [-1.45, 1.55]) {
      const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.37, 0.37, 0.38, 32), rubber);
      wheel.rotation.z = Math.PI / 2;
      wheel.position.set(side * 0.92, 0.39, z);
      wheel.castShadow = true;
      group.add(wheel);
      const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.23, 0.23, 0.395, 24), alloy);
      hub.rotation.z = Math.PI / 2;
      hub.position.copy(wheel.position);
      group.add(hub);
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.29, 0.012, 6, 32),
        tyreRing);
      ring.rotation.y = Math.PI / 2;
      ring.position.set(side * 1.12, 0.39, z);
      group.add(ring);
      for (const offset of [-0.36, 0.36]) {
        strut(group, new THREE.Vector3(side * 0.2, 0.35, z + offset),
          new THREE.Vector3(side * 0.92, 0.39, z), carbon);
      }
    }
    strut(group, new THREE.Vector3(side * 0.35, 0.6, -0.48),
      new THREE.Vector3(side * 0.3, 1, -0.4), carbon);
    strut(group, new THREE.Vector3(side * 0.3, 1, -0.4), new THREE.Vector3(0, 0.92, 0.5), carbon);
    box(group, carbon, [0.07, 0.44, 0.09], [side * 0.42, 0.72, -2.1]);
    box(group, paint, [0.2, 0.08, 0.1], [side * 0.48, 0.77, 0.4]);
  }
  strut(group, new THREE.Vector3(0, 0.62, 0.5), new THREE.Vector3(0, 0.92, 0.5), carbon);
  for (let i = 0; i < 3; i++) {
    box(group, i === 2 ? paint : carbon, [1.96, 0.045, 0.19], [0, 0.2 + i * 0.05, 2.3 - i * 0.2]);
  }
  box(group, carbon, [1.6, 0.07, 0.62], [0, 1.06, -2.15]);
  box(group, paint, [1.6, 0.08, 0.15], [0, 1.13, -2.42]);
  box(group, stripe, [0.07, 0.025, 1.25], [0, 0.52, 1.06]);
  const cockpit = new THREE.Mesh(new THREE.SphereGeometry(0.27, 20, 12), carbon);
  cockpit.scale.set(1, 0.5, 1.5);
  cockpit.position.set(0, 0.67, -0.05);
  group.add(cockpit);
  const helmet = new THREE.Mesh(new THREE.SphereGeometry(0.17, 24, 16), stripe);
  helmet.position.set(0, 0.82, -0.22);
  group.add(helmet);
  const visor = new THREE.Mesh(new THREE.SphereGeometry(0.174, 24, 12, 0, Math.PI * 2, 1, 0.6), carbon);
  visor.position.copy(helmet.position);
  group.add(visor);
  const numberCanvas = document.createElement('canvas');
  numberCanvas.width = 128;
  numberCanvas.height = 64;
  const label = numberCanvas.getContext('2d');
  if (label) {
    label.fillStyle = '#11191f';
    label.fillRect(0, 0, 128, 64);
    label.fillStyle = '#f6f7f2';
    label.font = 'italic bold 48px Arial';
    label.textAlign = 'center';
    label.fillText(String(index + 1).padStart(2, '0'), 64, 50);
  }
  const numberTexture = new THREE.CanvasTexture(numberCanvas);
  numberTexture.colorSpace = THREE.SRGBColorSpace;
  const numberPlate = new THREE.Mesh(new THREE.PlaneGeometry(0.6, 0.3),
    new THREE.MeshStandardMaterial({ map: numberTexture, roughness: 0.55 }));
  numberPlate.rotation.y = Math.PI;
  numberPlate.position.set(0, 1.03, -2.505);
  group.add(numberPlate);
  const batches = new Map<THREE.Material, THREE.BufferGeometry[]>();
  group.updateMatrixWorld(true);
  for (const child of group.children) {
    if (child instanceof THREE.Mesh && !Array.isArray(child.material)) {
      const material = child.material as THREE.Material;
      const geometry = (child.geometry as THREE.BufferGeometry).clone().applyMatrix4(child.matrixWorld);
      const batch = batches.get(material) ?? [];
      batch.push(geometry);
      batches.set(material, batch);
      (child.geometry as THREE.BufferGeometry).dispose();
    }
  }
  group.clear();
  for (const [material, batch] of batches) {
    const geometry = mergeGeometries(batch);
    batch.forEach((item) => item.dispose());
    if (geometry) {
      const mesh = new THREE.Mesh(geometry, material);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      group.add(mesh);
    }
  }
  const spokes = new THREE.InstancedMesh(new THREE.BoxGeometry(0.03, 0.22, 0.03), alloy, 24);
  spokes.frustumCulled = false;
  group.add(spokes);
  group.userData['wheelSpokes'] = spokes;
  spinWheels(group, 0);
  group.scale.x = 2 / new THREE.Box3().setFromObject(group).getSize(new THREE.Vector3()).x;
  return group;
}

export function ribbon(map: CircuitMap, inner: number, outer: number, height: number) {
  const positions: number[] = [];
  const uv: number[] = [];
  const indices: number[] = [];
  const segments = Math.max(map.points.length, Math.ceil(map.length_m / 3));
  for (let i = 0; i <= segments; i++) {
    for (const offset of [inner, outer]) {
      const p = trackPose(map, i / segments * map.length_m, offset).position;
      positions.push(p.x, height, p.z);
      uv.push((offset - inner) / (outer - inner), i * map.length_m / segments / 6);
    }
    if (i < segments) {
      const a = i * 2;
      indices.push(a, a + 2, a + 1, a + 1, a + 2, a + 3);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

export function surfaceTexture(kind: 'asphalt' | 'grass' | 'curb' | 'gravel') {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 256;
  const context = canvas.getContext('2d');
  if (context) {
    context.fillStyle = kind === 'asphalt' ? '#303438' : kind === 'grass' ? '#344528'
      : kind === 'gravel' ? '#978772' : '#ede9dc';
    context.fillRect(0, 0, 256, 256);
    if (kind === 'curb') {
      context.fillStyle = '#b92728';
      context.fillRect(0, 0, 256, 128);
    } else {
      let seed = 42;
      for (let i = 0; i < 24000; i++) {
        seed = (seed * 1664525 + 1013904223) >>> 0;
        const x = seed % 256;
        const y = (seed >>> 8) % 256;
        const shade = (seed >>> 16) % 120 + 20;
        context.fillStyle = `rgba(${shade},${shade},${shade},0.18)`;
        context.fillRect(x, y, kind === 'gravel' ? 2 : 1, kind === 'grass' ? 3 : 1);
      }
    }
  }
  if (kind === 'asphalt' && context) {
    for (const x of [75, 160]) {
      const gradient = context.createLinearGradient(x - 20, 0, x + 20, 0);
      gradient.addColorStop(0, '#12151a00');
      gradient.addColorStop(0.5, '#12151a44');
      gradient.addColorStop(1, '#12151a00');
      context.fillStyle = gradient;
      context.fillRect(x - 20, 0, 40, 256);
    }
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  return texture;
}

export function foliageTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 512;
  const ctx = canvas.getContext('2d');
  if (ctx) {
    let seed = 1741;
    const random = () => {
      seed = (seed * 1664525 + 1013904223) >>> 0;
      return seed / 4294967296;
    };
    for (let i = 0; i < 1700; i++) {
      const angle = random() * Math.PI * 2;
      const radius = Math.sqrt(random()) * 225;
      const x = 256 + Math.cos(angle) * radius;
      const y = 256 + Math.sin(angle) * radius * 0.94;
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(random() * Math.PI);
      const light = 18 + random() * 24;
      ctx.fillStyle = `hsl(${85 + random() * 25} 34% ${light}%)`;
      ctx.beginPath();
      ctx.ellipse(0, 0, 4 + random() * 4, 10 + random() * 6, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = `hsl(80 25% ${light + 8}%)`;
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.moveTo(0, -9);
      ctx.lineTo(0, 10);
      ctx.stroke();
      ctx.restore();
    }
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

const wheelTransform = new THREE.Object3D();

export function spinWheels(car: THREE.Group, progress: number) {
  const wheels: unknown = car.userData['wheelSpokes'];
  if (!(wheels instanceof THREE.InstancedMesh)) {
    return;
  }
  let index = 0;
  for (const side of [-1, 1]) {
    for (const z of [-1.45, 1.55]) {
      for (let spoke = 0; spoke < 6; spoke++) {
        const angle = progress / 0.37 + spoke * Math.PI / 3;
        wheelTransform.position.set(side * 1.125, 0.39 + Math.cos(angle) * 0.11, z + Math.sin(angle) * 0.11);
        wheelTransform.rotation.set(angle, 0, 0);
        wheelTransform.updateMatrix();
        wheels.setMatrixAt(index++, wheelTransform.matrix);
      }
    }
  }
  wheels.instanceMatrix.needsUpdate = true;
}
