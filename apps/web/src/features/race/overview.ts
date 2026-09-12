import * as THREE from 'three';

import type { CircuitMap, RaceFrame } from './types';

export function overviewViewport(width: number, height: number, toolbarBottom: number) {
  const left = width > 700 ? 220 : 24;
  const right = 24;
  const top = Math.min(height * 0.45, toolbarBottom + (width > 700 ? 55 : 100));
  const bottom = 65;
  return { left, right, top, bottom };
}

export function overviewLayout(map: CircuitMap, width: number, height: number, toolbarBottom: number) {
  const { left, right, top, bottom } = overviewViewport(width, height, toolbarBottom);
  const availableWidth = Math.max(80, width - left - right);
  const availableHeight = Math.max(80, height - top - bottom);
  const xs = map.points.map(([x]) => x);
  const zs = map.points.map(([, z]) => z);
  const extentX = Math.max(...xs) - Math.min(...xs) + 60;
  const extentZ = Math.max(...zs) - Math.min(...zs) + 60;
  const distance = Math.max(extentX * height / availableWidth, extentZ * height / availableHeight)
    / (2 * Math.tan(THREE.MathUtils.degToRad(58 / 2)));
  return { distance, offsetX: -(left - right) / 2, offsetY: -(top - bottom) / 2 };
}

export function markerPosition(px: number, py: number, occupied: { x: number; y: number }[],
  width: number, height: number, toolbarBottom: number) {
  const bounds = overviewViewport(width, height, toolbarBottom);
  let x = px;
  let y = py;
  for (let attempt = 0; attempt < 300; attempt++) {
    x = THREE.MathUtils.clamp(x, bounds.left + 16, width - bounds.right - 16);
    y = THREE.MathUtils.clamp(y, bounds.top + 16, height - bounds.bottom - 16);
    if (occupied.every((other) => Math.hypot(other.x - x, other.y - y) >= 34)) {
      break;
    }
    const radius = 22 * Math.sqrt(attempt + 1);
    const angle = attempt * 2.4;
    x = px + Math.cos(angle) * radius;
    y = py + Math.sin(angle) * radius;
  }
  return { x, y };
}

export class OverviewMarkers {
  readonly element = document.createElement('div');
  private readonly markers = new Map<string, HTMLButtonElement>();
  private readonly lines = document.createElementNS('http://www.w3.org/2000/svg', 'svg');

  constructor(host: HTMLElement, private readonly select: (id: string) => void) {
    this.element.className = 'race-overview-markers';
    this.element.setAttribute('role', 'group');
    this.element.setAttribute('aria-label', 'Circuit driver markers');
    this.element.hidden = true;
    this.element.appendChild(this.lines);
    host.appendChild(this.element);
  }

  draw(camera: THREE.Camera, cars: Map<string, THREE.Group>, frame: RaceFrame | null,
    selected: string, width: number, height: number, visible: boolean) {
    this.element.hidden = !visible;
    if (!visible || !frame) {
      return;
    }
    const occupied: { x: number; y: number }[] = [];
    const ids = new Set(frame.cars.map((car) => car.id));
    for (const [id, marker] of this.markers) {
      if (!ids.has(id)) {
        marker.remove();
        this.markers.delete(id);
      }
    }
    this.lines.replaceChildren();
    const ordered = [...frame.cars].sort((a, b) => Number(b.id === selected) - Number(a.id === selected));
    for (const car of ordered) {
      let marker = this.markers.get(car.id);
      if (!marker) {
        marker = document.createElement('button');
        marker.type = 'button';
        marker.addEventListener('click', (event) => { event.stopPropagation(); this.select(car.id); });
        marker.addEventListener('pointerdown', (event) => event.stopPropagation());
        marker.addEventListener('dblclick', (event) => event.stopPropagation());
        this.markers.set(car.id, marker);
        this.element.appendChild(marker);
      }
      const model = cars.get(car.id);
      const projected = model?.position.clone().project(camera);
      marker.hidden = !model?.visible || !projected || Math.abs(projected.x) > 1
        || Math.abs(projected.y) > 1 || projected.z > 1;
      if (marker.hidden || !projected) {
        continue;
      }
      const px = (projected.x + 1) / 2 * width;
      const py = (1 - projected.y) / 2 * height;
      const toolbar = Number.parseFloat(getComputedStyle(this.element.parentElement?.parentElement
        ?? this.element).getPropertyValue('--toolbar-bottom')) || 130;
      const { x, y } = markerPosition(px, py, occupied, width, height, toolbar);
      occupied.push({ x, y });
      marker.style.transform = `translate(${x - 15}px, ${y - 15}px)`;
      marker.textContent = String(frame.cars.indexOf(car) + 1);
      marker.title = `P${marker.textContent} · ${car.driver_name}`;
      marker.setAttribute('aria-label', `Watch ${car.driver_name}`);
      marker.setAttribute('aria-pressed', String(car.id === selected));
      marker.dataset['carId'] = car.id;
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      for (const [key, value] of Object.entries({ x1: px, y1: py, x2: x, y2: y })) {
        line.setAttribute(key, String(value));
      }
      this.lines.appendChild(line);
      const point = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      point.setAttribute('cx', String(px));
      point.setAttribute('cy', String(py));
      point.setAttribute('r', '3');
      this.lines.appendChild(point);
    }
  }

  dispose() {
    this.element.remove();
  }
}
