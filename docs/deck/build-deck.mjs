import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "C:/Work/f1/docs/presentation";
const SKILL_DIR = process.env.SKILL_DIR;
const TMP_DIR = process.env.TMP_DIR;
const RUNTIME_PYTHON = process.env.RUNTIME_PYTHON;
if (!SKILL_DIR || !TMP_DIR || !RUNTIME_PYTHON) throw new Error("Required runtime paths are missing");

const { applyPresentationChartFont, finalizePresentation } = await import(
  pathToFileURL(path.join(SKILL_DIR, "container_tools/artifact_tool_utils.mjs")).href,
);

const W = 1280, H = 720;
const C = { paper: "#F3F4F2", white: "#FFFFFF", ink: "#17212B", muted: "#5D6872", rule: "#C9CFD3", blue: "#1768C4", blue2: "#75B7ED", amber: "#E5A637", purple: "#7B5A9A", green: "#2E7C57", red: "#B63B42", dark: "#101820", dark2: "#1A2732" };
const FONT = "Arial";
const presentation = Presentation.create({ slideSize: { width: W, height: H } });

function shape(slide, x, y, w, h, fill = "none", line = "none", radius = false) {
  return slide.shapes.add({
    geometry: radius ? "roundRect" : "rect",
    position: { left: x, top: y, width: w, height: h },
    fill: fill === "none" ? "none" : { type: "solid", color: fill },
    line: line === "none" ? { fill: "none", width: 0 } : { style: "solid", fill: line, width: 1 },
  });
}
function textBox(slide, text, x, y, w, h, size = 22, color = C.ink, bold = false, align = "left") {
  const s = slide.shapes.add({ geometry: "textbox", position: { left: x, top: y, width: w, height: h }, fill: "none", line: { fill: "none", width: 0 } });
  s.text = text;
  s.text.style = { typeface: FONT, fontSize: size, color, bold, alignment: align, verticalAlignment: "middle", autoFit: "shrinkText" };
  return s;
}
function line(slide, x, y, w, color = C.rule, width = 1) {
  return slide.shapes.add({ geometry: "line", position: { left: x, top: y, width: w, height: 0 }, fill: "none", line: { style: "solid", fill: color, width } });
}
function title(slide, n, heading, sub = "") {
  slide.background.fill = C.paper;
  textBox(slide, String(n).padStart(2, "0"), 58, 38, 48, 30, 14, C.blue, true);
  const headingSize = heading.length > 31 ? 34 : 40;
  textBox(slide, heading, 112, 32, 1085, 55, headingSize, C.ink, true);
  if (sub) textBox(slide, sub, 112, 88, 1080, 32, 18, C.muted);
  line(slide, 58, 126, 1164, C.rule, 1);
}
function footer(slide, n, source = "AFTERLAP technical design") {
  line(slide, 58, 680, 1164, C.rule, 1);
  textBox(slide, source, 58, 685, 950, 20, 12, C.muted);
  textBox(slide, String(n), 1170, 685, 52, 20, 12, C.muted, false, "right");
}
function note(slide, talk, sources = []) {
  slide.speakerNotes.textFrame.setText(`${talk}\n\nSources reviewed 8 September 2026:\n${sources.join("\n")}`);
}
function label(slide, text, x, y, w, color = C.blue) {
  textBox(slide, text.toUpperCase(), x, y, w, 24, 13, color, true);
}
function node(slide, txt, x, y, w, h, fill = C.white, stroke = C.rule, size = 18) {
  const r = shape(slide, x, y, w, h, fill, stroke, false);
  textBox(slide, txt, x + 12, y + 8, w - 24, h - 16, size, C.ink, true, "center");
  return r;
}
function connect(slide, a, b, fromSide = "right", toSide = "left", color = C.blue) {
  slide.shapes.connect(a, b, { kind: "elbow", fromSide, toSide, line: { style: "solid", fill: color, width: 2 }, tail: { type: "arrow", width: "sm", length: "sm" } });
}
function statement(slide, lead, body, y, color = C.blue) {
  shape(slide, 74, y + 5, 6, 70, color, "none");
  textBox(slide, lead, 96, y, 350, 34, 22, C.ink, true);
  textBox(slide, body, 96, y + 34, 420, 48, 17, C.muted);
}

