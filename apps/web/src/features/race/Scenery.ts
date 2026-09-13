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
  private wind = 0;
  private readonly detailMeshes: THREE.Object3D[] = [];

  constructor(private readonly map: CircuitMap, private readonly profile: SceneryProfile,
    private readonly invalidate: () => void) {
    super();
    this.name = 'Circuit surroundings';
    this.buildGrandstands();
    this.buildLandscape();
    this.buildLandmark();
    this.buildFences();
    this.buildGroundDetails();
    this.buildTrackLife();
    this.buildInfrastructure();
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

  private buildGroundDetails() {
    const bladeCount = Math.min(7200, 900 + this.profile.trees * 8);
    const bladeGeometry = new THREE.PlaneGeometry(0.45, 1.2);
    bladeGeometry.translate(0, 0.58, 0);
    const grass = new THREE.InstancedMesh(bladeGeometry,
      new THREE.MeshStandardMaterial({ color: '#50673a', roughness: 1, side: THREE.DoubleSide }), bladeCount);
    for (let i = 0; i < bladeCount; i++) {
      const progress = i * 0.61803398875 % 1;
      const spread = 16 + (i * 47 % 32);
      const pose = trackPose(this.map, progress * this.map.length_m, (i % 2 ? 1 : -1) * spread);
      const scale = 0.35 + (i * 31 % 100) / 130;
      this.dummy.position.copy(pose.position).y = 0;
      this.dummy.rotation.set(0, pose.yaw + i * 2.39996, (i % 7 - 3) * 0.03);
      this.dummy.scale.set(scale, scale, scale);
      this.dummy.updateMatrix();
      grass.setMatrixAt(i, this.dummy.matrix);
      grass.setColorAt(i, new THREE.Color().setHSL(0.19 + i % 9 * 0.006, 0.27, 0.29 + i % 7 * 0.018));
    }
    grass.receiveShadow = true;
    this.add(grass);
    this.detailMeshes.push(grass);

    const shrubCount = Math.min(850, 120 + this.profile.trees);
    const shrubs = new THREE.InstancedMesh(new THREE.DodecahedronGeometry(1, 1),
      material('#445e35'), shrubCount);
    for (let i = 0; i < shrubCount; i++) {
      const pose = trackPose(this.map, (i * 0.754877666 % 1) * this.map.length_m,
        (i % 2 ? 1 : -1) * (21 + i * 29 % 85));
      const radius = 0.5 + i % 9 * 0.13;
      this.dummy.position.copy(pose.position).y = radius * 0.7;
      this.dummy.rotation.set(i * 0.11, i * 1.7, 0);
      this.dummy.scale.set(radius * 1.4, radius, radius * 1.2);
      this.dummy.updateMatrix();
      shrubs.setMatrixAt(i, this.dummy.matrix);
      shrubs.setColorAt(i, new THREE.Color().setHSL(0.22 + i % 11 * 0.004, 0.26, 0.25 + i % 5 * 0.025));
    }
    shrubs.castShadow = shrubs.receiveShadow = true;
    this.add(shrubs);
    this.detailMeshes.push(shrubs);
  }

  private buildTrackLife() {
    const workerCount = 72;
    const orange = material('#ff5a1f');
    const skin = material('#b77c5b');
    const dark = material('#151b20');
    const concrete = material('#a5a59e');
    const steel = material('#6d7677', 0.7);
    const workers = new THREE.InstancedMesh(new THREE.CapsuleGeometry(0.16, 0.68, 4, 8), orange, workerCount);
    const heads = new THREE.InstancedMesh(new THREE.SphereGeometry(0.14, 10, 8), skin, workerCount);
    const tireCount = 320;
    const tires = new THREE.InstancedMesh(new THREE.TorusGeometry(0.34, 0.12, 7, 14), dark, tireCount);
    for (let station = 0; station < 12; station++) {
      const side = station % 2 ? 1 : -1;
      const progress = (station + 0.12) / 12;
      const group = this.place(progress, side * 19.5);
      box(group, concrete, [3.8, 0.25, 2.6], [0, 0.12, 0]);
      box(group, steel, [0.14, 2.9, 0.14], [-1.7, 1.45, -1.1]);
      box(group, steel, [0.14, 2.9, 0.14], [-1.7, 1.45, 1.1]);
      box(group, steel, [0.14, 2.9, 0.14], [1.7, 1.45, -1.1]);
      box(group, steel, [0.14, 2.9, 0.14], [1.7, 1.45, 1.1]);
      const roof = box(group, orange, [4.4, 0.18, 3.2], [0, 3, 0]);
      roof.rotation.z = side * 0.035;
      for (let person = 0; person < 6; person++) {
        const index = station * 6 + person;
        const local = new THREE.Vector3((person % 3 - 1) * 0.78, 0.68, (Math.floor(person / 3) - 0.5) * 0.86);
        local.applyAxisAngle(new THREE.Vector3(0, 1, 0), group.rotation.y).add(group.position);
        this.dummy.position.copy(local);
        this.dummy.rotation.set(0, group.rotation.y + (person % 3 - 1) * 0.22, 0);
        this.dummy.scale.setScalar(1);
        this.dummy.updateMatrix();
        workers.setMatrixAt(index, this.dummy.matrix);
        this.dummy.position.y += 0.57;
        this.dummy.updateMatrix();
        heads.setMatrixAt(index, this.dummy.matrix);
      }
    }
    for (let i = 0; i < tireCount; i++) {
      const section = Math.floor(i / 20);
      const pose = trackPose(this.map, (section + 0.36) / 16 * this.map.length_m,
        (section % 2 ? 1 : -1) * 14.35);
      const local = new THREE.Vector3((i % 4 - 1.5) * 0.36, 0.34 + Math.floor(i % 20 / 4) * 0.38,
        (i % 5 - 2) * 0.36).applyAxisAngle(new THREE.Vector3(0, 1, 0), pose.yaw).add(pose.position);
      this.dummy.position.copy(local);
      this.dummy.rotation.set(Math.PI / 2, pose.yaw, 0);
      this.dummy.scale.setScalar(1);
      this.dummy.updateMatrix();
      tires.setMatrixAt(i, this.dummy.matrix);
    }
    workers.castShadow = heads.castShadow = tires.castShadow = true;
    workers.receiveShadow = heads.receiveShadow = tires.receiveShadow = true;
    this.add(workers, heads, tires);

    const boardCanvas = document.createElement('canvas');
    boardCanvas.width = 1024;
    boardCanvas.height = 256;
    const boardContext = boardCanvas.getContext('2d');
    if (boardContext) {
      boardContext.fillStyle = '#d7ff45';
      boardContext.fillRect(0, 0, 1024, 256);
      boardContext.fillStyle = '#0b171b';
      boardContext.font = 'italic 900 142px Arial';
      boardContext.textAlign = 'center';
      boardContext.fillText('AFTERLAP', 512, 181);
    }
    const boardTexture = new THREE.CanvasTexture(boardCanvas);
    boardTexture.colorSpace = THREE.SRGBColorSpace;
    const boardMaterial = new THREE.MeshStandardMaterial({ map: boardTexture, roughness: 0.52,
      emissive: this.profile.night ? '#395000' : '#000000', emissiveIntensity: 0.42 });
    for (let i = 0; i < 36; i++) {
      const side = i % 2 ? 1 : -1;
      const group = this.place((i + 0.25) / 36, side * 14.6);
      const board = new THREE.Mesh(new THREE.PlaneGeometry(5.8, 1.45), boardMaterial);
      board.position.y = 1.55;
      board.rotation.y = side < 0 ? Math.PI : 0;
      board.castShadow = board.receiveShadow = true;
      group.add(board);
    }

    for (let i = 0; i < 14; i++) {
      const side = i % 2 ? 1 : -1;
      const group = this.place((i + 0.55) / 14, side * 22);
      box(group, steel, [0.18, 4.2, 0.18], [0, 2.1, 0]);
      const camera = new THREE.Mesh(new THREE.BoxGeometry(0.58, 0.4, 0.82), dark);
      camera.position.set(0, 4.3, 0);
      camera.rotation.y = side < 0 ? Math.PI : 0;
      camera.castShadow = true;
      group.add(camera);
      const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.2, 0.35, 16),
        new THREE.MeshPhysicalMaterial({ color: '#182e43', metalness: 0.7, roughness: 0.12, clearcoat: 1 }));
      lens.rotation.x = Math.PI / 2;
      lens.position.set(0, 4.3, side < 0 ? 0.56 : -0.56);
      group.add(lens);
    }
  }

  private buildInfrastructure() {
    const asphalt = material('#343a3d');
    const concrete = material('#b7b7af');
    const dark = material('#1c2930', 0.35);
    const glass = new THREE.MeshPhysicalMaterial({ color: '#43616e', metalness: 0.4, roughness: 0.15,
      transmission: 0.12, clearcoat: 1, emissive: this.profile.night ? '#8b9d88' : '#000000',
      emissiveIntensity: 0.35 });
    const red = material('#c72531', 0.25);
    const rubber = material('#17191a');
    for (let i = 0; i < 9; i++) {
      const group = this.place(0.01 + i * 0.004, -48 - i % 2 * 12);
      box(group, asphalt, [12, 0.08, 16], [0, 0.02, 0]);
      const height = 4.5 + i % 3 * 1.8;
      box(group, concrete, [10, height, 13], [0, height / 2, 0]);
      box(group, glass, [10.1, 1.25, 13.1], [0, height - 1.25, 0]);
      box(group, dark, [10.8, 0.22, 14], [0, height + 0.15, 0]);
      for (const z of [-4.5, 0, 4.5]) {
        box(group, dark, [0.12, height - 1.8, 2.8], [5.06, (height - 1.8) / 2, z]);
      }
    }
    for (let i = 0; i < 18; i++) {
      const side = i % 2 ? 1 : -1;
      const group = this.place((i + 0.71) / 18, side * (26 + i % 3 * 3));
      const bodyColor = i % 4 === 0 ? red : i % 4 === 1 ? concrete : dark;
      box(group, bodyColor, [2.3, 1.65, 5.8], [0, 1.15, 0]);
      box(group, glass, [2.34, 0.75, 1.55], [0, 1.75, -2.2]);
      for (const x of [-1.2, 1.2]) {
        for (const z of [-1.85, 1.85]) {
          const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.45, 0.3, 16), rubber);
          wheel.position.set(x, 0.48, z);
          wheel.rotation.z = Math.PI / 2;
          wheel.castShadow = true;
          group.add(wheel);
        }
      }
    }
    for (let i = 0; i < 28; i++) {
      const side = i % 2 ? 1 : -1;
      const group = this.place((i + 0.18) / 28, side * 24);
      box(group, dark, [0.22, 11, 0.22], [0, 5.5, 0]);
      box(group, dark, [4.8, 0.16, 0.16], [-side * 2.25, 10.8, 0]);
      const lamp = new THREE.Mesh(new THREE.BoxGeometry(2.6, 0.24, 1.25),
        new THREE.MeshStandardMaterial({ color: '#e5eee8', emissive: '#d8f2ff',
          emissiveIntensity: this.profile.night ? 5 : 0.15 }));
      lamp.position.set(-side * 4.35, 10.65, 0);
      group.add(lamp);
      if (this.profile.night) {
        const light = new THREE.SpotLight('#d8efff', 38, 45, 0.75, 0.65, 1.3);
        light.position.copy(lamp.position);
        light.target.position.set(-side * 9, 0, 0);
        group.add(light, light.target);
      }
    }
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

  update(time: number, camera: THREE.Vector3, detailed: boolean) {
    if (time - this.lastUpdate < 1 / 24) {
      return;
    }
    this.lastUpdate = time;
    for (const mesh of this.detailMeshes) {
      mesh.visible = detailed;
    }
    const nearest = [...this.treePositions].sort((a, b) =>
      a.distanceToSquared(camera) - b.distanceToSquared(camera));
    for (const [i, tree] of this.treePool.entries()) {
      const p = nearest[i];
      tree.visible = detailed && Boolean(p && p.distanceTo(camera) < 180);
      if (p) {
        tree.position.copy(p);
        tree.rotation.z = Math.sin(time * 0.85 + i * 1.7) * Math.min(0.075, Math.abs(this.wind) * 0.005);
      }
    }
    for (const { group, arms, head, count } of this.crowd) {
      const distance = group.position.distanceTo(camera);
      head.geometry = detailed && distance < 65 && this.detailedHead ? this.detailedHead : this.simpleHead;
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

  setWind(wind: number) {
    this.wind = wind;
  }

  get detailsVisible() {
    return this.detailMeshes.every((mesh) => mesh.visible);
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
