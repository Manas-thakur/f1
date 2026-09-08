# A06 — contract proposal

One item. It is a **documentation / semantics** clash between `handoffs/decisions.md`
D-01 and the merged rules checker, not a request to change a field.

---

## P-01 — `requested_budget_j` is double-converted when `discharge_efficiency < 1`

**Contracts affected:** `afterlap_contracts.planning.ProfileSegment`
(`requested_budget_j` description only) and
`afterlap_core.rules.state.CheckerState.discharge_efficiency` (behaviour only).
No field is added, removed or retyped.

### Observation

D-01 defines `requested_budget_j` as **energy leaving the battery**, symmetric
with `harvest_target_j` being battery energy gain.

`afterlap_core.rules.checker` treats the same number as a **bus-side** quantity
in one place and a battery-side quantity in another:

```python
deploy_scale = segment.requested_budget_j / ceiling_integral      # bus-side
...
energy_j += (mean_harvest - mean_deploy / state.discharge_efficiency) * dt   # /eta again
```

`ceiling_integral` is the time integral of the ERS-K DC bus ceiling, so the first
line fixes `∫P_dep dt = requested_budget_j` **at the bus**. The second then
divides that bus power by `discharge_efficiency` to get battery drain. If
`requested_budget_j` is already battery-side per D-01, the battery ledger is
divided by `eta_discharge` once too often — at a plausible 0.95 that is a 5 %
over-drain, and at 0.9 a 11 % one.

The harvest side has no such clash: `harvest_target_j` is battery gain and the
checker converts it *up* to the CU-K bus exactly once, which is what D-01 asks
for.

### Why it has not bitten anything yet

`CheckerState.discharge_efficiency` defaults to `1.0`, documented by A04 as
"not modelled here". Every shipped test and fixture uses that default, so the
two readings coincide numerically and the defect is latent.

### What A06 does about it in the meantime

`afterlap_core.planning.segments.checker_state_for` sets
`discharge_efficiency=1.0` explicitly and says why in a comment. With that value
the checker's battery ledger is exactly the D-01 quantity, and its power-ceiling
comparison treats battery joules as bus joules — which is **conservative**,
because bus energy never exceeds battery energy, so the checker can reject a
legal plan but can never accept an illegal one. The planner also sets
`charge_bus_efficiency` to the car's real charge efficiency, because that side is
unambiguous.

This is a workaround, not a fix. An integrator who sets a realistic
`discharge_efficiency` today gets a checker that silently over-drains the
modelled battery.

### Proposed resolution (coordinator's call)

Pick one and record it, so that both modules read the same way:

1. **Keep D-01 and change the checker's deployment arithmetic** — set
   `deploy_scale = requested_budget_j * eta_discharge / ceiling_integral` and
   drop the later `/ discharge_efficiency`. The bus ceiling is then compared
   against a genuine bus figure and the battery ledger against a genuine battery
   figure. This is the option A06 recommends: it makes the two ledgers agree
   with `UNITS_TIME.md`, and it is the only one where a car with a real
   `eta_discharge` is checked correctly.
2. **Change D-01** so `requested_budget_j` is bus-side, symmetric with the
   regulated ceiling rather than with `harvest_target_j`. This is cheaper —
   nothing in the checker moves — but it makes the two fields of one
   `ProfileSegment` sit on different buses, which is exactly the confusion
   `UNITS_TIME.md` exists to prevent, and it would require A03's simulator to
   convert in the opposite direction when applying the instruction.

Either way the field description on `ProfileSegment.requested_budget_j` should
name the bus it is measured at as explicitly as `harvest_target_j` already does,
and `CheckerState.discharge_efficiency` should say which side of the conversion
it applies to.

**A06 has not modified `rules/` or the contracts.** The planner is written so
that whichever resolution is chosen, only `checker_state_for` changes.
