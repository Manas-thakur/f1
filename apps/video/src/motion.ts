import { interpolate } from "remotion";
import type { Camera } from "./three/camera";
import { VIDEO } from "./theme";

export const at = (frame: number, keys: readonly number[], vals: readonly number[]): number =>
  interpolate(frame, keys, vals, { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

export const fade = (frame: number, a: number, b: number, c: number, d: number): number =>
  at(frame, [a, b, c, d], [0, 1, 1, 0]);

export const ownX = (frame: number): number => at(frame, [0, 900], [0, 620]);

export const rivalX = (frame: number): number =>
  ownX(frame) + 9 + at(frame, [640, 790], [0, -17]);

export const ownZ = (frame: number): number =>
  at(frame, [0, 620, 700, 780, 860], [1.55, 1.55, -1.2, -4.6, -4.6]);

export const rivalZ = (frame: number): number => at(frame, [0, 700, 800], [-1.4, -1.4, 0.4]);

const KEYS = [0, 180, 420, 600, 700, 820, 900] as const;
const HEIGHT = [3.1, 2.6, 5.4, 4.2, 2.3, 2.0, 3.4] as const;
const BACK = [-13.5, -12.5, -16, -15, -11, -12, -12.5] as const;
const SIDE = [4.2, 3.8, 2.2, 2.6, 4.0, 5.2, 5.8] as const;
const FOV = [0.62, 0.62, 0.7, 0.66, 0.6, 0.6, 0.64] as const;

export const cameraAt = (frame: number): Camera => {
  const mid = (ownX(frame) + rivalX(frame)) / 2;
  const lead = at(frame, [740, 860], [0, 1]);
  const focus = mid + (ownX(frame) - mid) * lead;
  const side = at(frame, KEYS, SIDE);
  const midZ = (ownZ(frame) + rivalZ(frame)) / 2;
  return {
    eye: [focus + at(frame, KEYS, BACK), at(frame, KEYS, HEIGHT), side],
    target: [focus + 6 - 5 * lead, 0.6, midZ * 0.8],
    up: [0, 1, 0],
    fov: at(frame, KEYS, FOV),
    width: VIDEO.width,
    height: VIDEO.height,
  };
};
