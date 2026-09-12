export type Beat = {
  readonly id: string;
  readonly n: string;
  readonly title: string;
  readonly note: string;
  readonly from: number;
  readonly to: number;
};

export const BEATS: readonly Beat[] = [
  {
    id: "observe",
    n: "01",
    title: "Observe",
    note: "Telemetry is aligned to one clock and carries its own age.",
    from: 0,
    to: 175,
  },
  {
    id: "believe",
    n: "02",
    title: "Estimate",
    note: "Own battery is measured. The rival's is an interval, never an invented number.",
    from: 175,
    to: 340,
  },
  {
    id: "rules",
    n: "03",
    title: "Check the rule pack",
    note: "Missing information stays unknown. It never becomes a default.",
    from: 340,
    to: 500,
  },
  {
    id: "plan",
    n: "04",
    title: "Score the candidates",
    note: "Each option is scored across the battle and the counterattack that follows.",
    from: 500,
    to: 660,
  },
  {
    id: "decide",
    n: "05",
    title: "Recommend, do not execute",
    note: "The engineer selects. The driver executes. Selection is not execution.",
    from: 660,
    to: 790,
  },
  {
    id: "outcome",
    n: "06",
    title: "Judge at the checkpoint",
    note: "Measured laps later, not at the moment of passing.",
    from: 790,
    to: 900,
  },
];
