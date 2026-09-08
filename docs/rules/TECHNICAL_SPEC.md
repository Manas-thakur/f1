# Rules engine and legal profile interface

## Deliverable

Implement `packages/core/rules/` as deterministic pure functions and an eligibility state machine. API: `resolve_context(manifest, race_events, progress)`, `admissible_profiles(context, state)`, `check_plan(plan, state, context)`. A checker reports pass/fail/unknown plus margins and source references. No LLM is called.

## Rule packs

Three levels compose: season revision -> event/session pack -> timestamped race-control state. Store source URL, published/effective date, article, machine representation, reviewer and test IDs. A pack includes power curves, applicable sectors, recharge allowances, detection/activation crossings, flag restrictions, ramp/reset rules and unsupported referenced conditions. Missing applicable information yields unknown, not an invented default.

Human review converts FIA documents into structured configuration. Do not automatically accept PDF extraction: equations, strike-through amendments and tables can be misread. The simulator, planner and independent checker load the same immutable pack, but the checker uses independently tested calculations rather than accepting planner status.

## Profile feasibility

Intersect absolute power ceiling, speed-dependent curve, event-sector curve, battery physical envelope, temperature/torque limits and stateful power-change rules. Compute accepted power at the correct measurement location. Treat Overtake eligibility as permission to use a profile, not as a source of battery energy. Distinguish an allowance to recover additional energy from actually recovering it.

Track eligibility observations at detection crossings and activation transitions at activation crossings. Invalidate permissions when applicable race-control events demand it. Ruleset hash changes invalidate outstanding plans; the backend must reject a selection using the old hash.

## Checker

Reintegrate accepted power/energy ledger along each proposed segment with boundary subdivision. Check endpoints and interior extrema/events, not only first/last states. Report conservative uncertainty treatment and unresolved constraints. If future opponent state affects a sporting manoeuvre, report feasibility limits without asserting definitive steward judgement. No blanket claim of FIA certification.

## Acceptance

Test exact threshold, epsilon below/above, non-active versus active profile, line crossed between ticks, two lines in one interval, missing detection, safety-state interruption, pack update during selection, lap-counter reset, temperature derate and solver-proposed impossible ramp. Every test carries a reviewed expected result. Coordinator owns event-pack promotion; a worker cannot silently activate an unreviewed pack.

## Sources

Current planning references are FIA Technical Issue 20 and Sporting Issue 08 (August 2026) plus applicable event documents. Revalidate before implementing a particular event. See [rule matrix](RULE_MATRIX.md) and [source register](../sources/SOURCE_REGISTER.md).