// 1 Cover
{
  const s = presentation.slides.add();
  s.background.fill = C.dark;
  const img = await fs.readFile(path.join(workspaceDir, "assets/energy-circuit-cover.png"));
  s.images.add({ blob: new Uint8Array(img), contentType: "image/png", alt: "Abstract generated circuit, energy trace and weather front", fit: "cover", position: { left: 0, top: 0, width: W, height: H } });
  shape(s, 0, 0, 620, H, C.dark, "none");
  textBox(s, "AFTERLAP", 68, 64, 440, 40, 18, "#FFFFFF", true);
  textBox(s, "Energy and overtake intelligence", 68, 220, 520, 120, 58, "#FFFFFF", true);
  textBox(s, "Real circuits, constrained learning and decisions an engineer can inspect", 70, 366, 445, 78, 24, "#D3DAE0");
  textBox(s, "TrackShift 2026 final round", 70, 620, 350, 26, 16, C.amber, true);
  note(s, "Electrical deployment changes the next battle as well as the current pass. AFTERLAP combines real circuit packages, race-condition simulation, constrained learning and a human decision workflow.", ["Cover artwork: generated abstract illustration. It is not a real circuit or event photograph."]);
}

// 2 Engineering question
{
  const s = presentation.slides.add(); title(s, 2, "The engineering question", "A pass has value only if the car can survive what follows");
  textBox(s, "0.65 s", 72, 176, 220, 70, 54, C.blue, true); textBox(s, "gap to the car ahead", 76, 243, 240, 28, 17, C.muted);
  line(s, 350, 174, 0, C.rule);
  const a = node(s, "Approach", 380, 175, 190, 78, C.white, C.rule, 22);
  const b = node(s, "Pass attempt", 650, 175, 190, 78, "#E7EEF7", C.blue, 22);
  const c = node(s, "Retain at T12", 920, 175, 220, 78, C.white, C.rule, 22);
  connect(s, a, b); connect(s, b, c);
  statement(s, "Immediate gain", "Electrical power closes the gap and changes the passing window.", 340, C.blue);
  statement(s, "Delayed cost", "The same energy may be needed to defend on the following straight.", 450, C.amber);
  textBox(s, "Decision horizon", 640, 360, 250, 28, 16, C.muted, true);
  textBox(s, "Current opportunity", 640, 410, 220, 26, 19, C.ink, true);
  shape(s, 640, 448, 230, 12, C.blue, "none");
  textBox(s, "Later response", 910, 410, 220, 26, 19, C.ink, true);
  shape(s, 910, 448, 180, 12, C.amber, "none");
  textBox(s, "The objective records elapsed time and position separately. A utility score never becomes fictional seconds.", 640, 500, 500, 70, 18, C.muted);
  footer(s, 2); note(s, "We evaluate the attack and a later retained-position checkpoint. This prevents a policy from earning repeated rewards for passing and being repassed.", ["Project: planning/OPTIMIZATION.md", "Project: learning/ENVIRONMENT_AND_FEATURES.md"]);
}

// 3 Calendar
{
  const s = presentation.slides.add(); title(s, 3, "2026 circuit scope", "Current Formula 1 schedule snapshot: 23 rounds on 23 physical circuits");
  const cols = [
    ["01 Melbourne", "02 Shanghai", "03 Suzuka", "04 Miami", "05 Montréal", "06 Monaco", "07 Catalunya", "08 Spielberg"],
    ["09 Silverstone", "10 Spa", "11 Hungaroring", "12 Zandvoort", "13 Monza", "14 Madring", "15 Baku", "16 Sepang"],
    ["17 Singapore", "18 Austin", "19 Mexico City", "20 Interlagos", "21 Las Vegas", "22 Lusail", "23 Yas Marina"]
  ];
  cols.forEach((arr, i) => {
    const x = 76 + i * 390;
    textBox(s, arr.join("\n"), x, 174, 320, 350, 23, C.ink, false);
    shape(s, x, 544, 315, 4, i === 1 ? C.amber : C.blue, "none");
  });
  textBox(s, "Calendar event", 76, 590, 170, 28, 18, C.ink, true);
  textBox(s, "Bahrain Grand Prix", 246, 590, 230, 28, 18, C.muted);
  textBox(s, "Physical circuit", 560, 590, 170, 28, 18, C.ink, true);
  textBox(s, "Sepang, Malaysia", 730, 590, 230, 28, 18, C.muted);
  textBox(s, "Separate IDs preserve schedule changes", 968, 590, 245, 48, 16, C.blue, true, "right");
  footer(s, 3, "Official Formula 1 schedule, snapshot 8 September 2026");
  note(s, "The live official page currently lists 23 rounds. Event identity and circuit geometry use separate IDs because the Bahrain Grand Prix is hosted at Sepang in the current schedule. Refresh this snapshot before presenting later.", ["https://www.formula1.com/en/racing/2026", "https://www.formula1.com/en/latest/article/formula-1-and-fia-confirm-malaysia-will-join-2026-calendar-as-host-venue-for-bahrain-grand-prix.6lL7vjFEM2VVynRHvg1TCf.6lL7vjFEM2VVynRHvg1TCf"]);
}

