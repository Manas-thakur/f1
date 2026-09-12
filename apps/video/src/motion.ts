import { interpolate } from "remotion";
import type { Camera } from "./three/camera";
import { VIDEO } from "./theme";

const track = (frame: number, at: readonly number[], to: readonly number[]): number =>
  interpolate(frame, at, to, { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

export const ownX = (frame: number): number => -track(frame, [0, 900], [0, 430]);

export const rivalX = (frame: number): number =>
  ownX(frame) - 16 + track(frame, [620, 800], [0, 34]);

export const ownZ = (frame: number): number => track(frame, [630, 730, 800], [3.6, 1.1, -3.4]);

export const rivalZ = (): number => -3.4;

const CAM_KEYS = [0, 340, 660, 900] as const;
const HEIGHT = [27, 25, 22, 24] as const;
const BACK = [-11, -10, -8.5, -9.5] as const;
const FOV = [0.72, 0.72, 0.76, 0.74] as const;

export const cameraAt = (frame: number): Camera => {
  const focus = (ownX(frame) + rivalX(frame)) / 2 + 2;
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
