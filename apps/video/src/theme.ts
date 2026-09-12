export const VIDEO = {
  width: 1920,
  height: 1080,
  fps: 30,
  durationInFrames: 900,
} as const;

export const T = {
  paper: "#eef0f2",
  surface: "#ffffff",
  raised: "#e7ebef",
  rule: "#cbd1d7",
  ink: "#20282f",
  muted: "#56616c",
  accent: "#155dc1",
  aqua: "#8855a6",
  good: "#207247",
  bad: "#b32b32",
  soft: "#e6edf7",
  track: "#b8c1c9",
  well: "#20282f",
} as const;

export const FONT = {
  body: "'Segoe UI', Arial, sans-serif",
  mono: "Consolas, 'Courier New', monospace",
} as const;

export const S = {
  s1: 4,
  s2: 8,
  s3: 12,
  s4: 16,
  s6: 24,
  s8: 32,
  s12: 48,
  s16: 64,
} as const;

export const EASE_OUT = [0.16, 1, 0.3, 1] as const;
export const EASE_IN_OUT = [0.65, 0, 0.35, 1] as const;
