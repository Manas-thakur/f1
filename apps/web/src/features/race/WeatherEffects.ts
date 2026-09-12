import * as THREE from 'three';

export class WeatherEffects extends THREE.Group {
  private readonly rain: THREE.Points;
  private readonly rainPositions: Float32Array;
  private readonly sun: THREE.Sprite;
  private lastTime = 0;
  private weather: 'sunny' | 'rainy' = 'sunny';

  constructor() {
    super();
    this.rainPositions = new Float32Array(1500 * 3);
    let seed = 9137;
    for (let index = 0; index < this.rainPositions.length; index += 3) {
      seed = (seed * 1664525 + 1013904223) >>> 0;
      this.rainPositions[index] = seed % 180 - 90;
      seed = (seed * 1664525 + 1013904223) >>> 0;
      this.rainPositions[index + 1] = seed % 70;
      seed = (seed * 1664525 + 1013904223) >>> 0;
      this.rainPositions[index + 2] = seed % 180 - 90;
    }
    const rainGeometry = new THREE.BufferGeometry();
    rainGeometry.setAttribute('position', new THREE.BufferAttribute(this.rainPositions, 3));
    this.rain = new THREE.Points(
      rainGeometry,
      new THREE.PointsMaterial({ color: '#b8d7e8', size: 0.18, transparent: true, opacity: 0.68 }),
    );
    this.rain.frustumCulled = false;
    this.add(this.rain);
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 256;
    const context = canvas.getContext('2d');
    if (context) {
      const gradient = context.createRadialGradient(128, 128, 12, 128, 128, 128);
      gradient.addColorStop(0, '#fffbd0');
      gradient.addColorStop(0.18, '#ffd95b');
      gradient.addColorStop(0.42, '#ffb52e99');
      gradient.addColorStop(1, '#ffb52e00');
      context.fillStyle = gradient;
      context.fillRect(0, 0, 256, 256);
    }
    const texture = new THREE.CanvasTexture(canvas);
    this.sun = new THREE.Sprite(new THREE.SpriteMaterial({
      map: texture, transparent: true, depthWrite: false,
    }));
    this.sun.scale.setScalar(180);
    this.add(this.sun);
    this.setWeather('sunny');
  }

  setWeather(weather: 'sunny' | 'rainy') {
    this.weather = weather;
    this.rain.visible = weather === 'rainy';
    this.sun.visible = weather === 'sunny';
  }

  update(time: number, focus: THREE.Vector3) {
    const elapsed = Math.min(0.1, Math.max(0, time - this.lastTime));
    this.lastTime = time;
    if (this.weather === 'rainy') {
      this.rain.position.copy(focus).setY(0);
      for (let index = 1; index < this.rainPositions.length; index += 3) {
        this.rainPositions[index] = (this.rainPositions[index] ?? 0) - elapsed * 58;
        if ((this.rainPositions[index] ?? 0) < 0) {
          this.rainPositions[index] = 70;
        }
      }
      const position = this.rain.geometry.getAttribute('position');
      position.needsUpdate = true;
    }
    this.sun.position.copy(focus).add(new THREE.Vector3(520, 720, -620));
  }
}
