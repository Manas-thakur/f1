# Regulatory coverage matrix

This is an implementation checklist, not a complete executable rule pack. Exact equations and applicability must be transcribed and reviewed from the listed FIA sources before activation.

| Concern | Source family | Implementation | Required evidence |
|---|---|---|---|
| Electrical DC ceiling | C5.2.7 | power bound at ERS-K bus | threshold tests |
| Speed/context curves | C5.2.8 + event pack | piecewise functions and sector lookup | continuity/boundary tests |
| Charge range | C5.2.9 | operating-range constraint, not lap refill | trajectory extrema tests |
| Recharge allowance | C5.2.10 + event pack | correct-bus cumulative ledger | reset/allowance/efficiency tests |
| Power demand transitions | C5.12 + event documents | stateful ramp/reset feasibility | operating-state transitions |
| Overtake permission | B7.2 + event documents | detection/activation state machine | missed crossing and gap boundary |
| Flags and conditions | B7.2 and race-control instructions | invalidation events | stale-plan rejection |
| Driver information path | C8.5.3 / C8.6.1 | simulator-only network driver capability | server rejects live-team command |
| Unknown referenced documents | applicable FIA supporting documents | unresolved applicability state | no silent complete-coverage badge |

Store coverage as `implemented_and_tested`, `review_required`, `not_applicable`, or `unsupported`. Unknown is a first-class result. Each plan lists only the checks actually performed. A synthetic event pack may implement illustrative rules for testing but must have `synthetic=true` and cannot masquerade as a real Grand Prix pack.

The current baseline mentions 350 kW, 4 MJ state-of-charge range and 8.5 MJ recharge with qualifications. These are not interchangeable. The full context includes event and session adjustments; use original documents rather than this summary for machine implementation.
