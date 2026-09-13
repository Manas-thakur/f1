export const FPS = 30;
export const SECONDS = 12;
export const WIDTH = 1920;
export const HEIGHT = 1080;
export const REVISION = 'dbb00c3';

export const chapters = [
  {
    section: 'THE IDEA', title: 'Every joule\nhas a next use.',
    body: 'A repeatable race simulator.\nA guarded recommendation.\nOne driver decision.',
    caption: 'AFTERLAP connects race physics, delayed telemetry and energy deployment in one inspectable loop.',
    visual: 'hero', labels: ['SIMULATE', 'OBSERVE', 'DECIDE'],
    notes: 'The implementation is a standalone race lab with up to 20 cars and 23 circuit layouts. Python owns the simulated world; Next.js presents it. The energy decision engine recommends a battery profile using a rules baseline or an optional PPO policy. It does not take over the live steering or pedals. This presentation describes the source revision shown in the footer. All 3D sequences are explanatory illustrations, not recorded race measurements.',
    sources: ['README.md', 'BOOST_MODEL_ENGINE.md'],
  },
  {
    section: 'RUNTIME', title: 'One world.\nA shared loop.',
    body: 'RaceSession advances physics.\nSensors delay the observations.\nThe browser presents the result.',
    caption: 'Generation, training and the live server use the same session. Rendering never advances the simulation.',
    visual: 'pipeline', labels: ['PYTHON SESSION', 'OBSERVATIONS', 'NEXT.JS VIEW'],
    notes: 'The physics plant integrates SI quantities. Automatic driver decisions run every 0.1 simulated seconds, with command execution delay. The live Python server publishes observed frames through the Next.js /race/socket proxy. Only the dashboard port needs forwarding. Race checkpoints retain simulation state, random streams, pending commands and observation buffers. Checkpoints live in memory; SQLite separately persists the selected car. The local lab has no remote authentication or operator lease.',
    sources: ['RACE_SIMULATOR.md', 'apps/api/afterlap_api/race_server.py', 'packages/core/afterlap_core/race/session.py'],
  },
  {
    section: 'CIRCUIT', title: 'A recognizable shape.\nExplicit assumptions.',
    body: '23 sourced circuit outlines.\nRescaled, sampled and smoothed.\nCurvature becomes track preview.',
    caption: 'Monza is shown here. The road is flat artwork with an assumed corridor, not a surveyed digital twin.',
    visual: 'circuit', labels: ['SOURCE + HASH', 'METRIC SCALE', 'CURVATURE'],
    notes: 'Crowdflow supplies versioned circuit artwork, originally from Jules Roy under CC BY 4.0. The importer scales each closed outline to its registry length, samples at approximately five metres and applies periodic smoothing. The constant 12 metre corridor, flat elevation, direction and timing origin remain assumptions. Circuit-specific trees, stands, water and landmarks are visual interpretations. Weather sliders and seeded variability alter physical scenarios; a recognizable scene does not establish real-circuit accuracy.',
    sources: ['configs/race-circuits/ATTRIBUTION.md', 'docs/CIRCUIT_SCENERY.md', 'RACE_PARAMETERS.md'],
  },
  {
    section: 'RACECRAFT', title: 'Forces move the car.\nIntent shapes the pass.',
    body: 'Grip, drag, braking and wake.\nA persistent passing state.\nSeeded lines and driver traits.',
    caption: 'The driver commits, runs alongside, returns or aborts. The physical engine still determines longitudinal motion.',
    visual: 'race', labels: ['COMMIT', 'ALONGSIDE', 'RETURN'],
    notes: 'The reduced plant uses float64 midpoint RK2, normally at 0.01 seconds. Wheel force comes from drivetrain power and resistance, bounded by a combined tyre envelope. Racecraft uses delayed rival position and speed to maintain a passing intention. Named random streams keep vehicle setup, driver traits, weather and storylines reproducible. Pit service, tyre wear and dry-compound changes are synthetic but affect the session. Contact can be ignored or terminate an episode; this is not crash dynamics. Lateral line tracking omits full yaw, slip and load-transfer physics. The movement shown here is a scripted explanation, not a benchmark.',
    sources: ['RACE_MODELS.md', 'RACE_SIMULATOR.md', 'packages/core/afterlap_core/race/racecraft.py'],
  },
  {
    section: 'ENERGY', title: 'Deploy with demand.\nRecover under braking.',
    body: 'Useful propulsion sets demand.\nBraking offers recovery.\nOne ledger accounts for both.',
    caption: 'Energy, grip, temperature and power limits constrain delivery. Crossing the timing line never refills the battery.',
    visual: 'battery', labels: ['350 kW BASE CAP', '4 MJ USABLE WINDOW', '8.5 MJ / LAP RECHARGE'],
    notes: 'These are the repository\'s base public-rule limits, not event-specific authorization. Deployment is capped by throttle, selected profile, speed, thermal state, combined shaft power and tyre headroom after combustion. Recovery depends on braking work, rear share, grip, charge acceptance, battery headroom and the lap allowance. Losses and auxiliary load remain in the balance. The session starts at a declared 3.1 MJ operating target. Depletion or thermal shutdown latches a held boost request into Harvest; a non-boost request must rearm it. No stationary free recharge or nitrous effect is represented. The animated charge level is illustrative.',
    sources: ['BATTERY.md', 'docs/FIA_2026_RULE_COVERAGE.md', 'packages/core/afterlap_core/simulation/engine.py'],
  },
  {
    section: 'OBSERVATION', title: 'Missing is different\nfrom zero.',
    body: '38 normalized features.\n38 availability masks.\nOnly delayed observations.',
    caption: 'Own energy, weather, track preview and nearby traffic enter the energy policy. Rival battery truth stays hidden.',
    visual: 'observations', labels: ['OWN CAR', 'TRACK + WEATHER', 'NEARBY TRAFFIC'],
    notes: 'boost-decision-v1 has 76 float32 inputs. Curvature and target racing line are sampled at 0, 50, 100, 200 and 400 metres ahead. The nearest car ahead and behind contribute observed relative motion and lateral position. Missing channels are encoded as zero with a zero mask. Hidden rival energy and future weather do not enter the decision. Operator views may inspect each car\'s own delayed channels; that multi-car payload is not the policy observation. The separate full-controller RaceEnv has 40 values and eight actions, so the two contracts must not be confused.',
    sources: ['BOOST_MODEL_ENGINE.md', 'packages/core/afterlap_core/race/decision.py'],
  },
  {
    section: 'DECISION', title: 'Suggest a profile.\nCheck it independently.',
    body: 'Rules baseline or PPO.\nFive deployment profiles.\nThe same guard checks either.',
    caption: 'Missing telemetry, low energy, temperature, braking and launch conditions can block boost. Event Overtake stays unavailable.',
    visual: 'guard', labels: ['RECOMMEND', 'GUARD', 'APPLY OR REJECT'],
    notes: 'The five actions are harvest, conserve, neutral, push and overtake. BoostDecisionEnv holds each action for 0.5 simulated seconds. The baseline estimates straight quality, closing opportunity, risk and reward from observations. PPO can propose a different action, but cannot remove the guard. Without official event detection and activation inputs, overtake is downgraded to ordinary push when otherwise allowed. Recommendation confidence is an action probability for PPO, not a calibrated real-world safety probability. The server reevaluates the current recommendation when the command arrives.',
    sources: ['docs/MODEL_ENGINE.md', 'BOOST_MODEL_ENGINE.md', 'packages/core/afterlap_core/race/decision.py'],
  },
  {
    section: 'HARDWARE', title: 'Select the car.\nThen press Boost.',
    body: 'Selection persists in SQLite.\nPOST /race/boost carries no car ID.\nThe server resolves the target.',
    caption: 'A successful guarded request transfers the manual energy override. The previous car returns to automatic decisions.',
    visual: 'button', labels: ['SELECT', 'POST', 'GUARDED OVERRIDE'],
    notes: 'The race view and telemetry dropdown update /race/selection/{car_id}. The Raspberry Pi helper uses a pull-up button on BCM GPIO 17 by default and sends one POST on press to a configurable dashboard host. Next.js forwards /race/boost to the runtime, which reads selected_car_id from SQLite. After guard approval, the server clears the prior manual profile and applies the recommendation to the selected car. Accepted means the command reached the session, not that maximum electrical power was delivered. Command delay, pit behavior and physical limits still apply. The older WebSocket CLI remains available; the current button flow is HTTP.',
    sources: ['BOOST_MODEL_ENGINE.md', 'scripts/button_command.py', 'apps/api/afterlap_api/control_state.py'],
  },
  {
    section: 'OPERATOR VIEWS', title: 'One race.\nThree ways to read it.',
    body: 'Watch the 3D race.\nInspect the engineer console.\nFollow one car on telemetry.',
    caption: 'The views share delayed race observations. Unknown channels remain unavailable rather than becoming invented instruments.',
    visual: 'screen', labels: ['/race', '/race/engineer', '/tel/{car_id}'],
    notes: 'The live product capture shows the current race view. The engineer console combines live cameras and telemetry with prediction and execution panels explicitly marked SCENARIO MOCK and MOCK. Those panels are placeholders, not live trained-model outputs. The 800 by 480 telemetry display follows one selected car, and the compact overlay follows the watched car. Speed, energy, power, grip and applied pedals come from delayed sensor channels. Lap times and gaps are browser-side derivations and inherit observation delay and noise. There are no fabricated engine RPM, gearbox or tyre-temperature readouts. Classification, camera selection and manual energy control refer to the same race.',
    sources: ['RACE_SIMULATOR.md', 'apps/web/src/features/engineer/EngineerConsole.tsx', 'apps/web/src/features/telemetry/Screen.tsx'],
  },
  {
    section: 'ANIMATION', title: 'Smooth the view.\nKeep the timing honest.',
    body: 'Buffer received observations.\nShare one playback cursor.\nHold when new samples stop.',
    caption: 'Cars, cameras and the minimap follow presentation time. Render FPS and simulation PACE measure different things.',
    visual: 'motion', labels: ['RECEIVED SAMPLES', 'BUFFERED CURSOR', 'PRESENTED POSE'],
    notes: 'RaceMotion buffers observed poses, uses observed speed to smooth corrections and interpolates between samples. It limits visual overlap separately from the physics state. These display estimates never rewrite classification, exported observations or learning data. Reset and restore clear the old generation. Pause consumes the available buffer and comes to rest; a stalled connection holds the newest known state. Rain, spray, wheels, pit motion and boost indicators use simulation-related timing, with blue trails indicating delivered electrical power. A slower physics pace cannot be repaired by raising rendering FPS. The explainer itself uses frame-indexed animation for reproducible export.',
    sources: ['apps/web/src/features/race/motion.ts', 'docs/CIRCUIT_SCENERY.md', 'BATTERY.md'],
  },
  {
    section: 'LEARNING', title: 'Train. Evaluate.\nThen decide to promote.',
    body: 'CPU PPO collects its own rollouts.\nEach cycle evaluates held-out seeds.\nThe rules baseline stays visible.',
    caption: 'Save policy, manifest and metrics together. Better reward alone is not proof of a useful or reliable strategy.',
    visual: 'training', labels: ['ROLLOUT', 'EVALUATE', 'MANUAL REVIEW'],
    notes: 'The energy reward encourages progress, positions and completed passes while charging for energy use, risk, unsafe requests, failures and action churn. Each cycle evaluates on a held-out seed range, records metrics and saves an improved best checkpoint. Promotion candidate status requires beating the baseline reward and zero evaluation failures, but promotion remains manual. Hold out whole circuits and scenario families, use independent seeds and inspect failures and truncations. Policy manifests validate feature, action and reward compatibility. JSONL generation is for inspection or offline research; PPO does not train by loading those files. The broader RaceEnv controller is an offline experiment, not the live boost policy.',
    sources: ['BOOST_MODEL_ENGINE.md', 'docs/MODEL_ENGINE.md', 'packages/core/afterlap_core/race/training.py'],
  },
  {
    section: 'EVIDENCE + BOUNDARIES', title: 'Repeatable by design.\nMeasured claims only.',
    body: 'Energy closure and replay.\nReal browser and training checks.\nCalibration is still future work.',
    caption: 'A useful platform for controlled experiments: inspect the assumptions, reproduce the run, and evaluate the outcome.',
    visual: 'hero', labels: ['INVARIANTS', 'INTEGRATION', 'LIMITS'],
    notes: 'Tests check energy balance, power and recharge limits, delayed observations, masking, deterministic restore, control routing and real browser behavior. CI also exercises generation and PPO wiring on the source revision under review. Historical validation reports are revision-specific, not fresh performance claims. Circuit shapes, vehicle coefficients, weather fields, pit timings and opportunity labels are synthetic. No measured lap-time advantage, trained superiority, real-car safety, full FIA compliance, or sim-to-real transfer is established. Full crash dynamics, chemistry, event authorization and measured geometry require additional models and data. The strength of this implementation is an inspectable chain from assumptions to observed consequences.',
    sources: ['RACE_VALIDATION.md', 'docs/FIA_2026_RULE_COVERAGE.md', 'tests/race', '.github/workflows/ci.yml'],
  },
] as const;
export type Chapter = (typeof chapters)[number];
