export type Shot = {
  readonly id: string;
  readonly from: number;
  readonly durationInFrames: number;
};

const bounds = [0, 22, 67, 97, 187, 323, 559, 687, 759, 866, 942] as const;

const ids = [
  "openA",
  "openB",
  "beam",
  "debt",
  "mask",
  "corridor",
  "decision",
  "ghost",
  "verdict",
  "logo",
] as const;

export const SHOTS: readonly Shot[] = ids.map((id, index) => ({
  id,
  from: bounds[index] as number,
  durationInFrames: (bounds[index + 1] as number) - (bounds[index] as number),
}));

export const shot = (id: (typeof ids)[number]): Shot => {
  const found = SHOTS.find((s) => s.id === id);
  if (!found) throw new Error(`unknown shot ${id}`);
  return found;
};

export type Beat = {
  readonly id: string;
  readonly from: number;
  readonly durationInFrames: number;
};

const beat = (id: string, from: number, to: number): Beat => ({
  id,
  from,
  durationInFrames: to - from,
});

export const BEATS: readonly Beat[] = [
  beat("title", 0, 97),
  beat("debt", 100, 190),
  beat("mask", 190, 325),
  beat("corridor", 323, 560),
  beat("decision", 566, 708),
  beat("waitGhost", 699, 719),
  beat("attackChip", 711, 759),
  beat("durable", 821, 871),
  beat("logo", 867, 942),
];

export const findBeat = (id: string): Beat => {
  const found = BEATS.find((b) => b.id === id);
  if (!found) throw new Error(`unknown beat ${id}`);
  return found;
};

export type Caption = {
  readonly frame: number;
  readonly word: string;
};

export const CAPTIONS: readonly Caption[] = [
  { frame: 128, word: "In" },
  { frame: 141, word: "2026," },
  { frame: 163, word: "overtaking" },
  { frame: 177, word: "is" },
  { frame: 184, word: "also" },
  { frame: 189, word: "an" },
  { frame: 193, word: "energy" },
  { frame: 201, word: "allocation" },
  { frame: 207, word: "problem." },
  { frame: 225, word: "Using" },
  { frame: 233, word: "boosts" },
  { frame: 239, word: "may" },
  { frame: 244, word: "win" },
  { frame: 249, word: "a" },
  { frame: 253, word: "corner," },
  { frame: 262, word: "but" },
  { frame: 267, word: "leave" },
  { frame: 272, word: "too" },
  { frame: 276, word: "little" },
  { frame: 280, word: "energy" },
  { frame: 286, word: "to" },
  { frame: 292, word: "defend" },
  { frame: 298, word: "later." },
  { frame: 312, word: "Our" },
  { frame: 322, word: "prototype," },
  { frame: 337, word: "Apex" },
  { frame: 343, word: "Ledger," },
  { frame: 351, word: "combines" },
  { frame: 362, word: "live" },
  { frame: 370, word: "telemetry," },
  { frame: 385, word: "current" },
  { frame: 391, word: "FIA," },
  { frame: 407, word: "and" },
  { frame: 418, word: "specific" },
  { frame: 424, word: "rules," },
  { frame: 436, word: "circuit" },
  { frame: 445, word: "positions," },
  { frame: 456, word: "closing" },
  { frame: 466, word: "speed," },
  { frame: 477, word: "and" },
  { frame: 488, word: "estimated" },
  { frame: 498, word: "energy" },
  { frame: 507, word: "range" },
  { frame: 513, word: "to" },
  { frame: 518, word: "price" },
  { frame: 522, word: "attack," },
  { frame: 535, word: "delay," },
  { frame: 547, word: "defend," },
  { frame: 561, word: "recharge." },
  { frame: 574, word: "For" },
  { frame: 586, word: "each" },
  { frame: 594, word: "option" },
  { frame: 603, word: "it" },
  { frame: 609, word: "looks" },
  { frame: 614, word: "three" },
  { frame: 618, word: "laps" },
  { frame: 630, word: "ahead," },
  { frame: 640, word: "estimating" },
  { frame: 650, word: "immediate" },
  { frame: 658, word: "gain," },
  { frame: 668, word: "future" },
  { frame: 674, word: "energy" },
  { frame: 681, word: "debt," },
  { frame: 688, word: "rival" },
  { frame: 694, word: "responses," },
  { frame: 717, word: "re-pass" },
  { frame: 725, word: "risk," },
  { frame: 731, word: "and" },
  { frame: 736, word: "legality." },
  { frame: 748, word: "It" },
  { frame: 759, word: "suggests" },
  { frame: 766, word: "the" },
  { frame: 778, word: "durable" },
  { frame: 787, word: "option," },
  { frame: 799, word: "explains" },
  { frame: 812, word: "why," },
  { frame: 818, word: "or" },
  { frame: 824, word: "abstains" },
  { frame: 830, word: "when" },
  { frame: 836, word: "uncertainty" },
  { frame: 848, word: "is" },
  { frame: 854, word: "too" },
  { frame: 860, word: "high." },
  { frame: 866, word: "Apex" },
  { frame: 880, word: "Ledger." },
  { frame: 894, word: "Helping" },
  { frame: 906, word: "teams" },
  { frame: 916, word: "price" },
  { frame: 922, word: "the" },
];

export const CAPTION_END = 930;
