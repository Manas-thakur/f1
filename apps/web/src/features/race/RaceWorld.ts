import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { Sky } from 'three/addons/objects/Sky.js';

import { energyMode } from './energyStatus';
import { Branding } from './Branding';
import { sceneryProfile } from './circuitScenery';
import { Scenery } from './Scenery';
import { Minimap } from './Minimap';
import { RaceMotion } from './motion';
import type { CircuitMap, RaceFrame } from './types';
import { box, createCar, foliageTexture, ribbon, spinWheels, surfaceTexture, trackPose } from './worldGeometry';

export type CameraMode = 'chase' | 'cockpit' | 'orbit' | 'track';

export class RaceWorld {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(52, 1, 0.12, 16000);
  readonly controls: OrbitControls;
  private readonly cars = new Map<string, THREE.Group>();
  private readonly sun = new THREE.DirectionalLight('#fff1d5', 3.2);
  private readonly resize: ResizeObserver;
  private readonly environment: THREE.WebGLRenderTarget;
  private readonly center: THREE.Vector3;
  private readonly span: number;
  private frame: RaceFrame | null = null;
  private selected = 'car-01';
  private mode: CameraMode = 'chase';
  private disposed = false;
  private dirty = true;
  private distance = 1;
  private rendered = 0;
  private fpsAt = performance.now();
  private fpsFrames = 0;
  private readonly onFps: (fps: number) => void;
  private readonly motion = new RaceMotion();
  private readonly minimap: Minimap;
  private readonly surroundings: Scenery;
  private readonly branding: Branding;
  private mapCanvas: HTMLCanvasElement | null = null;
  private readonly lastFollowPosition = new THREE.Vector3();
  private followedCar: string | null = null;
  private readonly raycaster = new THREE.Raycaster();
  private pointerStart = new THREE.Vector2();
  private readonly onMode: (mode: CameraMode) => void;
  private readonly onSelect: (id: string) => void;
  private readonly onError: (message: string) => void;

  constructor(
    private readonly host: HTMLElement,
    private readonly map: CircuitMap,
    onMode: (mode: CameraMode) => void,
    onSelect: (id: string) => void,
    onError: (message: string) => void,
    onFps: (fps: number) => void,
  ) {
    this.minimap = new Minimap(map);
    this.onFps = onFps;
    this.onMode = onMode;
    this.onSelect = onSelect;
    this.onError = onError;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    const gl = this.renderer.getContext();
    const debug = gl.getExtension('WEBGL_debug_renderer_info');
    const device: unknown = debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : '';
    const software = typeof device === 'string' && /swiftshader|llvmpipe|software/i.test(device);
    this.renderer.setPixelRatio(software ? 0.65 : Math.min(window.devicePixelRatio, 1.75));
    this.renderer.shadowMap.enabled = !software;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 0.75;
    this.renderer.domElement.setAttribute('aria-label', 'Interactive 3D race scene');
    this.renderer.domElement.setAttribute('role', 'img');
    host.appendChild(this.renderer.domElement);
    const bounds = new THREE.Box3().setFromPoints(map.points.map(([x, z]) => new THREE.Vector3(x, 0, z)));
    this.center = bounds.getCenter(new THREE.Vector3());
    this.span = Math.max(...bounds.getSize(new THREE.Vector3()).toArray());
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    const room = new RoomEnvironment();
    this.environment = pmrem.fromScene(room, 0.04);
    this.scene.environment = this.environment.texture;
    room.dispose();
    pmrem.dispose();
    const profile = sceneryProfile(map.id);
    this.scene.fog = new THREE.FogExp2(profile.night ? '#243440' : '#b7c8cc', 0.0002);
    this.renderer.toneMappingExposure = profile.night ? 0.65 : 0.85;
    this.scene.add(new THREE.HemisphereLight('#d7edff', '#39402e', 0.8));
    const sky = new Sky();
    sky.scale.setScalar(12000);
    Object.assign(sky.material.uniforms, {
      turbidity: { value: 3 }, rayleigh: { value: 1.6 },
      sunPosition: { value: new THREE.Vector3(0.6, profile.night ? -0.025 : 0.35, -0.45) },
    });
    this.scene.add(sky);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(1024, 1024);
    Object.assign(this.sun.shadow.camera, { left: -65, right: 65, top: 65, bottom: -65, near: 1, far: 350 });
    this.sun.shadow.normalBias = 0.035;
    this.scene.add(this.sun, this.sun.target);
    this.buildTrack();
    this.branding = new Branding(map,
      Math.min(this.renderer.capabilities.getMaxAnisotropy(), 16), () => { this.dirty = true; });
    this.scene.add(this.branding);
    this.surroundings = new Scenery(map, profile, () => { this.dirty = true; });
    this.scene.add(this.surroundings);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;
    this.controls.minDistance = 3;
    this.controls.maxDistance = this.span * 2;
    this.controls.maxPolarAngle = Math.PI / 2 - 0.02;
    this.controls.zoomToCursor = true;
    const startingView = trackPose(map, 0);
    this.controls.target.copy(startingView.position);
    this.camera.position.copy(startingView.position).add(new THREE.Vector3(15, 10, -20));
    this.controls.update();
    this.controls.addEventListener('start', this.releaseCamera);
    this.renderer.domElement.addEventListener('pointerdown', this.pointerDown);
    this.renderer.domElement.addEventListener('pointerup', this.pointerUp);
    this.renderer.domElement.addEventListener('dblclick', this.focusCar);
    this.renderer.domElement.addEventListener('webglcontextlost', this.contextLost);
    this.resize = new ResizeObserver(() => this.resizeCanvas());
    this.resize.observe(host);
    this.resizeCanvas();
    this.renderer.setAnimationLoop(this.animate);
  }

