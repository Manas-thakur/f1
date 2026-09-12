"""Turning a scenario ensemble into published outcome ranges.

``rollout_candidate`` produces one :class:`ScenarioOutcome` per sampled rival
scenario, each with its own per-checkpoint predictions. A published
recommendation that showed only the mean of those would hide the fact an
engineer most needs: whether the scenarios agreed. This module reduces the
ensemble to :class:`OutcomeRange` records that carry the spread.

Three decisions here are deliberate and they all narrow what is claimed.

**The interval is the observed spread, not a quantile.** Every emitted
``IntervalValue`` is ``kind="physical_bounds"``: the minimum and maximum
actually produced by the sampled scenarios. A handful of weighted scenarios
cannot identify a 90th percentile, and labelling their range as one would
overstate the evidence by a wide margin.

**A checkpoint some scenarios did not reach reports how much weight did.**
``weight_covered`` below 1.0 says the range describes only part of the
ensemble. Renormalising silently would make a range computed from one scenario
look like a range computed from five.

**A quantity no scenario produced is absent, never zero.** ``None`` propagates
all the way out; a zero-width interval at zero would read as a confident
prediction of nothing happening.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from afterlap_contracts import IntervalValue, OutcomeRange, Provenance, ScenarioOutcome

__all__ = ["OBSERVED_SPREAD_KIND", "outcome_ranges"]

OBSERVED_SPREAD_KIND: Literal["physical_bounds"] = "physical_bounds"
"""The observed minimum and maximum. Not a fitted quantile, not a CI."""


def _interval(values: list[tuple[float, float]], *, unit: str) -> IntervalValue | None:
    """The observed range of ``(value, weight)`` pairs, or ``None`` if empty.

    No ``coverage`` is set, which the contract requires for ``physical_bounds``:
    the bounds are what the ensemble produced, and attaching a nominal coverage
    to them would turn an observed spread into a statistical claim.
    """
    if not values:
        return None
    numbers = [value for value, _ in values]
    return IntervalValue(
        lower=min(numbers),
        upper=max(numbers),
        unit=unit,
        kind=OBSERVED_SPREAD_KIND,
        provenance=Provenance.SIMULATED,
    )


def outcome_ranges(outcomes: Sequence[ScenarioOutcome]) -> tuple[OutcomeRange, ...]:
    """Reduce a scenario ensemble to one published range per checkpoint.

    Checkpoints are emitted in the order they appear on the ensemble's first
    scenario, so a published payload lists them along the track rather than
    alphabetically. Infeasible scenarios are excluded from the ranges and from
    ``weight_covered``: a scenario the plan could not survive is not a
    prediction of what would happen if it were followed.
    """
    feasible = [outcome for outcome in outcomes if outcome.feasible]
    total_weight = sum(outcome.weight for outcome in outcomes)
    if not feasible or total_weight <= 0.0:
        return ()

    order: list[str] = []
    for outcome in feasible:
        for checkpoint in outcome.checkpoints:
            if checkpoint.checkpoint_id not in order:
                order.append(checkpoint.checkpoint_id)

    ranges: list[OutcomeRange] = []
    for checkpoint_id in order:
        rows = [
            (outcome, checkpoint)
            for outcome in feasible
            for checkpoint in outcome.checkpoints
            if checkpoint.checkpoint_id == checkpoint_id
        ]
        if not rows:  # pragma: no cover - order is built from these rows
            continue
        covered = sum(outcome.weight for outcome, _ in rows)
        ahead_weight = sum(
            outcome.weight for outcome, checkpoint in rows if checkpoint.ahead_of_rival is True
        )
        ahead_known = sum(
            outcome.weight for outcome, checkpoint in rows if checkpoint.ahead_of_rival is not None
        )
        ranges.append(
            OutcomeRange(
                checkpoint_id=checkpoint_id,
                progress_m=float(rows[0][1].progress_m),
                scenario_count=len(rows),
                weight_covered=min(1.0, covered / total_weight),
                elapsed_time_s=_interval(
                    [(float(c.elapsed_time_s), o.weight) for o, c in rows if c.elapsed_time_s is not None],
                    unit="s",
                ),
                gap_to_reference_s=_interval(
                    [
                        (float(c.gap_to_reference_s), o.weight)
                        for o, c in rows
                        if c.gap_to_reference_s is not None
                    ],
                    unit="s",
                ),
                own_energy_j=_interval(
                    [(float(c.own_energy_j), o.weight) for o, c in rows if c.own_energy_j is not None],
                    unit="J",
                ),
                ahead_of_rival_weight=(None if ahead_known <= 0.0 else min(1.0, ahead_weight / ahead_known)),
            )
        )
    return tuple(ranges)
