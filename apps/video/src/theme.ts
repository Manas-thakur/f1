export const VIDEO = {
  width: 1920,
  height: 1080,
  fps: 30,
  durationInFrames: 942,
} as const;

export const PALETTE = {
  ink: "#101418",
  paper: "#f4f6f8",
  attack: "#ff858a",
  attackDeep: "#7d2f33",
  delay: "#f0c65a",
  defend: "#8dccf2",
  defendDeep: "#2a5f7d",
  recharge: "#8acd9e",
  rechargeDeep: "#2c5f3f",
  amber: "#f0c65a",
  green: "#8acd9e",
  greenDeep: "#2c5f3f",
  rail: "#afb9c2",
  mute: "rgba(244,246,248,0.66)",
  panel: "rgba(21,28,34,0.82)",
  panelEdge: "rgba(70,82,93,0.9)",
  chip: "rgba(70,82,93,0.72)",
} as const;

export const SCALE = VIDEO.width / 848;

export const px = (value: number): number => value * SCALE;

export const FONT = {
  display: "'Segoe UI', 'Liberation Sans', Arial, sans-serif",
  caption: "'Segoe UI', 'Liberation Sans', Arial, sans-serif",
  mono: "Consolas, 'DejaVu Sans Mono', 'Courier New', monospace",
} as const;
