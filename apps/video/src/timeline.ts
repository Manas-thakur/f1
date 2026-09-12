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
  beat("decision", 566, 704),
  beat("waitGhost", 702, 716),
  beat("attackChip", 711, 759),
  beat("durable", 821, 870),
  beat("logo", 870, 942),
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
  { frame: 128, word: "Energy" },
  { frame: 141, word: "spent" },
  { frame: 163, word: "overtaking" },
  { frame: 177, word: "is" },
  { frame: 184, word: "energy" },
  { frame: 189, word: "you" },
  { frame: 193, word: "cannot" },
  { frame: 201, word: "spend" },
  { frame: 207, word: "defending." },
  { frame: 225, word: "A" },
  { frame: 233, word: "pass" },
  { frame: 239, word: "is" },
  { frame: 244, word: "not" },
  { frame: 249, word: "free." },
  { frame: 253, word: "So" },
  { frame: 262, word: "AFTERLAP" },
  { frame: 267, word: "reads" },
  { frame: 272, word: "telemetry" },
  { frame: 276, word: "and" },
  { frame: 280, word: "flags" },
  { frame: 286, word: "what" },
  { frame: 292, word: "is" },
  { frame: 298, word: "stale." },
  { frame: 312, word: "Your" },
  { frame: 322, word: "own" },
  { frame: 337, word: "battery" },
  { frame: 343, word: "comes" },
  { frame: 351, word: "from" },
  { frame: 362, word: "measured" },
  { frame: 370, word: "power." },
  { frame: 385, word: "Your" },
  { frame: 391, word: "rival's" },
  { frame: 407, word: "is" },
  { frame: 418, word: "an" },
  { frame: 424, word: "interval," },
  { frame: 436, word: "never" },
  { frame: 445, word: "an" },
  { frame: 456, word: "invented" },
  { frame: 466, word: "number," },
  { frame: 477, word: "and" },
  { frame: 488, word: "every" },
  { frame: 498, word: "option" },
  { frame: 507, word: "is" },
  { frame: 513, word: "checked" },
  { frame: 518, word: "against" },
  { frame: 522, word: "a" },
  { frame: 535, word: "versioned" },
  { frame: 547, word: "rule" },
  { frame: 561, word: "pack." },
  { frame: 574, word: "Attack," },
  { frame: 586, word: "prepare," },
  { frame: 594, word: "defend" },
  { frame: 603, word: "or" },
  { frame: 609, word: "recover," },
  { frame: 614, word: "scored" },
  { frame: 618, word: "across" },
  { frame: 630, word: "the" },
  { frame: 640, word: "battle" },
  { frame: 650, word: "and" },
  { frame: 658, word: "the" },
  { frame: 668, word: "counterattack" },
  { frame: 674, word: "that" },
  { frame: 681, word: "follows." },
  { frame: 688, word: "An" },
  { frame: 694, word: "independent" },
  { frame: 717, word: "checker" },
  { frame: 725, word: "can" },
  { frame: 731, word: "still" },
  { frame: 736, word: "reject" },
  { frame: 748, word: "it." },
  { frame: 759, word: "The" },
  { frame: 766, word: "engineer" },
  { frame: 778, word: "decides," },
  { frame: 787, word: "the" },
  { frame: 799, word: "driver" },
  { frame: 812, word: "executes," },
  { frame: 818, word: "and" },
  { frame: 824, word: "the" },
  { frame: 830, word: "result" },
  { frame: 836, word: "is" },
  { frame: 848, word: "judged" },
  { frame: 854, word: "laps" },
  { frame: 860, word: "later." },
  { frame: 872, word: "AFTERLAP." },
  { frame: 880, word: "Helping" },
  { frame: 894, word: "engineers" },
  { frame: 906, word: "price" },
  { frame: 916, word: "the" },
  { frame: 922, word: "pass." },
];

export const CAPTION_END = 930;