// 4 Circuit comparison
{
  const s = presentation.slides.add(); title(s, 4, "Circuit diversity changes energy value", "Official nominal lengths for six validation circuits");
  const chart = s.charts.add("bar", {
    position: { left: 555, top: 165, width: 650, height: 430 },
    categories: ["Spa", "Monza", "Suzuka", "Singapore", "Mexico City", "Monaco"],
    series: [{ name: "Circuit length", values: [7.004, 5.793, 5.807, 4.927, 4.304, 3.337], fill: C.blue }],
    barOptions: { direction: "bar", grouping: "clustered", gapWidth: 55 },
    hasLegend: false,
    xAxis: { min: 0, max: 8, majorUnit: 1, numberFormatCode: "0.0\" km\"", majorGridlines: { style: "solid", fill: "#DDE1E4", width: 1 }, textStyle: { fill: C.muted, fontSize: 14 } },
    yAxis: { textStyle: { fill: C.ink, fontSize: 16 }, line: { fill: "none", width: 0 } },
    dataLabels: { showValue: true, position: "outEnd", textStyle: { fill: C.ink, fontSize: 15, bold: true } },
    chartFill: { color: C.paper, transparency: 100 }, plotAreaFill: { color: C.paper, transparency: 100 }, chartLine: { fill: "none", width: 0 },
  });
  applyPresentationChartFont(chart, { fontFamily: FONT });
  statement(s, "Monza", "Long full-throttle running followed by heavy braking changes both deployment demand and recovery opportunity.", 175, C.blue);
  statement(s, "Monaco", "A narrow corridor and difficult passing make space and retention central to the decision.", 315, C.amber);
  statement(s, "Spa and Mexico", "Weather, elevation and air density test whether physics transfers beyond one circuit profile.", 455, C.purple);
  footer(s, 4, "Formula1.com circuit pages; lengths in kilometres");
  note(s, "Length is a scale check, not a strategy score. The actual policy receives geometry, conditions and rule context. Monza's official page reports 80 percent full throttle and a 1.1 km main straight. Monaco's page describes narrow streets and difficult overtaking.", ["https://www.formula1.com/en/racing/2026/italy", "https://www.formula1.com/en/racing/2026/monaco", "Project: tracks/season_2026_registry.json"]);
}

// 5 Track package
{
  const s = presentation.slides.add(); title(s, 5, "A simulation-grade track package", "A map image cannot drive the physics model");
  const a = node(s, "Metric centreline\nx, y, z, s", 72, 180, 220, 100, C.white, C.rule, 21);
  const b = node(s, "Derived geometry\ncurvature, grade, heading", 360, 180, 260, 100, C.white, C.rule, 20);
  const c = node(s, "Driveable corridor\nwidth, boundaries, pit exclusion", 690, 180, 280, 100, C.white, C.rule, 20);
  const d = node(s, "Event overlay\nFIA lines, zones and curves", 72, 390, 250, 100, "#E7EEF7", C.blue, 20);
  const e = node(s, "Source record\nURL, revision, licence and hash", 390, 390, 270, 100, C.white, C.rule, 20);
  const f = node(s, "Validation report\nclosure, scale and projection", 730, 390, 260, 100, C.white, C.rule, 20);
  const gate = node(s, "Simulation eligible", 1035, 280, 180, 110, "#E5F0EA", C.green, 22);
  connect(s, a, b); connect(s, b, c); connect(s, d, e); connect(s, e, f); connect(s, c, gate); connect(s, f, gate);
  textBox(s, "1 m canonical resampling", 74, 300, 250, 24, 16, C.muted);
  textBox(s, "Archive track hash and event hash with every run", 72, 566, 880, 40, 24, C.ink, true);
  textBox(s, "Missing boundaries disable precise contact-risk claims", 72, 612, 780, 28, 18, C.red);
  footer(s, 5); note(s, "The compiler creates a periodic metric representation and aligns it with the latest event documents. A validator, not a manually edited status, decides whether the package can run.", ["Project: tracks/TRACK_DATA_PIPELINE.md", "https://www.fia.com/documents/formula-1"]);
}

