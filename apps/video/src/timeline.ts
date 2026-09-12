export type Scene = {
  readonly id: string;
  readonly from: number;
  readonly durationInFrames: number;
};

const CUTS = [0, 110, 300, 450, 620, 760, 862, 900] as const;
const IDS = ["open", "observe", "rules", "candidates", "recommend", "outcome", "close"] as const;

export const FADE = 9;

export const SCENES: readonly Scene[] = IDS.map((id, i) => ({
  id,
  from: CUTS[i] as number,
  durationInFrames: (CUTS[i + 1] as number) - (CUTS[i] as number),
}));


export type Caption = { readonly frame: number; readonly word: string };

export const CAPTIONS: readonly Caption[] = [];

export const CAPTION_END = 0;
