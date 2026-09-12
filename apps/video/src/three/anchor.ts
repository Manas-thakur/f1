import { basisOf, ground, project } from "./camera";
import type { Camera } from "./camera";

export type Anchor = { readonly x: number; readonly y: number; readonly visible: boolean };

export const anchor = (camera: Camera, x: number, z: number): Anchor => {
  const p = project(basisOf(camera), ground(x, z));
  return { x: p.x, y: p.y, visible: p.visible };
};