// 6 Sources
{
  const s = presentation.slides.add(); title(s, 6, "Real observations with clear limits", "Each source has a declared capability and provenance");
  const rows = [
    ["FIA event documents", "Detection and activation lines, straight-mode areas, power-unit parameters", "Human-reviewed event overlay", C.blue],
    ["Licensed survey or CAD", "Metric centreline, elevation, banking, boundaries", "Primary geometry", C.green],
    ["OpenF1 and FastF1", "Position, speed, gaps, stints, race control and weather", "Context and calibration", C.purple],
    ["Authorised team telemetry", "Own-car energy, electrical power and temperatures where permission allows", "Private capability", C.amber]
  ];
  label(s, "Source", 76, 154, 270); label(s, "What it can provide", 362, 154, 520); label(s, "Role", 950, 154, 230);
  rows.forEach((r, i) => {
    const y = 194 + i * 102;
    line(s, 76, y, 1105, C.rule, 1);
    shape(s, 76, y + 23, 7, 52, r[3], "none");
    textBox(s, r[0], 98, y + 14, 250, 66, 20, C.ink, true);
    textBox(s, r[1], 362, y + 10, 520, 72, 17, C.muted);
    textBox(s, r[2], 950, y + 18, 230, 48, 18, C.ink, true);
  });
  textBox(s, "Public telemetry does not contain true rival battery state", 76, 620, 760, 34, 25, C.red, true);
  footer(s, 6, "FIA decision documents, OpenF1 and FastF1 documentation");
  note(s, "OpenF1 exposes useful public race context. We do not relabel it as measured ERS state. Real circuit plus synthetic energy remains a real-circuit synthetic-energy scenario.", ["https://openf1.org/docs/", "https://docs.fastf1.dev/", "https://www.fia.com/documents/formula-1"]);
}

// 7 Factors
{
  const s = presentation.slides.add(); title(s, 7, "Factors that alter the decision", "The simulator preserves causal relationships and correlated conditions");
  const demand = node(s, "Wheel demand\nand braking opportunity", 480, 220, 300, 100, "#E7EEF7", C.blue, 22);
  const energy = node(s, "Battery energy\nand temperature", 480, 410, 300, 100, "#FFF3DC", C.amber, 22);
  const factors = [
    ["Track geometry", 72, 170, C.blue], ["Weather and altitude", 72, 270, C.purple], ["Tyres and grip", 72, 370, C.green], ["Traffic and active aero", 72, 470, C.amber]
  ];
  factors.forEach(([txt, x, y, col]) => { const n = node(s, txt, x, y, 280, 66, C.white, col, 19); connect(s, n, demand, "right", "left", col); });
  const feasible = node(s, "Feasible power\nand recovery", 900, 225, 270, 90, C.white, C.rule, 21);
  const outcome = node(s, "Pass and retained\nposition", 900, 415, 270, 90, "#E5F0EA", C.green, 22);
  connect(s, demand, energy, "bottom", "top", C.blue); connect(s, demand, feasible); connect(s, energy, feasible); connect(s, feasible, outcome, "bottom", "top", C.green);
  textBox(s, "Rules and flags", 910, 150, 200, 26, 18, C.red, true);
  textBox(s, "Rival response and driver delay", 860, 535, 360, 30, 18, C.muted, true, "center");
  textBox(s, "Observed estimates feed the policy. Future weather and hidden rival energy stay unavailable.", 305, 595, 680, 42, 20, C.ink, true, "center");
  footer(s, 7); note(s, "The causal graph guides scenario sampling and leakage tests. Weather, grip and tyre state remain correlated. Wind is projected against local track heading rather than treated as one global sign.", ["Project: tracks/RACE_CONDITION_MODEL.md"]);
}

