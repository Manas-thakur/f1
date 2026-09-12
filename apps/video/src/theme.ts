export const VIDEO = {
  width: 3840,
  height: 2160,
  fps: 30,
  durationInFrames: 900,
} as const;

export const T = {
  sky: "#0d1117",
  deep: "#0b1016",
  asphalt: "#343c45",
  asphaltEdge: "#4a545f",
  kerbA: "#c8ced4",
  kerbB: "#8b3a3f",
  line: "#e8edf1",
  ink: "#f4f6f8",
  muted: "#96a3b0",
  own: "#4f9dea",
  ownDeep: "#1c4e85",
  rival: "#b083d0",
  rivalDeep: "#5d3f75",
  attack: "#ff858a",
  prepare: "#f0c65a",
  defend: "#8dccf2",
  recover: "#8acd9e",
  unknown: "#5d6b78",
} as const;

export const FONT = {
  body: "'Segoe UI', 'Liberation Sans', Arial, sans-serif",
  mono: "Consolas, 'DejaVu Sans Mono', 'Courier New', monospace",
} as const;

export const K = VIDEO.width / 1920;
