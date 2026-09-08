"""Create module briefs and machine-readable seed fixtures inside docs only."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
MODULES = [
 ('contracts','A01','contracts and coordinator','packages/contracts/; root scaffolding and shared integration files','program/EXECUTION_PLAN.md','Wire types, fixture validation, generated Python/TypeScript clients and schema compatibility tests'),
 ('data','A02','data ingestion','packages/core/data/; tests/data/','contracts','Typed adapters, recording/replay, provenance and gap/clock handling'),
 ('simulation','A03','physics simulator','packages/core/simulation/; tests/simulation/','contracts and rules interfaces','Headless dynamics, correct energy ledgers, reactive opponents, observation isolation and full snapshots'),
 ('rules','A04','rules engine','packages/core/rules/; tests/rules/','contracts','Reviewed rule packs, eligibility state machine, independent checker and boundary cases'),
 ('estimation','A05','state estimation','packages/core/estimation/; tests/estimation/','data, simulation observation interface','Own-car estimates, uncertainty, opponent mixtures and no-truth-leak tests'),
 ('planning','A06','predictive planning','packages/core/planning/; tests/planning/','simulation, rules, estimation','Legal baseline and scenario MPC, terminal interface, deadline handling and evidence records'),
 ('learning','A07','reinforcement learning','packages/core/learning/; tests/learning/','simulation, rules, planning, validation','Gym wrapper, SAC training, separate return estimator, frozen bundles and ablation report'),
 ('backend','A08','backend runtime','apps/api/; workers/session_runtime/; tests/backend/','contracts plus runtime module interfaces','Routes, session authority, persistence, lifecycle, streams and recovery'),
 ('engineer-console','A09','engineer console','apps/web/src/features/engineer/; tests/ui/engineer/','contracts, shared shell from A01/A12, backend','Decision workflow, charts, inspector, provenance, stale and lifecycle states'),
 ('simulation-lab','A10','simulation lab','apps/web/src/features/lab/; apps/web/src/features/replay/; tests/ui/lab/','simulation, backend, validation','Scenario creation, run controls, deterministic branch jobs and result inspection'),
 ('driver-display','A11','simulator driver display','apps/web/src/features/driver/; tests/ui/driver/','backend lifecycle and shared design tokens','Minimal display, deliberate simulator execution, expiry watchdog and mode enforcement'),
 ('design','A12','shared design and landing pages','apps/web/src/design-system/; apps/web/src/features/marketing/; tests/ui/design/','contracts; approved screen inventory','Shared tokens/components, two landing routes, accessible states and responsive behaviour'),
 ('validation','A13','independent evaluation','packages/core/evaluation/; tests/acceptance/','module interfaces; coordinator test manifests','Independent gates, paired benchmarks, calibration, ablation and failure reports'),
 ('operations','A14','operations','infra/; workers/batch/; tests/operations/','backend and coordinator dependency contracts','Local packaging, observability, recovery, provenance exports and clean startup'),
 ('demo','A15','presentation','docs/demo/; docs/deck/; no runtime code ownership','validation completed reports','Reproducible demonstration script, truthful claims and failure drill')
]
for folder, aid, title, scope, deps, output in MODULES:
    spec = 'DOMAIN_MODEL.md' if folder=='contracts' else 'DESIGN_SYSTEM.md' if folder=='design' else 'DEMO_RUNBOOK.md' if folder=='demo' else 'TECHNICAL_SPEC.md'
    content=f'''# {aid} — {title}: ready-to-paste agent brief

Implement the {title} module for AFTERLAP using this specification package. This is implementation work, not a request for another plan.

## Mandatory context

Read `docs/AGENTS.md`, `docs/README.md`, `program/ARCHITECTURE.md`, `program/DECISIONS.md`, `program/EXECUTION_PLAN.md`, all `contracts` documents and [{spec}]({spec}). Read other markdowns in this module. References are relative to docs/ unless stated otherwise.

## Write scope

All production paths are at the repository root. Own only: {scope}. Ignore files outside this repository. Do not alter other workers' modules, root dependency files, schemas, database migrations or router registration without coordinator integration. A01 is the coordinator exception for its declared responsibilities. Do not overwrite the documentation mockups with production code.

## Dependencies

{deps}. Use coordinator-provided contract fixtures until dependencies are integrated. Missing dependencies must return explicit unavailable states, not fake successful behaviour. Submit contract changes in `docs/handoffs/{aid}-contract-proposal.md` and continue independent work.

## Deliverables

{output}. Include public interfaces, deterministic fixtures, meaningful tests, diagnostics, failure paths and source/provenance notes. Implement all acceptance cases in the module specification. Validate the shared contract vectors. No real-F1 actuation, hidden simulator-truth access, fabricated measurements or live model exploration.

## Execution sequence

1. Confirm the assigned interface contract and dependency readiness from coordinator status.
2. Implement the smallest deterministic end-to-end path for this module.
3. Add the domain-specific correctness tests before optimisation or visual polish.
4. Implement missing/stale/invalid/timeout behaviours and provenance.
5. Integrate through the agreed interfaces and run module plus contract tests.
6. Measure applicable performance; distinguish measurements from targets.
7. Write `docs/handoffs/{aid}.md` with paths, commands/results, assumptions, unresolved issues and required integration actions.

Do not declare the full product complete. Mark this module review-ready only when its acceptance cases pass. Never edit test expectations merely to conceal a failed invariant.
'''
    (ROOT/folder/'AGENT_BRIEF.md').write_text(content,encoding='utf-8')

schema={
 '$schema':'https://json-schema.org/draft/2020-12/schema',
 'title':'TelemetryEvent','type':'object','additionalProperties':False,
 'required':['schema_version','event_id','session_id','car_id','sequence','source_time_s','received_time_s','channel','value','unit','provenance','quality'],
 'properties':{
 'schema_version':{'const':'1.0'},'event_id':{'type':'string','minLength':1},'session_id':{'type':'string','minLength':1},'car_id':{'type':'string','minLength':1},
 'sequence':{'type':'integer','minimum':0},'source_time_s':{'type':'number','minimum':0},'received_time_s':{'type':'number','minimum':0},
 'channel':{'type':'string','minLength':1},'value':{'type':['number','null']},'unit':{'type':'string'},
 'provenance':{'enum':['measured','estimated','configured','simulated']},'quality':{'enum':['valid','degraded','stale','missing','invalid']}
 }}
sd=ROOT/'contracts'/'schemas';sd.mkdir(parents=True,exist_ok=True)
(sd/'telemetry-event.schema.json').write_text(json.dumps(schema,indent=2)+'\n',encoding='utf-8')
fixture={'schema_version':'1.0','event_id':'fixture-001','session_id':'synthetic-battle-001','car_id':'car-01','sequence':1,'source_time_s':12.0,'received_time_s':12.02,'channel':'battery_energy_j','value':2400000,'unit':'J','provenance':'simulated','quality':'valid'}
(sd/'telemetry-event.example.json').write_text(json.dumps(fixture,indent=2)+'\n',encoding='utf-8')
scenario={'schema_version':'1.0','id':'two-straight-counterattack','synthetic':True,'description':'Illustrative initial condition; not a calibrated real circuit or measured race.','seed':42,'track':{'id':'test-loop','length_m':5200,'geometry_status':'requires implementation','checkpoints':[{'id':'attack-exit','progress_m':2100},{'id':'counterattack-exit','progress_m':3500}]},'initial_state':{'own_speed_mps':75,'own_energy_j':2400000,'gap_ahead_s':0.65,'rival_energy_j':2800000},'observation':{'expose_rival_energy':False,'delay_s':0.15,'energy_provenance':'simulated'},'rule_pack':'synthetic-pack-v1-unreviewed','controller':'mpc-baseline','status':'fixture_only_not_executable_physics'}
(ROOT/'simulation'/'scenario.example.json').write_text(json.dumps(scenario,indent=2)+'\n',encoding='utf-8')
print('Created 15 agent briefs and 3 JSON seed artefacts')