// 8 Energy physics
{
  const s = presentation.slides.add(); title(s, 8, "Deployment and regeneration physics", "Energy moves through explicit physical and regulatory limits");
  const battery = node(s, "Energy store\nSOC and temperature", 500, 265, 280, 115, "#FFF3DC", C.amber, 23);
  const drive = node(s, "ERS-K drive\nspeed-dependent ceiling", 860, 180, 280, 90, C.white, C.blue, 20);
  const wheel = node(s, "Wheel demand\ndrag, grade and acceleration", 860, 400, 280, 90, C.white, C.rule, 20);
  const brake = node(s, "Braking work\ngrip and stability", 90, 400, 280, 90, C.white, C.green, 20);
  const regen = node(s, "Recharge path\nmotor, battery and lap ledger", 90, 180, 280, 90, C.white, C.green, 20);
  connect(s, battery, drive); connect(s, drive, wheel, "bottom", "top", C.blue);
  connect(s, wheel, brake, "left", "right", C.muted); connect(s, brake, regen, "top", "bottom", C.green); connect(s, regen, battery, "right", "left", C.green);
  textBox(s, "dE/dt = −Pdrive / ηdischarge + ηcharge × Precharge − Paux", 255, 535, 770, 45, 27, C.ink, true, "center");
  textBox(s, "Absolute ERS-K DC power ceiling: 350 kW. Event curves and recharge limits still apply.", 185, 598, 910, 34, 19, C.red, true, "center");
  footer(s, 8, "FIA 2026 Technical Regulations and event Power Unit Information");
  note(s, "The FIA technical regulation sets an absolute 350 kW ERS-K DC power ceiling. Event-specific speed curves and recharge values determine the usable envelope. The simulator applies grip, motor and battery limits before adding recovered energy, and an independent ledger catches double counting.", ["https://www.fia.com/system/files/documents/fia_2026_f1_regulations_-_section_c_technical_-_iss_20_-_2026-08-05.pdf", "https://www.fia.com/system/files/decision-document/2026_miami_grand_prix_-_power_unit_information.pdf"]);
}

// 9 Overtake
{
  const s = presentation.slides.add(); title(s, 9, "Overtake state and partial observation", "A battle progresses through stages and remains uncertain");
  const stages = ["Close", "Overlap", "Complete pass", "Retain at checkpoint"];
  let prev;
  stages.forEach((txt, i) => { const n = node(s, txt, 72 + i * 290, 175, 230, 76, i === 2 ? "#E7EEF7" : C.white, i === 2 ? C.blue : C.rule, 19); if (prev) connect(s, prev, n); prev = n; });
  label(s, "Available to the controller", 76, 330, 420, C.green);
  textBox(s, "Gap and relative speed\nTrack corridor and lookahead\nOwn energy estimate and execution state\nCurrent eligibility, flags and observation age", 76, 365, 490, 190, 20, C.ink);
  label(s, "Hidden or uncertain", 690, 330, 360, C.red);
  textBox(s, "Rival battery and future action\nFuture weather and race-control events\nUnmeasured lateral position\nTyre temperature and vehicle differences", 690, 365, 490, 190, 20, C.ink);
  shape(s, 625, 322, 2, 260, C.rule, "none");
  textBox(s, "The policy acts on beliefs. Evaluation may inspect simulator truth after the run.", 220, 600, 840, 34, 21, C.blue, true, "center");
  footer(s, 9); note(s, "A completed pass and a retained pass are separate outcomes. Counterfactual opponents react to the changed branch. The policy cannot read simulator labels or future data.", ["Project: estimation/TECHNICAL_SPEC.md", "Project: tracks/RACE_CONDITION_MODEL.md"]);
}

// 10 RL loop
{
  const s = presentation.slides.add(); title(s, 10, "The reinforcement-learning interaction", "SAC proposes strategy at one-second intervals");
  const obs = node(s, "192-value masked\nstate estimate", 80, 220, 230, 95, C.white, C.rule, 21);
  const actor = node(s, "SAC actor\n2 continuous outputs", 390, 220, 230, 95, "#E7EEF7", C.blue, 21);
  const plan = node(s, "Constrained planner\nfeasible trajectory", 700, 220, 230, 95, C.white, C.rule, 21);
  const env = node(s, "Simulator\nnext observed state", 1010, 220, 200, 95, "#E5F0EA", C.green, 21);
  connect(s, obs, actor); connect(s, actor, plan); connect(s, plan, env);
  s.shapes.connect(env, obs, { kind: "elbow", fromSide: "bottom", toSide: "bottom", line: { style: "solid", fill: C.green, width: 2 }, head: { type: "arrow", width: "sm", length: "sm" } });
  textBox(s, "Action 1", 394, 375, 160, 24, 16, C.blue, true);
  textBox(s, "Energy budget for the next 10 seconds", 394, 404, 300, 48, 19, C.ink);
  textBox(s, "Action 2", 745, 375, 160, 24, 16, C.blue, true);
  textBox(s, "Energy target at the next checkpoint", 745, 404, 300, 48, 19, C.ink);
  textBox(s, "Reward", 82, 486, 150, 24, 16, C.amber, true);
  textBox(s, "Elapsed time, finishing position and instruction changes under objective-v1", 82, 516, 570, 64, 19, C.ink);
  textBox(s, "Rules remain hard constraints", 760, 515, 410, 34, 23, C.red, true, "right");
  textBox(s, "No steering, torque command or online exploration", 680, 558, 490, 32, 18, C.muted, false, "right");
  footer(s, 10); note(s, "The actor proposes a ten-second budget and a checkpoint reserve. The planner decodes and checks these preferences. Training and serving use the same action path. Operational inference uses the deterministic policy and frozen weights.", ["https://stable-baselines3.readthedocs.io/en/master/modules/sac.html", "Project: learning/ENVIRONMENT_AND_FEATURES.md"]);
}

