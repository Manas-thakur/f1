import * as THREE from 'three';

import type { CircuitMap, RaceSettings } from './types';
import { ribbon } from './worldGeometry';

function seededValues(count: number, seed = 9041) {
  const values = new Float32Array(count);
  let state = seed;
  for (let i = 0; i < count; i++) {
    state = (state * 1664525 + 1013904223) >>> 0;
    values[i] = state / 4294967296;
  }
  return values;
}

export class Atmosphere extends THREE.Group {
  private readonly rain: THREE.LineSegments;
  private readonly rainEchoes: THREE.LineSegments[];
  private readonly rainPositions: THREE.BufferAttribute;
  private readonly rainOrigins: Float32Array;
  private readonly clouds: THREE.InstancedMesh;
  private readonly puddles: THREE.Mesh[] = [];
  private readonly cameraPosition = new THREE.Vector3();
  private readonly wetMaterials: THREE.MeshPhysicalMaterial[];
  private wetness = 0;
  private wind = 0;
  private readonly night: boolean;
  private quality: 'ultra' | 'high' | 'performance' = 'ultra';
  private lastRainUpdate = 0;
  private raining = false;
  private interactive = false;

  constructor(map: CircuitMap, center: THREE.Vector3, span: number,
    wetMaterials: THREE.MeshPhysicalMaterial[], night: boolean) {
    super();
    this.night = night;
    this.wetMaterials = wetMaterials;
    const values = seededValues(8400);
    const positions = new Float32Array(2800 * 2 * 3);
    for (let i = 0; i < 2800; i++) {
      const x = (values[i * 3] ?? 0) * 180 - 90;
      const y = (values[i * 3 + 1] ?? 0) * 62;
      const z = (values[i * 3 + 2] ?? 0) * 180 - 90;
      positions.set([x, y, z, x - 0.16, y - 2.8, z + 0.12], i * 6);
    }
    this.rainOrigins = positions.slice();
    const rainGeometry = new THREE.BufferGeometry();
    this.rainPositions = new THREE.BufferAttribute(positions, 3);
    rainGeometry.setAttribute('position', this.rainPositions);
    this.rain = new THREE.LineSegments(rainGeometry, new THREE.LineBasicMaterial({
      color: '#b9e4ff', transparent: true, opacity: 0.42, depthWrite: false,
      blending: THREE.AdditiveBlending,
    }));
    this.rain.frustumCulled = false;
    this.rain.renderOrder = 8;
    this.rainEchoes = [-0.075, 0.075].map((offset) => {
      const echo = new THREE.LineSegments(rainGeometry,
        new THREE.LineBasicMaterial({ color: '#83cfff', transparent: true, opacity: 0.2,
          depthWrite: false, blending: THREE.AdditiveBlending }));
      echo.position.x = offset;
      echo.frustumCulled = false;
      echo.renderOrder = 8;
      return echo;
    });
    this.add(this.rain, ...this.rainEchoes);

    const cloudCanvas = document.createElement('canvas');
    cloudCanvas.width = cloudCanvas.height = 512;
    const cloudContext = cloudCanvas.getContext('2d');
    if (cloudContext) {
      for (let i = 0; i < 22; i++) {
        const x = 70 + (values[i * 3] ?? 0) * 372;
        const y = 110 + (values[i * 3 + 1] ?? 0) * 292;
        const radius = 60 + (values[i * 3 + 2] ?? 0) * 105;
        const puff = cloudContext.createRadialGradient(x, y, 0, x, y, radius);
        puff.addColorStop(0, '#ffffffff');
        puff.addColorStop(0.5, '#ffffffc0');
        puff.addColorStop(1, '#ffffff00');
        cloudContext.fillStyle = puff;
        cloudContext.fillRect(x - radius, y - radius, radius * 2, radius * 2);
      }
    }
    const cloudTexture = new THREE.CanvasTexture(cloudCanvas);
    cloudTexture.colorSpace = THREE.SRGBColorSpace;
    const cloudGeometry = new THREE.PlaneGeometry(1, 1);
    const cloudMaterial = new THREE.MeshBasicMaterial({
      color: night ? '#324050' : '#d5d9d8', map: cloudTexture, transparent: true,
      opacity: night ? 0.22 : 0.14, depthWrite: false, side: THREE.DoubleSide,
    });
    this.clouds = new THREE.InstancedMesh(cloudGeometry, cloudMaterial, 85);
    const dummy = new THREE.Object3D();
    for (let i = 0; i < 85; i++) {
      const angle = (values[i * 5] ?? 0) * Math.PI * 2;
      const radius = span * (0.25 + (values[i * 5 + 1] ?? 0) * 0.75);
      dummy.position.set(center.x + Math.cos(angle) * radius,
        280 + (values[i * 5 + 2] ?? 0) * 160,
        center.z + Math.sin(angle) * radius);
      dummy.scale.set(150 + (values[i * 5 + 3] ?? 0) * 260,
        80 + (values[i * 5 + 4] ?? 0) * 150, 1);
      dummy.rotation.set(-Math.PI / 2, 0, angle);
      dummy.updateMatrix();
      this.clouds.setMatrixAt(i, dummy.matrix);
    }
    this.add(this.clouds);

    const puddleMaterial = new THREE.MeshPhysicalMaterial({
      color: '#18232a', transparent: true, opacity: 0, roughness: 0.08, metalness: 0.2,
      clearcoat: 1, clearcoatRoughness: 0.03, reflectivity: 1, depthWrite: false,
      side: THREE.DoubleSide,
    });
    for (const [inner, outer] of [[-5.55, -5.1], [4.8, 5.35]] as const) {
      const puddle = new THREE.Mesh(ribbon(map, inner, outer, 0.057), puddleMaterial.clone());
      puddle.renderOrder = 2;
      this.puddles.push(puddle);
      this.add(puddle);
    }
  }