  private buildTrack() {
    const loader = new THREE.TextureLoader();
    const loaded = () => { this.dirty = true; };
    const paved = ['monaco', 'baku', 'singapore', 'las-vegas'].includes(this.map.id);
    const sandy = ['lusail', 'yas-marina', 'madring', 'zandvoort'].includes(this.map.id);
    const grass = paved || sandy ? surfaceTexture(paved ? 'asphalt' : 'gravel')
      : loader.load('/race-assets/leafy-grass.jpg', loaded);
    const grassNormal = paved || sandy ? null : loader.load('/race-assets/leafy-grass-normal.jpg', loaded);
    for (const texture of grassNormal ? [grass, grassNormal] : [grass]) {
      texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
      texture.repeat.set(3500, 3500);
      texture.anisotropy = 8;
    }
    grass.colorSpace = THREE.SRGBColorSpace;
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(14000, 14000, 64, 64),
      new THREE.MeshStandardMaterial({ color: sceneryProfile(this.map.id).terrain,
        map: grass, normalMap: grassNormal,
        normalScale: new THREE.Vector2(0.4, 0.4), roughness: 1 }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.copy(this.center).y = -0.25;
    ground.receiveShadow = true;
    this.scene.add(ground);
    const asphalt = surfaceTexture('asphalt');
    const road = new THREE.Mesh(ribbon(this.map, -6, 6, 0.025),
      new THREE.MeshStandardMaterial({ map: asphalt, roughness: 0.93, side: THREE.DoubleSide }));
    road.receiveShadow = true;
    this.scene.add(road);
    const curb = new THREE.MeshStandardMaterial({ map: surfaceTexture('curb'), roughness: 0.8,
      side: THREE.DoubleSide });
    const white = new THREE.MeshStandardMaterial({ color: '#f1eee1', roughness: 0.8,
      side: THREE.DoubleSide });
    const gravel = new THREE.MeshStandardMaterial({ map: surfaceTexture('gravel'), color: sceneryProfile(this.map.id).runoff, roughness: 1,
      side: THREE.DoubleSide });
    const barrier = new THREE.MeshStandardMaterial({ color: '#91999b', roughness: 0.4, metalness: 0.65 });
    for (const side of [-1, 1]) {
      this.scene.add(new THREE.Mesh(ribbon(this.map, side * 6, side * 6.9, 0.045), curb));
      this.scene.add(new THREE.Mesh(ribbon(this.map, side * 5.75, side * 5.87, 0.04), white));
      this.scene.add(new THREE.Mesh(ribbon(this.map, side * 7, side * 11, 0.01), gravel));
      const points = Array.from({ length: this.map.points.length + 1 }, (_, i) => {
        const p = trackPose(this.map, i / this.map.points.length * this.map.length_m, side * 13).position;
        p.y = 0.8;
        return p;
      });
      const rail = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points),
        this.map.points.length, 0.14, 5, true), barrier);
      this.scene.add(rail);
    }
    const treeCount = sceneryProfile(this.map.id).trees;
    const leaves = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1),
      new THREE.MeshStandardMaterial({ map: foliageTexture(), roughness: 1,
        alphaTest: 0.45, side: THREE.DoubleSide }), treeCount * 12);
    const trunks = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.22, 0.4, 1, 7),
      new THREE.MeshStandardMaterial({ color: '#625544', roughness: 1 }), treeCount);
    const dummy = new THREE.Object3D();
    let accepted = 0;
    for (let i = 0; i < treeCount * 2 && accepted < treeCount; i++) {
      const s = (i * 0.61803398875 % 1) * this.map.length_m;
      const offset = (i % 2 ? 1 : -1) * (24 + (i * 37 % 140));
      const p = trackPose(this.map, s, offset).position;
      if (this.map.points.some(([x, z]) => Math.hypot(x - p.x, z - p.z) < 19)) {
        continue;
      }
      const height = 6 + (i * 13 % 8);
      dummy.position.set(p.x, height * 0.72, p.z);
      dummy.scale.set(height * 0.38, height * 0.48, height * 0.34);
      dummy.rotation.y = i;
      dummy.updateMatrix();
      for (let cluster = 0; cluster < 4; cluster++) {
        const angle = cluster * 2.4 + i;
        dummy.position.set(p.x + Math.cos(angle) * height * 0.17,
          height * (0.5 + cluster * 0.1), p.z + Math.sin(angle) * height * 0.17);
        dummy.scale.set(height * 0.65, height * 0.68, 1);
        for (let plane = 0; plane < 3; plane++) {
          dummy.rotation.set(plane === 2 ? 0.55 : -0.15, angle + plane * Math.PI / 3, 0);
          dummy.updateMatrix();
          leaves.setMatrixAt(accepted * 12 + cluster * 3 + plane, dummy.matrix);
          leaves.setColorAt(accepted * 12 + cluster * 3 + plane,
            new THREE.Color().setHSL(0.23, 0.12, 0.7 + i % 4 * 0.07));
        }
      }
      dummy.position.set(p.x, height * 0.25, p.z);
      dummy.rotation.set(0, i, 0);
      dummy.position.y = height * 0.25;
      dummy.scale.set(1, height * 0.5, 1);
      dummy.updateMatrix();
      trunks.setMatrixAt(accepted, dummy.matrix);
      accepted++;
    }
    leaves.count = accepted * 12;
    trunks.count = accepted;
    leaves.castShadow = true;
    this.scene.add(leaves, trunks);
    const postCount = Math.ceil(this.map.length_m / 8);
    const posts = new THREE.InstancedMesh(new THREE.BoxGeometry(0.12, 1, 0.16), barrier, postCount * 2);
    for (let i = 0; i < postCount; i++) {
      for (const [j, side] of [-1, 1].entries()) {
        const pose = trackPose(this.map, i / postCount * this.map.length_m, side * 13);
        dummy.position.copy(pose.position).y = 0.5;
        dummy.rotation.set(0, pose.yaw, 0);
        dummy.scale.setScalar(1);
        dummy.updateMatrix();
        posts.setMatrixAt(i * 2 + j, dummy.matrix);
      }
    }
    this.scene.add(posts);
    const start = trackPose(this.map, 0);
    const paddock = new THREE.Group();
    paddock.position.copy(start.position);
    paddock.rotation.y = start.yaw;
    const dark = new THREE.MeshStandardMaterial({ color: '#27343d', metalness: 0.4, roughness: 0.45 });
    const concrete = new THREE.MeshStandardMaterial({ color: '#b5b5ac', roughness: 0.9 });
    for (let i = 0; i < 12; i++) {
      for (let j = 0; j < 2; j++) {
        box(paddock, (i + j) % 2 ? dark : white, [1, 0.012, 0.6], [i - 5.5, 0.06, j * 0.6]);
      }
    }
    box(paddock, dark, [0.35, 6.5, 0.35], [-9, 3.25, 0]);
    box(paddock, dark, [0.35, 6.5, 0.35], [9, 3.25, 0]);
    box(paddock, dark, [18.4, 1, 0.6], [0, 6.2, 0]);
    for (let i = 0; i < 5; i++) {
      box(paddock, new THREE.MeshStandardMaterial({ color: '#a02927' }),
        [0.23, 0.23, 0.1], [i * 0.45 - 0.9, 6.2, -0.36]);
    }
    for (let i = 0; i < 10; i++) {
      box(paddock, concrete, [8, 4, 8], [24, 2, i * 9 - 35]);
      box(paddock, dark, [0.1, 2.6, 6], [19.95, 1.4, i * 9 - 35]);
      box(paddock, dark, [9, 0.22, 8.5], [23.5, 4.2, i * 9 - 35]);
    }
    this.scene.add(paddock);
  }

  update(frame: RaceFrame, selected: string) {
    this.dirty = true;
    this.selected = selected;
    if (frame.generation !== this.frame?.generation) {
      this.followedCar = null;
    }
    if (frame !== this.frame) {
      this.motion.push(frame, performance.now());
    }
    this.frame = frame;
    this.host.dataset['boostingCars'] = frame.cars.filter((car) => energyMode(car) === 'BOOST').map((car) => car.id).join(',');
    const ids = new Set(frame.cars.map((car) => car.id));
    for (const [id, model] of this.cars) {
      model.visible = ids.has(id);
    }
    for (const car of frame.cars) {
      let model = this.cars.get(car.id);
      if (!model) {
        model = createCar(Number(car.id.slice(-2)) - 1);
        model.userData['carId'] = car.id;
        const boost = new THREE.Group();
        boost.name = 'electrical-boost';
        boost.position.z = -2.6;
        for (const side of [-1, 1]) {
          const material = new THREE.MeshBasicMaterial({ color: '#48dfff', transparent: true,
            opacity: 0.65, depthWrite: false, blending: THREE.AdditiveBlending });
          const streak = new THREE.Mesh(new THREE.ConeGeometry(0.14, 4, 8), material);
          streak.rotation.x = -Math.PI / 2;
          streak.position.set(side * 0.65, 0.3, -2);
          boost.add(streak);
        }
        model.add(boost);
        this.cars.set(car.id, model);
        this.scene.add(model);
      }
      const boost = model.getObjectByName('electrical-boost');
      if (boost) {
        boost.visible = energyMode(car) === 'BOOST' && car.finish_time_s === null;
        boost.scale.z = Math.max(0.25, Math.min(1, (car.channels['electrical_power_w'] ?? 0) / 350000));
      }
      model.visible = car.channels['s_m'] !== undefined;
    }
  }

  setMode(mode: CameraMode) {
    this.dirty = true;
    this.mode = mode;
    this.camera.fov = mode === 'cockpit' ? 82 : 58;
    this.camera.updateProjectionMatrix();
    this.distance = 1;
    this.onMode(mode);
    const car = this.cars.get(this.selected);
    if (car) {
      this.lastFollowPosition.copy(car.position);
    }
    if (mode === 'track') {
      this.controls.target.copy(this.center);
      this.camera.position.copy(this.center)
        .add(new THREE.Vector3(this.span * 0.3, this.span, this.span * 0.6));
    } else if (mode === 'orbit' && car) {
      this.controls.target.copy(car.position).y = 0.65;
      this.camera.position.copy(car.position).add(new THREE.Vector3(6, 3, 8));
    }
    this.controls.update();
  }

  setMinimap(canvas: HTMLCanvasElement | null) {
    this.mapCanvas = canvas;
    this.dirty = true;
  }

  setQuality(high: boolean) {
    this.renderer.setPixelRatio(high ? Math.min(window.devicePixelRatio, 1.75) : 0.65);
    this.renderer.shadowMap.enabled = high;
    this.resizeCanvas();
  }

  get highQuality() {
    return this.renderer.shadowMap.enabled;
  }

  zoom(factor: number) {
    this.dirty = true;
    if (this.mode === 'chase' || this.mode === 'cockpit') {
      this.distance = THREE.MathUtils.clamp(this.distance * factor, 0.55, 4);
      if (this.mode === 'cockpit') {
        this.camera.fov = THREE.MathUtils.clamp(this.camera.fov * factor, 30, 90);
        this.camera.updateProjectionMatrix();
      }
    } else {
      this.camera.position.sub(this.controls.target).multiplyScalar(factor).add(this.controls.target);
      this.controls.update();
    }
  }

  private releaseCamera = () => {
    if (this.mode === 'chase' || this.mode === 'cockpit') {
      this.mode = 'orbit';
      const car = this.cars.get(this.selected);
      if (car) {
        this.lastFollowPosition.copy(car.position);
      }
      this.onMode('orbit');
    }
  };

  private pointerDown = (event: PointerEvent) => {
    this.pointerStart.set(event.clientX, event.clientY);
  };

  private pointerUp = (event: PointerEvent) => {
    const movement = this.pointerStart.distanceTo(new THREE.Vector2(event.clientX, event.clientY));
    if (event.button !== 0 || movement > 5) {
      return;
    }
    const bounds = this.renderer.domElement.getBoundingClientRect();
    this.raycaster.setFromCamera(new THREE.Vector2(
      (event.clientX - bounds.left) / bounds.width * 2 - 1,
      -(event.clientY - bounds.top) / bounds.height * 2 + 1,
    ), this.camera);
    const visible = [...this.cars.values()].filter((car) => car.visible);
    const hit = this.raycaster.intersectObjects(visible, true)[0];
    let object: THREE.Object3D | null = hit?.object ?? null;
    while (object) {
      const id: unknown = object.userData['carId'];
      if (typeof id === 'string') {
        this.onSelect(id);
        return;
      }
      object = object.parent;
    }
  };

  private focusCar = () => this.setMode('orbit');

  private contextLost = (event: Event) => {
    event.preventDefault();
    this.renderer.setAnimationLoop(null);
    this.onError('The graphics context was lost. Reload the 3D view to reconnect it.');
  };

  private resizeCanvas() {
    this.dirty = true;
    const width = this.host.clientWidth;
    const height = this.host.clientHeight;
    this.renderer.setSize(width, height);
    this.camera.aspect = width / Math.max(1, height);
    this.camera.updateProjectionMatrix();
  }

  private animate = () => {
    if (this.disposed) {
      return;
    }
    const renderedPoses = this.motion.sample(performance.now());
    for (const [id, model] of this.cars) {
      const pose = renderedPoses.get(id);
      model.visible = Boolean(pose);
      if (pose) {
        const slope = (pose.lateralRate ?? 0) / Math.max(1, pose.speed ?? 0);
        const location = trackPose(this.map, pose.progress, pose.lateral, slope);
        model.position.copy(location.position);
        model.rotation.y = location.yaw;
        spinWheels(model, pose.progress);
      }
    }
    const car = this.cars.get(this.selected);
    if (car?.visible) {
      if (this.mode === 'chase' || this.mode === 'cockpit') {
        const cockpit = this.mode === 'cockpit';
        const offset = new THREE.Vector3(cockpit ? 0 : 0.7, cockpit ? 0.86 : 5.1 * this.distance,
          cockpit ? -0.02 : -13 * this.distance).applyAxisAngle(new THREE.Vector3(0, 1, 0), car.rotation.y);
        const target = new THREE.Vector3(0, cockpit ? 0.86 : 0.9, cockpit ? 30 : 8)
          .applyAxisAngle(new THREE.Vector3(0, 1, 0), car.rotation.y).add(car.position);
        this.camera.position.copy(car.position).add(offset);
        this.controls.target.copy(target);
      }
      if (this.mode === 'orbit') {
        const movement = this.followedCar === this.selected
          ? car.position.clone().sub(this.lastFollowPosition)
          : car.position.clone().add(new THREE.Vector3(0, 0.65, 0)).sub(this.controls.target);
        this.camera.position.add(movement);
        this.controls.target.add(movement);
      }
      this.lastFollowPosition.copy(car.position);
      this.followedCar = this.selected;
      this.sun.position.copy(car.position).add(new THREE.Vector3(80, 120, -60));
      this.sun.target.position.copy(car.position);
    } else {
      this.followedCar = null;
    }
    const following = this.mode === 'chase' || this.mode === 'cockpit';
    if (following) {
      this.camera.lookAt(this.controls.target);
    }
    const changed = following ? false : this.controls.update();
    if (!following) {
      this.camera.position.y = Math.max(0.65, this.camera.position.y);
      this.controls.target.y = Math.max(0, this.controls.target.y);
      const horizontal = new THREE.Vector2(
        this.camera.position.x - this.center.x, this.camera.position.z - this.center.z);
      if (horizontal.length() > this.span * 1.5) {
        horizontal.setLength(this.span * 1.5);
        this.camera.position.x = this.center.x + horizontal.x;
        this.camera.position.z = this.center.z + horizontal.y;
      }
    }
    if (!changed && !this.dirty && this.frame?.status !== 'running') {
      return;
    }
    this.dirty = false;
    this.surroundings.update(performance.now() / 1000, this.camera.position, this.highQuality);
    this.renderer.render(this.scene, this.camera);
    if (this.mapCanvas) {
      this.minimap.draw(this.mapCanvas, this.cars, this.selected);
    }
    this.rendered++;
    this.fpsFrames++;
    const now = performance.now();
    if (now - this.fpsAt >= 1000) {
      this.onFps(Math.round(this.fpsFrames * 1000 / (now - this.fpsAt)));
      this.fpsFrames = 0;
      this.fpsAt = now;
    }
    this.host.dataset['renderedFrames'] = String(this.rendered);
    this.host.dataset['cameraPosition'] = this.camera.position.toArray().map((n) => n.toFixed(2)).join(',');
    this.host.dataset['cameraTarget'] = this.controls.target.toArray().join(',');
    this.host.dataset['followedPosition'] = car?.visible ? car.position.toArray().join(',') : '';
    this.host.dataset['observedTime'] = String(this.frame?.time_s ?? 0);
    this.host.dataset['brandingDecals'] = String(this.branding.decalCount);
  };

  dispose() {
    this.disposed = true;
    this.renderer.setAnimationLoop(null);
    this.resize.disconnect();
    this.branding.dispose();
    this.surroundings.dispose();
    this.controls.dispose();
    this.renderer.domElement.removeEventListener('pointerdown', this.pointerDown);
    this.renderer.domElement.removeEventListener('pointerup', this.pointerUp);
    this.renderer.domElement.removeEventListener('dblclick', this.focusCar);
    this.renderer.domElement.removeEventListener('webglcontextlost', this.contextLost);
    const geometries = new Set<THREE.BufferGeometry>();
    const materials = new Set<THREE.Material>();
    const textures = new Set<THREE.Texture>();
    this.scene.traverse((object) => {
      if (object instanceof THREE.InstancedMesh) {
        object.dispose();
      }
      if (object instanceof THREE.Mesh || object instanceof THREE.LineSegments) {
        geometries.add(object.geometry as THREE.BufferGeometry);
        const material = object.material as THREE.Material | THREE.Material[];
        for (const item of Array.isArray(material) ? material : [material]) {
          materials.add(item);
          for (const value of Object.values(item)) {
            if (value instanceof THREE.Texture) {
              textures.add(value as THREE.Texture);
            }
          }
        }
      }
    });
    geometries.forEach((item) => item.dispose());
    materials.forEach((item) => item.dispose());
    textures.forEach((item) => item.dispose());
    this.sun.shadow.dispose();
    this.environment.dispose();
    this.renderer.forceContextLoss();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
