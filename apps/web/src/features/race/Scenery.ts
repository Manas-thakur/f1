import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

import type { SceneryProfile } from './circuitScenery';
import type { CircuitMap } from './types';
import { box, trackPose } from './worldGeometry';

const material = (color: string, metalness = 0) => new THREE.MeshStandardMaterial({
  color, roughness: metalness ? 0.4 : 0.86, metalness,
});

export class Scenery extends THREE.Group {
  private readonly treePool: THREE.Group[] = [];
  private readonly treePositions: THREE.Vector3[] = [];
  private readonly crowd: {
    group: THREE.Group; arms: THREE.InstancedMesh; head: THREE.InstancedMesh; count: number;
  }[] = [];
  private readonly dummy = new THREE.Object3D();
  private lastUpdate = 0;
  private disposed = false;
  private detailedHead: THREE.BufferGeometry | null = null;
  private readonly simpleHead = new THREE.SphereGeometry(0.12, 10, 8);
  private treeSource: THREE.Group | null = null;
  private readonly controller = new AbortController();

  constructor(private readonly map: CircuitMap, private readonly profile: SceneryProfile,
    private readonly invalidate: () => void) {
    super();
    this.name = 'Circuit surroundings';
    this.buildGrandstands();
    this.buildLandscape();
    this.buildLandmark();
    this.buildFences();
    this.batchStaticMeshes();
    this.loadTrees();
  }

  private place(progress: number, lateral: number) {
    const pose = trackPose(this.map, progress * this.map.length_m, lateral);
    const group = new THREE.Group();
    group.position.copy(pose.position);
    group.rotation.y = pose.yaw;
    this.add(group);
    return group;
  }

