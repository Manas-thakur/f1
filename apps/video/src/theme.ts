export const VIDEO = {
  width: 1920,
  height: 1080,
  fps: 30,
  durationInFrames: 942,
} as const;

export const PALETTE = {
  ink: "#05070a",
  paper: "#ffffff",
  attack: "#ff3327",
  attackDeep: "#c2140d",
  delay: "#e6eef1",
  defend: "#42cfdb",
  defendDeep: "#0d7f8e",
  recharge: "#e9a92c",
  rechargeDeep: "#8d5a17",
  amber: "#f0a41e",
  green: "#54df59",
  greenDeep: "#1d7a26",
  rail: "#cfe0dc",
  mute: "rgba(255,255,255,0.62)",
  panel: "rgba(14,17,20,0.74)",
  panelEdge: "rgba(255,255,255,0.18)",
  chip: "rgba(196,205,210,0.34)",
} as const;

export const SCALE = VIDEO.width / 848;

export const px = (value: number): number => value * SCALE;

export const FONT = {
  display: "Oswald",
  caption: "Poppins",
} as const;