// 11 Weights
{
  const s = presentation.slides.add(); title(s, 11, "Three different meanings of weight", "Conflating them produces unsafe explanations");
  const data = [
    ["Physics parameters", "Units and causal state transitions", "Calibrate drag, grip and efficiency", C.blue],
    ["Reward coefficients", "Human priorities in objective-v1", "Freeze before final evaluation", C.amber],
    ["Policy influence", "Nonlinear dependence on state", "Measure with interventions and ablations", C.purple]
  ];
  data.forEach((r, i) => {
    const y = 175 + i * 125;
    textBox(s, r[0], 76, y, 280, 40, 25, r[3], true);
    textBox(s, r[1], 385, y, 390, 54, 20, C.ink);
    textBox(s, r[2], 825, y, 365, 54, 20, C.muted);
    line(s, 76, y + 84, 1114, C.rule, 1);
  });
  textBox(s, "Explain one decision by replaying the same snapshot with a controlled change", 76, 570, 860, 40, 25, C.ink, true);
  textBox(s, "Track, state, action and baseline stay attached to every explanation", 76, 616, 880, 30, 18, C.blue);
  footer(s, 11); note(s, "A neural network has no one stable physical importance weight per feature. We use paired interventions, group ablations, Sobol or Morris sensitivity and local actor diagnostics. Each result names the experiment and limits.", ["Project: tracks/FACTOR_AND_INFLUENCE.md"]);
}

// 12 Curriculum
{
  const s = presentation.slides.add(); title(s, 12, "Training across real circuits", "The policy sees geometry and conditions, not a track-name shortcut");
  const phases = [
    ["1", "Energy primitives", "Conservation and reward checks"],
    ["2", "Complete circuit", "Single-car pace and recovery"],
    ["3", "Battle zones", "Reactive rival and driver delay"],
    ["4", "Race segments", "Weather, tyres, traffic and flags"]
  ];
  let prev;
  phases.forEach((p, i) => {
    const x = 70 + i * 285;
    const n = shape(s, x, 185, 235, 145, C.white, i === 3 ? C.blue : C.rule);
    textBox(s, p[0], x + 16, 200, 44, 38, 28, i === 3 ? C.blue : C.muted, true);
    textBox(s, p[1], x + 16, 244, 200, 30, 20, C.ink, true);
    textBox(s, p[2], x + 16, 278, 200, 42, 16, C.muted);
    if (prev) connect(s, prev, n); prev = n;
  });
  shape(s, 70, 395, 1110, 150, "#17212B", "none");
  label(s, "Final test remains sealed", 96, 416, 390, C.blue2);
  textBox(s, "Withhold complete circuits", 96, 455, 310, 28, 22, "#FFFFFF", true);
  textBox(s, "Hold out one high-speed, one street and one elevation/weather circuit.", 96, 490, 330, 42, 17, "#CBD5DC");
  textBox(s, "Withhold combined conditions", 510, 455, 330, 28, 22, "#FFFFFF", true);
  textBox(s, "Wet plus traffic plus low initial energy exposes interaction failures.", 510, 490, 330, 42, 17, "#CBD5DC");
  textBox(s, "Evaluate by subgroup", 915, 455, 230, 28, 22, "#FFFFFF", true);
  textBox(s, "Average gains cannot hide a failing street-circuit regime.", 915, 490, 230, 42, 17, "#CBD5DC");
  textBox(s, "Real historical context + synthetic or authorised energy, with provenance", 170, 595, 940, 34, 22, C.blue, true, "center");
  footer(s, 12); note(s, "The curriculum advances only after correctness and baseline gates. Evaluation balances decision opportunities rather than raw lap counts. Natural-frequency weights return for the final report.", ["Project: tracks/RL_TRACK_GENERALISATION.md"]);
}