  private buildGrandstands() {
    const concrete = material('#92948e');
    const steel = material('#bbc2c0', 0.7);
    const roof = material('#e3e0ce', 0.35);
    const shirtColors = ['#d75735', '#f1af24', '#28758e', '#ddddce', '#34383d', '#489060', '#b6223b'];
    const skinColors = ['#bf8764', '#e2b598', '#855338', '#623d2c', '#c79c78'];
    const headGeometry = this.simpleHead;
    for (let stand = 0; stand < 5; stand++) {
      const group = this.place([200 / this.map.length_m, 0.21, 0.43, 0.67, 0.88][stand] ?? 0, 31);
      const count = 192;
      const bodies = new THREE.InstancedMesh(new THREE.CapsuleGeometry(0.18, 0.3, 3, 7), material('#ffffff'), count);
      const head = new THREE.InstancedMesh(headGeometry, material('#ffffff'), count);
      const arms = new THREE.InstancedMesh(new THREE.CapsuleGeometry(0.052, 0.48, 3, 6), material('#ffffff'), count * 2);
      const legs = new THREE.InstancedMesh(new THREE.CapsuleGeometry(0.07, 0.62, 3, 6), material('#333c47'), count * 2);
      for (let row = 0; row < 8; row++) {
        box(group, concrete, [1.6, 0.6 + row * 0.62, 38], [-row * 1.6, 0.3 + row * 0.31, 0]);
        for (let seat = 0; seat < 24; seat++) {
          const i = row * 24 + seat;
          const x = -row * 1.6;
          const z = (seat - 11.5) * 1.5;
          this.dummy.position.set(x, row * 0.62 + 1.55, z);
          this.dummy.rotation.set(0, Math.PI / 2, 0);
          this.dummy.updateMatrix();
          bodies.setMatrixAt(i, this.dummy.matrix);
          bodies.setColorAt(i, new THREE.Color(shirtColors[(i * 13 + stand) % shirtColors.length]));
          this.dummy.position.y += 0.49;
          this.dummy.updateMatrix();
          head.setMatrixAt(i, this.dummy.matrix);
          head.setColorAt(i, new THREE.Color(skinColors[(i * 7 + stand) % skinColors.length]));
          for (const side of [-1, 1]) {
            this.dummy.position.set(x, row * 0.62 + 0.97, z + side * 0.105);
            this.dummy.updateMatrix();
            legs.setMatrixAt(i * 2 + (side + 1) / 2, this.dummy.matrix);
            arms.setColorAt(i * 2 + (side + 1) / 2,
              new THREE.Color(skinColors[(i * 7 + stand) % skinColors.length]));
          }
        }
      }
      for (let support = 0; support < 5; support++) {
        box(group, steel, [0.2, 10, 0.2], [-13, 5, support * 9 - 18]);
        box(group, steel, [15, 0.18, 0.18], [-6, 9.6, support * 9 - 18]);
      }
      const canopy = box(group, roof, [16, 0.16, 41], [-5.5, 9.9, 0]);
      canopy.rotation.z = -0.06;
      group.add(bodies, head, arms, legs);
      this.crowd.push({ group, arms, head, count });
    }
    void fetch('/race-assets/spectator-head.json', { signal: this.controller.signal })
      .then((response) => response.json()).then((data: { positions: number[]; indices: number[] }) => {
        if (this.disposed) {
          return;
        }
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(data.positions, 3));
        geometry.setIndex(data.indices);
        geometry.computeVertexNormals();
        this.detailedHead = geometry;
        this.invalidate();
      }).catch(() => undefined);
  }

  private buildLandscape() {
    const concrete = material('#ada798');
    const glass = new THREE.MeshStandardMaterial({ color: '#54707e', metalness: 0.7, roughness: 0.22,
      emissive: this.profile.night ? '#b2a17a' : '#000000', emissiveIntensity: 0.45 });
    if (this.profile.urban) {
      for (let i = 0; i < 65; i++) {
        const group = this.place(i / 65, (i % 2 ? 1 : -1) * (70 + i % 5 * 22));
        const height = this.map.id === 'monaco' ? 15 + i % 8 * 3 : 12 + i % 9 * 9;
        box(group, concrete, [15, height, 20], [0, height / 2, 0]);
        for (let floor = 0; floor < height / 3 - 1; floor++) {
          box(group, glass, [15.2, 1.6, 20.2], [0, floor * 3 + 2.4, 0]);
        }
      }
    }
    if (this.profile.water) {
      const group = this.place(0.57, 240);
      const water = new THREE.Mesh(new THREE.CircleGeometry(220, 64),
        new THREE.MeshPhysicalMaterial({ color: '#396f81', metalness: 0.45, roughness: 0.16, clearcoat: 1 }));
      water.rotation.x = -Math.PI / 2;
      water.position.y = -0.19;
      group.add(water);
      for (let i = 0; i < 9; i++) {
        const boat = box(group, material('#e4e0d3'), [4, 1, 12], [i * 12 - 50, 0.5, 5 + i % 3 * 15]);
        box(boat, glass, [2.5, 1.5, 5], [0, 1, 0]);
      }
    }
    if (this.profile.conifers || this.profile.landmark === 'dunes') {
      for (let i = 0; i < 25; i++) {
        const hill = new THREE.Mesh(new THREE.SphereGeometry(1, 32, 16), material(this.profile.terrain));
        const p = trackPose(this.map, i / 25 * this.map.length_m, (i % 2 ? 1 : -1) * 400).position;
        if (this.map.points.some(([x, z]) => Math.hypot(x - p.x, z - p.z) < 165)) {
          continue;
        }
        hill.position.copy(p).y = -50;
        hill.scale.set(150, this.profile.landmark === 'dunes' ? 60 : 85, 120);
        this.add(hill);
      }
    }
    if (this.profile.night) {
      const lamp = new THREE.MeshStandardMaterial({ color: '#ffffff', emissive: '#d7edff', emissiveIntensity: 3 });
      for (let i = 0; i < 90; i++) {
        const group = this.place(i / 90, i % 2 ? 17 : -17);
        box(group, concrete, [0.18, 16, 0.18], [0, 8, 0]);
        box(group, lamp, [2.5, 0.2, 1.2], [0, 16, 0]);
      }
    }
  }

  private buildLandmark() {
    const group = this.place(0.06, -110);
    const bright = material('#dce0db', 0.5);
    const red = material('#b5332e', 0.3);
    const dark = material('#304854', 0.6);
    const kind = this.profile.landmark;
    if (kind === 'wheel') {
      const wheel = new THREE.Mesh(new THREE.TorusGeometry(30, 0.65, 8, 80), bright);
      wheel.position.y = 34;
      group.add(wheel);
      for (let i = 0; i < 24; i++) {
        const angle = i / 24 * Math.PI * 2;
        box(group, red, [3, 3, 3], [Math.cos(angle) * 30, 34 + Math.sin(angle) * 30, 0]);
        const spoke = box(group, bright, [0.12, 60, 0.12], [0, 34, 0]);
        spoke.rotation.z = angle;
      }
      box(group, bright, [2, 34, 2], [0, 17, 0]);
    } else if (kind === 'sphere') {
      const sphere = new THREE.Mesh(new THREE.SphereGeometry(30, 48, 32),
        new THREE.MeshStandardMaterial({ color: '#e29e38', emissive: '#e08321', emissiveIntensity: 0.8 }));
      sphere.position.y = 30;
      group.add(sphere);
      for (let i = 0; i < 12; i++) {
        const ring = new THREE.Mesh(new THREE.TorusGeometry(30.1, 0.12, 4, 64), dark);
        ring.position.y = 30;
        ring.rotation.y = i / 12 * Math.PI;
        group.add(ring);
      }
    } else if (kind === 'tower') {
      box(group, bright, [5, 68, 5], [0, 34, 0]);
      box(group, red, [14, 2, 16], [0, 68, 0]);
      for (let i = 0; i < 8; i++) {
        const rib = box(group, red, [0.35, 70, 0.35], [i - 3.5, 34, 4]);
        rib.rotation.x = 0.13;
      }
    } else if (kind === 'castle') {
      box(group, material('#b2a58e'), [70, 16, 5], [0, 8, 0]);
      for (let i = 0; i < 15; i++) {
        box(group, bright, [2, 2.5, 5], [i * 5 - 35, 17, 0]);
      }
    } else if (kind === 'wing' || kind === 'hotel' || kind === 'stadium') {
      for (let i = 0; i < 9; i++) {
        box(group, dark, [12, 12, 22], [i * 12 - 48, 6, 0]);
        const roof = box(group, bright, [14, 0.35, 28], [i * 12 - 48, 13 + i % 3, 0]);
        roof.rotation.z = i % 2 ? 0.18 : -0.18;
      }
    }
  }

  private buildFences() {
    const count = Math.ceil(this.map.length_m / 5);
    const posts = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.055, 0.07, 3.5, 5),
      material('#838c89', 0.7), count * 2);
    const vertices: number[] = [];
    for (let i = 0; i < count; i++) {
      for (const side of [-1, 1]) {
        const a = trackPose(this.map, i / count * this.map.length_m, side * 14).position;
        const b = trackPose(this.map, (i + 1) / count * this.map.length_m, side * 14).position;
        this.dummy.position.set(a.x, 1.75, a.z);
        this.dummy.rotation.set(0, 0, 0);
        this.dummy.updateMatrix();
        posts.setMatrixAt(i * 2 + (side + 1) / 2, this.dummy.matrix);
        for (let wire = 0; wire < 8; wire++) {
          vertices.push(a.x, 0.5 + wire * 0.4, a.z, b.x, 0.5 + wire * 0.4, b.z);
        }
        vertices.push(a.x, 0.5, a.z, b.x, 3.3, b.z, a.x, 3.3, a.z, b.x, 0.5, b.z);
      }
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    this.add(posts, new THREE.LineSegments(geometry,
      new THREE.LineBasicMaterial({ color: '#5f6a66', transparent: true, opacity: 0.45 })));
  }

  private batchStaticMeshes() {
    this.updateMatrixWorld(true);
    const batches = new Map<THREE.Material, THREE.BufferGeometry[]>();
    const meshes: THREE.Mesh[] = [];
    this.traverse((object) => {
      if (object instanceof THREE.Mesh && !(object instanceof THREE.InstancedMesh)
        && !Array.isArray(object.material)) {
        const material = object.material as THREE.Material;
        const geometry = object.geometry as THREE.BufferGeometry;
        const batch = batches.get(material) ?? [];
        batch.push(geometry.clone().applyMatrix4(object.matrixWorld));
        batches.set(material, batch);
        meshes.push(object as THREE.Mesh);
      }
    });
    for (const mesh of meshes) {
      mesh.geometry.dispose();
      mesh.removeFromParent();
    }
    for (const [material, batch] of batches) {
      const geometry = mergeGeometries(batch);
      batch.forEach((item) => item.dispose());
      if (geometry) {
        const mesh = new THREE.Mesh(geometry, material);
        mesh.castShadow = mesh.receiveShadow = true;
        this.add(mesh);
      }
    }
  }

  private loadTrees() {
    for (let i = 0; i < this.profile.trees; i++) {
      const p = trackPose(this.map, (i * 0.61803398875 % 1) * this.map.length_m,
        (i % 2 ? 1 : -1) * (24 + i * 37 % 140)).position;
      if (!this.map.points.some(([x, z]) => Math.hypot(x - p.x, z - p.z) < 19)) {
        this.treePositions.push(p);
      }
    }
    new GLTFLoader().load(`/race-assets/${this.profile.conifers ? 'fir' : 'broadleaf'}.glb`, (gltf) => {
      this.treeSource = gltf.scene;
      if (this.disposed) {
        this.disposeTree();
        return;
      }
      const bounds = new THREE.Box3().setFromObject(gltf.scene);
      const scale = 12 / bounds.getSize(new THREE.Vector3()).y;
      gltf.scene.scale.multiplyScalar(scale);
      gltf.scene.position.y = -bounds.min.y * scale;
      for (let i = 0; i < 12; i++) {
        const tree = new THREE.Group();
        tree.add(gltf.scene.clone(true));
        this.treePool.push(tree);
        this.add(tree);
      }
      this.invalidate();
    }, undefined, () => undefined);
  }

  update(time: number, camera: THREE.Vector3, high: boolean) {
    if (time - this.lastUpdate < 1 / 24) {
      return;
    }
    this.lastUpdate = time;
    const nearest = [...this.treePositions].sort((a, b) =>
      a.distanceToSquared(camera) - b.distanceToSquared(camera));
    for (const [i, tree] of this.treePool.entries()) {
      const p = nearest[i];
      tree.visible = high && Boolean(p && p.distanceTo(camera) < 180);
      if (p) {
        tree.position.copy(p);
      }
    }
    for (const { group, arms, head, count } of this.crowd) {
      const distance = group.position.distanceTo(camera);
      head.geometry = high && distance < 65 && this.detailedHead ? this.detailedHead : this.simpleHead;
      if (distance > 180 && arms.userData['posed']) {
        continue;
      }
      for (let i = 0; i < count; i++) {
        const row = Math.floor(i / 24);
        for (const side of [-1, 1]) {
          const wave = Math.sin(time * 3 + i * 1.71) * 0.25;
          this.dummy.position.set(-row * 1.6, row * 0.62 + 1.9, (i % 24 - 11.5) * 1.5 + side * 0.29);
          this.dummy.rotation.set(side * (0.3 + wave), 0, Math.sin(i) * 0.4);
          this.dummy.updateMatrix();
          arms.setMatrixAt(i * 2 + (side + 1) / 2, this.dummy.matrix);
        }
      }
      arms.instanceMatrix.needsUpdate = true;
      arms.userData['posed'] = true;
    }
  }

  private disposeTree() {
    this.treeSource?.traverse((object) => {
      if (object instanceof THREE.Mesh) {
        (object.geometry as THREE.BufferGeometry).dispose();
        const materials = object.material as THREE.Material | THREE.Material[];
        for (const item of Array.isArray(materials) ? materials : [materials]) {
          Object.values(item).forEach((value: unknown) => {
            if (value instanceof THREE.Texture) {
              value.dispose();
            }
          });
          item.dispose();
        }
      }
    });
  }

  override dispose() {
    this.disposed = true;
    this.controller.abort();
    this.detailedHead?.dispose();
    this.simpleHead.dispose();
    this.disposeTree();
  }
}
