import * as THREE from 'three';

import type { CircuitMap, RaceFrame } from './types';
import { box, trackPose } from './worldGeometry';

interface CrewRig {
  group: THREE.Group;
  mechanics: THREE.Group[];
  wheels: THREE.Mesh[];
}

function laneGeometry(map: CircuitMap) {
  const positions: number[] = [];
  const indices: number[] = [];
  const segments = 120;
  for (let i = 0; i <= segments; i++) {
    const progress = map.length_m - 350 + i / segments * 570;
    for (const lateral of [-8, -18]) {
      const point = trackPose(map, progress, lateral).position;
      positions.push(point.x, 0.035, point.z);
    }
    if (i < segments) {
      const a = i * 2;
      indices.push(a, a + 2, a + 1, a + 1, a + 2, a + 3);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

function mechanic(color: THREE.ColorRepresentation) {
  const group = new THREE.Group();
  const suit = new THREE.MeshStandardMaterial({ color, roughness: 0.7 });
  const visor = new THREE.MeshStandardMaterial({ color: '#19232c', metalness: 0.7, roughness: 0.2 });
  box(group, suit, [0.36, 0.65, 0.28], [0, 0.72, 0]);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.18, 12, 8), suit);
  head.position.y = 1.18;
  group.add(head);
  box(group, visor, [0.28, 0.1, 0.03], [0, 1.2, 0.17]);
  return group;
}

function crew(color: THREE.ColorRepresentation): CrewRig {
  const group = new THREE.Group();
  const mechanics: THREE.Group[] = [];
  const wheels: THREE.Mesh[] = [];
  const rubber = new THREE.MeshStandardMaterial({ color: '#111417', roughness: 0.95 });
  for (const side of [-1, 1]) {
    for (const z of [-1.45, 1.55]) {
      const person = mechanic(color);
      person.position.set(side * 1.55, 0, z);
      person.rotation.y = side > 0 ? -Math.PI / 2 : Math.PI / 2;
      mechanics.push(person);
      group.add(person);
      const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.37, 0.37, 0.3, 20), rubber);
      wheel.rotation.z = Math.PI / 2;
      wheel.position.set(side * 2.25, 0.38, z);
      wheel.castShadow = true;
      wheels.push(wheel);
      group.add(wheel);
    }
  }
  const frontJack = mechanic(color);
  frontJack.position.set(0, 0, 2.9);
  const rearJack = mechanic(color);
  rearJack.position.set(0, 0, -2.9);
  rearJack.rotation.y = Math.PI;
  mechanics.push(frontJack, rearJack);
  group.add(frontJack, rearJack);
  group.visible = false;
  return { group, mechanics, wheels };
}

export class PitLane extends THREE.Group {
  private readonly crews = new Map<string, CrewRig>();

  constructor(map: CircuitMap) {
    super();
    const road = new THREE.Mesh(
      laneGeometry(map),
      new THREE.MeshStandardMaterial({ color: '#262b2f', roughness: 0.96, side: THREE.DoubleSide }),
    );
    road.receiveShadow = true;
    this.add(road);
    const white = new THREE.MeshStandardMaterial({ color: '#f1eee7', roughness: 0.8 });
    const wall = new THREE.MeshStandardMaterial({ color: '#c8c9c2', roughness: 0.7 });
    for (let index = 0; index < 20; index++) {
      const progress = map.length_m - 42 - index * 5.5;
      const pose = trackPose(map, progress, -13);
      const marker = new THREE.Group();
      marker.position.copy(pose.position);
      marker.rotation.y = pose.yaw;
      box(marker, white, [7.5, 0.035, 0.1], [0, 0.06, 0]);
      box(marker, white, [0.1, 0.035, 5], [3.75, 0.06, 0]);
      this.add(marker);
      const rig = crew(['#d9323b', '#18a99a', '#ef8e24', '#337bd6', '#d7d9d4'][index % 5] ?? '#d9323b');
      rig.group.position.copy(pose.position);
      rig.group.rotation.y = pose.yaw;
      this.crews.set(`car-${String(index + 1).padStart(2, '0')}`, rig);
      this.add(rig.group);
    }
    const points = Array.from({ length: 80 }, (_, index) =>
      trackPose(map, map.length_m - 350 + index / 79 * 570, -19).position.clone().setY(0.72));
    this.add(new THREE.Mesh(
      new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points), 160, 0.16, 5),
      wall,
    ));
  }

  update(frame: RaceFrame, time: number) {
    for (const [carId, rig] of this.crews) {
      const car = frame.cars.find((item) => item.id === carId);
      rig.group.visible = car?.tyres.phase === 'service';
      if (!car || !rig.group.visible) {
        continue;
      }
      const duration = Math.max(0.1, car.tyres.service_duration_s);
      const elapsed = duration - car.tyres.service_remaining_s;
      const choreography = Math.sin(Math.min(1, elapsed / duration) * Math.PI);
      for (const [index, person] of rig.mechanics.entries()) {
        person.rotation.z = (index % 2 ? -1 : 1) * choreography * 0.22;
        person.position.y = choreography * 0.08;
      }
      for (const [index, wheel] of rig.wheels.entries()) {
        wheel.rotation.x = time * 8 + index;
        wheel.position.y = 0.38 + choreography * 0.28;
      }
    }
  }
}