// 13 Architecture
{
  const s = presentation.slides.add(); title(s, 13, "Hybrid decision architecture", "Learning contributes strategy while physics and rules retain authority");
  const ingest = node(s, "Track, telemetry\nand event packages", 55, 220, 205, 90, C.white, C.rule, 18);
  const est = node(s, "State and\nrival belief", 315, 220, 190, 90, C.white, C.rule, 19);
  const mpc = node(s, "Scenario MPC\nand candidate set", 570, 220, 210, 90, "#E7EEF7", C.blue, 19);
  const check = node(s, "Independent\nrules checker", 845, 220, 185, 90, "#FBE8E9", C.red, 19);
  const engineer = node(s, "Engineer\nselection", 1080, 220, 150, 90, "#E5F0EA", C.green, 19);
  connect(s, ingest, est); connect(s, est, mpc); connect(s, mpc, check); connect(s, check, engineer);
  const actor = node(s, "SAC actor\nbudget + reserve", 575, 410, 190, 78, "#EFE8F4", C.purple, 18);
  const value = node(s, "Return ensemble\nfinalist scoring", 790, 410, 190, 78, C.white, C.purple, 18);
  connect(s, actor, mpc, "top", "bottom", C.purple); connect(s, value, check, "top", "bottom", C.purple);
  const driver = node(s, "Simulator driver\nexecution event", 1030, 435, 200, 78, C.white, C.rule, 18);
  connect(s, engineer, driver, "bottom", "top", C.green);
  s.shapes.add({ geometry: "line", position: { left: 1130, top: 513, width: 0, height: 24 }, fill: "none", line: { style: "solid", fill: C.green, width: 2 } });
  s.shapes.add({ geometry: "line", position: { left: 158, top: 537, width: 972, height: 0 }, fill: "none", line: { style: "solid", fill: C.green, width: 2 } });
  s.shapes.add({ geometry: "line", position: { left: 158, top: 310, width: 0, height: 227 }, fill: "none", line: { style: "solid", fill: C.green, width: 2 } });
  textBox(s, "execution feedback", 175, 542, 180, 22, 12, C.green, true);
  textBox(s, "Late results, stale observations and unsupported models cannot restore invalidated advice", 165, 590, 950, 34, 21, C.red, true, "center");
  footer(s, 13); note(s, "The ordinary-return network reranks feasible finalists outside acados, avoiding a false differentiability assumption. Baseline candidates remain available. The checker can reject learned preferences.", ["Project: program/ARCHITECTURE.md", "Project: learning/VALUE_AND_CALIBRATION.md", "Project: planning/OPTIMIZATION.md"]);
}

// 14 Evidence
{
  const s = presentation.slides.add(); title(s, 14, "Evidence before model promotion", "Every controller receives the same observations and paired starting conditions");
  const methods = ["Legal fixed", "Greedy attack", "MPC only", "MPC + actor", "MPC + value", "Full system"];
  methods.forEach((m, i) => {
    const y = 164 + i * 60;
    textBox(s, m, 76, y, 230, 34, 19, C.ink, i >= 2);
    shape(s, 320, y + 7, 430, 14, i < 2 ? C.rule : i === 2 ? C.blue : C.purple, "none");
    textBox(s, i < 2 ? "reference" : i === 2 ? "baseline" : "ablation", 770, y, 110, 30, 15, C.muted);
  });
  shape(s, 915, 155, 280, 380, "#17212B", "none");
  textBox(s, "Promotion gates", 942, 178, 225, 36, 25, "#FFFFFF", true);
  const gates = ["Predeclared benefit margin", "Downside by circuit subgroup", "Modeled constraint results", "Probability calibration", "p95 decision latency"];
  gates.forEach((g, i) => { shape(s, 942, 243 + i * 54, 6, 30, i === 2 ? C.red : C.blue2, "none"); textBox(s, g, 964, 236 + i * 54, 205, 42, 17, "#E6EBEF"); });
  textBox(s, "No benchmark result exists yet", 76, 568, 540, 38, 26, C.red, true);
  textBox(s, "A rejected learned model leaves MPC-only active and its report inspectable.", 76, 612, 730, 28, 18, C.muted);
  footer(s, 14); note(s, "The final report uses hierarchical paired intervals over scenarios and training seeds. Failed and withdrawn decisions stay in the denominator. Promotion thresholds are frozen before opening the final test set.", ["Project: learning/SERVING_AND_EVALUATION.md", "Project: validation/TECHNICAL_SPEC.md"]);
}