  setWeather(settings: Pick<RaceSettings, 'weather' | 'wetness' | 'wind_mps'>) {
    this.wetness = THREE.MathUtils.clamp(settings.wetness, 0, 1);
    const raining = settings.weather === 'rainy';
    const precipitation = raining ? Math.max(this.wetness, 0.55) : 0;
    this.raining = raining;
    this.wind = settings.wind_mps;
    this.configureRainLoad();
    const rainMaterial = this.rain.material as THREE.LineBasicMaterial;
    rainMaterial.opacity = 0.14 + precipitation * 0.48;
    for (const echo of this.rainEchoes) {
      (echo.material as THREE.LineBasicMaterial).opacity = 0.06 + precipitation * 0.24;
    }
    for (const puddle of this.puddles) {
      const material = puddle.material as THREE.MeshPhysicalMaterial;
      material.opacity = Math.max(0, this.wetness - 0.45) * 0.08;
    }
    for (const material of this.wetMaterials) {
      material.roughness = THREE.MathUtils.lerp(0.9, 0.34, this.wetness);
      material.clearcoat = this.wetness * 0.65;
      material.clearcoatRoughness = THREE.MathUtils.lerp(0.5, 0.16, this.wetness);
      material.envMapIntensity = THREE.MathUtils.lerp(0.5, 0.95, this.wetness);
    }
    const cloudMaterial = this.clouds.material as THREE.MeshBasicMaterial;
    cloudMaterial.color.set(raining ? '#53616c' : this.night ? '#324050' : '#bdc9cc');
    cloudMaterial.opacity = (this.night ? 0.18 : 0.1) + precipitation * 0.16;
  }

  setQuality(quality: 'ultra' | 'high' | 'performance') {
    this.quality = quality;
    this.configureRainLoad();
    this.clouds.count = quality === 'performance' ? 14 : quality === 'high' ? 28 : 40;
  }

  setInteractive(interactive: boolean) {
    this.interactive = interactive;
    this.configureRainLoad();
  }

  private configureRainLoad() {
    const qualityDrops = this.quality === 'ultra' ? 1900 : this.quality === 'high' ? 1100 : 400;
    const drops = this.interactive ? Math.min(650, qualityDrops) : qualityDrops;
    this.rain.geometry.setDrawRange(0, drops * 2);
    this.rain.visible = this.raining;
    for (const echo of this.rainEchoes) {
      echo.visible = this.raining && this.quality === 'ultra' && !this.interactive;
    }
  }

  update(time: number, camera: THREE.Vector3) {
    this.cameraPosition.copy(camera);
    const rainInterval = this.interactive ? 1 / 24
      : this.quality === 'ultra' ? 1 / 45 : this.quality === 'high' ? 1 / 30 : 1 / 18;
    if (this.rain.visible && time - this.lastRainUpdate >= rainInterval) {
      this.lastRainUpdate = time;
      const positions = this.rainPositions.array as Float32Array;
      const limit = Math.min(positions.length, this.rain.geometry.drawRange.count * 3);
      const fall = time * (48 + this.wetness * 42);
      const drift = time * this.wind * 0.65;
      for (let i = 0; i < limit; i += 6) {
        const baseX = this.rainOrigins[i] ?? 0;
        const baseY = this.rainOrigins[i + 1] ?? 0;
        const baseZ = this.rainOrigins[i + 2] ?? 0;
        const y = ((baseY - fall) % 62 + 62) % 62;
        const x = baseX + drift % 180 - 90;
        positions[i] = this.cameraPosition.x + x;
        positions[i + 1] = y;
        positions[i + 2] = this.cameraPosition.z + baseZ;
        positions[i + 3] = this.cameraPosition.x + x - this.wind * 0.035;
        positions[i + 4] = y - 2.8;
        positions[i + 5] = this.cameraPosition.z + baseZ + 0.12;
      }
      this.rainPositions.needsUpdate = true;
    }
    this.clouds.position.x = Math.sin(time * 0.006) * this.wind * 8;
    this.clouds.position.z = Math.cos(time * 0.004) * this.wind * 5;
  }

  override dispose() {
    this.rain.geometry.dispose();
    (this.rain.material as THREE.Material).dispose();
    for (const echo of this.rainEchoes) {
      (echo.material as THREE.Material).dispose();
    }
    this.clouds.geometry.dispose();
    (this.clouds.material as THREE.MeshBasicMaterial).map?.dispose();
    (this.clouds.material as THREE.Material).dispose();
    for (const puddle of this.puddles) {
      puddle.geometry.dispose();
      (puddle.material as THREE.Material).dispose();
    }
  }
}
