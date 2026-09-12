import { interpolate } from "remotion";
import type { Camera } from "./three/camera";
import { VIDEO } from "./theme";

const track = (frame: number, at: readonly number[], to: readonly number[]): number =>
  interpolate(frame, at, to, { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

export const ownX = (frame: number): number => track(frame, [0, 900], [0, 300]);

export const rivalX = (frame: number): number =>
  track(frame, [0, 900], [13, 313]) - track(frame, [630, 810], [0, 30]);

export const ownZ = (frame: number): number => track(frame, [640, 730, 810], [3.4, 1.0, -3.2]);

export const rivalZ = (): number => -3.2;

const CAM_KEYS = [0, 180, 330, 520, 660, 780, 900] as const;
const HEIGHT = [70, 70, 60, 64, 44, 38, 54] as const;
const BACK = [-23, -23, -19, -21, -15, -13, -17] as const;
const FOV = [0.62, 0.62, 0.7, 0.66, 0.82, 0.86, 0.72] as const;
const LEAD = [2, 2, 8, 20, 6, 5, 3] as const;

export const cameraAt = (frame: number): Camera => {
  const focus = (ownX(frame) + rivalX(frame)) / 2 - track(frame, CAM_KEYS, LEAD);
  return {
    eye: [focus, track(frame, CAM_KEYS, HEIGHT), track(frame, CAM_KEYS, BACK)],
    target: [focus, 0, 0],
    up: [0, 0, 1],
    fov: track(frame, CAM_KEYS, FOV),
    width: VIDEO.width,
    height: VIDEO.height,
  };
};

export const fade = (frame: number, a: number, b: number, c: number, d: number): number =>
  track(frame, [a, b, c, d], [0, 1, 1, 0]);