// 15 Product and USP
{
  const s = presentation.slides.add(); title(s, 15, "Product workflow and defensible USP", "One decision record connects simulation, engineer action and observed execution");
  const lab = node(s, "Simulation lab", 80, 175, 300, 84, C.white, C.rule, 25);
  const eng = node(s, "Race engineer", 490, 175, 300, 84, "#E7EEF7", C.blue, 25);
  const drv = node(s, "Simulator driver", 900, 175, 300, 84, C.white, C.rule, 25);
  connect(s, lab, eng); connect(s, eng, drv);
  textBox(s, "Define a real-circuit snapshot\nand branch actual controls", 80, 280, 300, 62, 19, C.muted, false, "center");
  textBox(s, "Inspect reserve, alternatives,\nrules and uncertainty", 490, 280, 300, 62, 19, C.muted, false, "center");
  textBox(s, "Show one instruction, end\ncondition and expiry", 900, 280, 300, 62, 19, C.muted, false, "center");
  line(s, 80, 380, 1120, C.rule, 1);
  label(s, "Why it stands apart", 80, 410, 320, C.blue);
  textBox(s, "Real event packages", 80, 455, 255, 32, 22, C.ink, true);
  textBox(s, "FIA lines and circuit geometry are versioned inputs.", 80, 490, 280, 48, 17, C.muted);
  textBox(s, "Reactive futures", 410, 455, 230, 32, 22, C.ink, true);
  textBox(s, "The rival responds differently after each intervention.", 410, 490, 280, 48, 17, C.muted);
  textBox(s, "Constrained learning", 745, 455, 250, 32, 22, C.ink, true);
  textBox(s, "RL proposes. Physics and rules decide feasibility.", 745, 490, 260, 48, 17, C.muted);
  textBox(s, "Auditable operation", 1040, 455, 190, 32, 22, C.ink, true);
  textBox(s, "Selection and execution remain separate evidence.", 1040, 490, 190, 56, 17, C.muted);
  textBox(s, "Demo proof: one snapshot, two strategies, two physically different futures", 120, 590, 1040, 42, 27, C.blue, true, "center");
  footer(s, 15); note(s, "The USP is the auditable chain from real event context to a constrained recommendation and observed execution. The final demonstration must run two actual branches rather than playing authored chart data.", ["Project: design/DESIGN_REVISION_02.md", "Project: demo/DEMO_RUNBOOK.md", "Project: tracks/README.md"]);
}

await fs.mkdir(TMP_DIR, { recursive: true });
const candidatePath = path.join(TMP_DIR, "AFTERLAP-candidate.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const previewDir = path.join(TMP_DIR, "previews");
await fs.mkdir(previewDir, { recursive: true });
for (let i = 0; i < presentation.slides.items.length; i++) {
  const slide = presentation.slides.items[i];
  const png = await presentation.export({ slide, format: "png", scale: 1 });
  await fs.writeFile(path.join(previewDir, `slide-${String(i + 1).padStart(2, "0")}.png`), new Uint8Array(await png.arrayBuffer()));
  const layout = await slide.export({ format: "layout" });
  await fs.writeFile(path.join(previewDir, `slide-${String(i + 1).padStart(2, "0")}.layout.json`), await layout.text());
}

const FINAL_PPTX = path.join(workspaceDir, "output/AFTERLAP-final-round-v4.pptx");
const requirements = {
  explicitTotalSlideCount: 15,
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [4],
  materializeLiteralChartWorkbooks: true,
  nativeChartTargetApplication: "powerpoint",
};
const stagingDir = path.join(TMP_DIR, "finalizer");
await fs.mkdir(stagingDir, { recursive: true });
await fs.mkdir(path.dirname(FINAL_PPTX), { recursive: true });
const result = await finalizePresentation({
  ...requirements,
  workspaceDir,
  candidatePath,
  finalPath: FINAL_PPTX,
  pythonExecutable: RUNTIME_PYTHON,
  integrityValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: ["--expected-slide-size-emu", "12192000,6858000", "--validate-heading-fit"],
  fontPolicy: { basis: "design", families: [FONT] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "AFTERLAP-final-round-v4.validation.json"),
});
console.log(JSON.stringify({ candidatePath, finalPath: FINAL_PPTX, previewDir, result }, null, 2));
