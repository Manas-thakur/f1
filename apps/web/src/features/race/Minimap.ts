import type { Group } from 'three';

import type { CircuitMap } from './types';
import { LIVERIES, trackPose } from './worldGeometry';

export class Minimap {
  private readonly base = document.createElement('canvas');
  private readonly scale: number;
  private readonly offsetX: number;
  private readonly offsetZ: number;

  constructor(map: CircuitMap) {
    this.base.width = 480;
    this.base.height = 300;
    const xs = map.points.map(([x]) => x);
    const zs = map.points.map(([, z]) => z);
    const width = Math.max(...xs) - Math.min(...xs);
    const height = Math.max(...zs) - Math.min(...zs);
    this.scale = Math.min(420 / Math.max(1, width), 240 / Math.max(1, height));
    this.offsetX = (480 - width * this.scale) / 2 - Math.min(...xs) * this.scale;
    this.offsetZ = (300 - height * this.scale) / 2 - Math.min(...zs) * this.scale;
    const ctx = this.base.getContext('2d');
    if (!ctx) {
      return;
    }
    ctx.beginPath();
    for (let i = 0; i <= map.points.length * 2; i++) {
      const p = trackPose(map, i / (map.points.length * 2) * map.length_m).position;
      const x = p.x * this.scale + this.offsetX;
      const y = p.z * this.scale + this.offsetZ;
      if (i === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.closePath();
    ctx.strokeStyle = '#617482';
    ctx.lineWidth = 13;
    ctx.stroke();
    ctx.strokeStyle = '#c6d0d3';
    ctx.lineWidth = 3;
    ctx.stroke();
    const start = map.points[0];
    if (start) {
      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 18px monospace';
      ctx.fillText('S/F', start[0] * this.scale + this.offsetX + 10, start[1] * this.scale + this.offsetZ - 10);
    }
  }

  draw(canvas: HTMLCanvasElement, cars: Map<string, Group>, selected: string) {
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      return;
    }
    ctx.clearRect(0, 0, 480, 300);
    ctx.drawImage(this.base, 0, 0);
    for (const [id, car] of cars) {
      if (!car.visible || id === selected) {
        continue;
      }
      ctx.fillStyle = LIVERIES[(Number(id.slice(-2)) - 1) % LIVERIES.length] ?? '#fff';
      ctx.beginPath();
      ctx.arc(car.position.x * this.scale + this.offsetX,
        car.position.z * this.scale + this.offsetZ, 4, 0, Math.PI * 2);
      ctx.fill();
    }
    const car = cars.get(selected);
    if (car?.visible) {
      const x = car.position.x * this.scale + this.offsetX;
      const y = car.position.z * this.scale + this.offsetZ;
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(-car.rotation.y);
      ctx.beginPath();
      ctx.moveTo(0, 12);
      ctx.lineTo(-9, -8);
      ctx.lineTo(0, -4);
      ctx.lineTo(9, -8);
      ctx.closePath();
      ctx.strokeStyle = '#0a1119';
      ctx.lineWidth = 4;
      ctx.stroke();
      ctx.fillStyle = '#c8ff78';
      ctx.fill();
      ctx.restore();
      canvas.dataset['selectedCar'] = selected;
      canvas.dataset['selectedPosition'] = `${x.toFixed(2)},${y.toFixed(2)}`;
    } else {
      delete canvas.dataset['selectedPosition'];
    }
  }
}
