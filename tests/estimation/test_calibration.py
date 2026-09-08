"""Measured calibration on generated data with known ground truth.

Every number produced here is measured, not assumed, and every number is
qualified: the trajectories come from a synthetic generator, so these figures
describe the estimator's internal consistency and say nothing about a real car.
The exact values are reproduced in ``handoffs/A05.md``.
"""

from __future__ import annotations

import pytest

from afterlap_contracts import RivalIntention
from afterlap_core.estimation import (
    AdjacentRowSplitError,
    CalibrationRecord,
    OwnCarConfig,
    RivalConfig,
    create_state,
    evaluate,
    split_by_row,
    split_by_scenario,
    update,
)
from afterlap_core.estimation.calibration import _normal_quantile, scenario_ids

from .conftest import OWN_CAR_ID, SESSION_ID, SyntheticRun, make_context, make_run

CUTOFF_STEP_S = 1.0
WARMUP_S = 2.0


def _collect(
    run: SyntheticRun,
    own_config: OwnCarConfig,
    rival_config: RivalConfig,
    *,
    duration_s: float,
    seed: int,
) -> list[CalibrationRecord]:
    """Roll the estimator forward and pair each posterior with hidden truth.

    The truth is read *after* each estimate is published, never before, and it is
    never handed to the estimator. That is what makes the coverage number a
    measurement rather than a restatement of the model.
    """
    state = create_state(
        session_id=SESSION_ID,
        car_id=OWN_CAR_ID,
        seed=seed,
        own_config=own_config,
        rival_config=rival_config,
    )
    records: list[CalibrationRecord] = []
    previous = -1.0
    cutoff = CUTOFF_STEP_S
    while cutoff <= duration_s + 1e-9:
        batch = tuple(e for e in run.events if previous < e.source_time_s <= cutoff)
        estimate = update(batch, state, make_context(cutoff))
        if cutoff >= WARMUP_S:
            own_truth = run.own_truth_at(cutoff)
            rival_truth = run.rival_truth_at(cutoff)
            belief = estimate.rival_in_slot("ahead_1")
            own = estimate.own_car
            records.append(
                CalibrationRecord(
                    scenario_id=run.scenario_id,
                    session_time_s=cutoff,
                    predicted_speed_mps=own.speed_mps.value,
                    predicted_speed_sigma=own.speed_mps.standard_deviation,
                    truth_speed_mps=own_truth.speed_mps,
                    predicted_progress_m=own.progress_m.value,
                    predicted_progress_sigma=own.progress_m.standard_deviation,
                    truth_progress_m=own_truth.progress_m,
                    predicted_energy_j=own.battery_energy_j.value,
                    predicted_energy_sigma=own.battery_energy_j.standard_deviation,
                    truth_energy_j=own_truth.energy_j,
                    energy_interval_j=(
                        None
                        if belief is None or belief.energy_interval_j is None
                        else (
                            float(belief.energy_interval_j.lower or 0.0),
                            float(belief.energy_interval_j.upper or 0.0),
                        )
                    ),
                    energy_interval_coverage=(
                        None
                        if belief is None or belief.energy_interval_j is None
                        else belief.energy_interval_j.coverage
                    ),
                    intention_weights=(None if belief is None else belief.intentions.as_mapping()),
                    truth_intention=rival_truth.mode,
                )
            )
        previous = cutoff
        cutoff += CUTOFF_STEP_S
    return records


def _rival_records(
    run: SyntheticRun,
    own_config: OwnCarConfig,
    rival_config: RivalConfig,
    *,
    duration_s: float,
    seed: int,
) -> list[CalibrationRecord]:
    """Records whose ``truth_energy_j`` is the *rival's*, for interval coverage."""
    base = _collect(run, own_config, rival_config, duration_s=duration_s, seed=seed)
    rebuilt: list[CalibrationRecord] = []
    for record in base:
        rival_truth = run.rival_truth_at(record.session_time_s)
        rebuilt.append(
            CalibrationRecord(
                scenario_id=record.scenario_id,
                session_time_s=record.session_time_s,
                energy_interval_j=record.energy_interval_j,
                energy_interval_coverage=record.energy_interval_coverage,
                truth_energy_j=rival_truth.energy_j,
                intention_weights=record.intention_weights,
                truth_intention=record.truth_intention,
            )
        )
    return rebuilt


@pytest.fixture(scope="module")
def _scenarios() -> list[tuple[str, int, float, bool]]:
    """(scenario id, seed, throttle gain, matched?) for the calibration corpus."""
    return [(f"matched-{index:02d}", 500 + index, 0.0, True) for index in range(6)] + [
        (f"throttled-{index:02d}", 700 + index, 0.4, False) for index in range(6)
    ]


def test_normal_quantile_is_accurate() -> None:
    """The coverage threshold comes from a checked quantile, not a magic number."""
    assert _normal_quantile(0.95) == pytest.approx(1.6448536269514722, abs=1e-9)
    assert _normal_quantile(0.975) == pytest.approx(1.959963984540054, abs=1e-9)
    assert _normal_quantile(0.5) == pytest.approx(0.0, abs=1e-9)


def test_own_car_interval_coverage_is_measured_and_lands_in_a_stated_band(
    own_config: OwnCarConfig, rival_config: RivalConfig, _scenarios
) -> None:
    """Empirical coverage of the nominal 90 % own-car intervals, as a number.

    The band is 0.75 to 0.99. A filter whose covariance is honest lands near 0.90;
    below 0.75 it is overconfident and every downstream margin is wrong, above
    0.99 it is so wide the interval carries no information. The measured figures
    are printed and reported in the handoff.
    """
    records: list[CalibrationRecord] = []
    for scenario_id, seed, throttle, _matched in _scenarios:
        run = make_run(
            own_config,
            rival_config,
            scenario_id=scenario_id,
            seed=seed,
            duration_s=14.0,
            throttle_gain=throttle,
        )
        records.extend(_collect(run, own_config, rival_config, duration_s=14.0, seed=seed))

    report = evaluate(records, split_name="own-car-calibration", nominal_coverage=0.9)
    print("\n".join(report.as_lines()))

    assert report.record_count >= 100
    assert report.scenario_count == len(_scenarios)

    speed = report.speed_interval_coverage
    assert speed is not None and speed.empirical is not None
    assert speed.total >= 100
    assert 0.75 <= speed.empirical <= 0.99, f"speed coverage {speed.empirical:.4f} on {speed.total} samples"

    progress = report.progress_interval_coverage
    assert progress is not None and progress.empirical is not None
    assert 0.75 <= progress.empirical <= 0.99, (
        f"progress coverage {progress.empirical:.4f} on {progress.total} samples"
    )

    assert report.speed_rmse_mps is not None and report.speed_rmse_mps < 1.0
    assert report.progress_rmse_m is not None and report.progress_rmse_m < 5.0
    assert report.mean_normalised_innovation_squared is not None
    assert 0.1 < report.mean_normalised_innovation_squared < 4.0


def test_rival_energy_interval_coverage_is_measured(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    """Empirical coverage of the nominal 90 % rival-energy quantile interval.

    The band is deliberately wide, 0.55 to 1.0. A rival's battery is not observed
    at all: the interval is a belief propagated through a simplified model from a
    broad prior, so its coverage is a property of that model rather than of a
    measurement, and claiming a tight guarantee here would be dishonest. The
    measured figure is reported in the handoff.
    """
    records: list[CalibrationRecord] = []
    schedules = [
        ((0.0, RivalIntention.NORMAL),),
        ((0.0, RivalIntention.NORMAL), (6.0, RivalIntention.ATTACK)),
        ((0.0, RivalIntention.CONSERVE), (8.0, RivalIntention.NORMAL)),
        ((0.0, RivalIntention.DEFEND),),
    ]
    for index, schedule in enumerate(schedules):
        for repeat in range(3):
            seed = 900 + index * 10 + repeat
            run = make_run(
                own_config,
                rival_config,
                scenario_id=f"rival-{index}-{repeat}",
                seed=seed,
                duration_s=14.0,
                mode_schedule=schedule,
                rival_energy_j=1_600_000.0 + 500_000.0 * index,
                rival_pace_bias_mps=0.1 * (repeat - 1),
            )
            records.extend(_rival_records(run, own_config, rival_config, duration_s=14.0, seed=seed))

    report = evaluate(records, split_name="rival-energy-calibration", nominal_coverage=0.9)
    print("\n".join(report.as_lines()))

    coverage = report.rival_energy_interval_coverage
    assert coverage is not None and coverage.empirical is not None
    assert coverage.total >= 100
    assert 0.55 <= coverage.empirical <= 1.0, (
        f"rival energy coverage {coverage.empirical:.4f} on {coverage.total} samples"
    )
    assert report.behaviour_brier_score is not None
    assert report.behaviour_sample_count == coverage.total
    assert report.behaviour_minimum_true_class_weight is not None
    assert report.behaviour_minimum_true_class_weight >= rival_config.filter.mode_weight_floor.value * 0.99


def test_energy_error_is_only_reported_where_truth_is_legitimate(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    """A withheld label is counted, never quietly dropped from the denominator."""
    records = [
        CalibrationRecord(
            scenario_id="s1",
            session_time_s=1.0,
            predicted_energy_j=2_000_000.0,
            predicted_energy_sigma=20_000.0,
            truth_energy_j=2_010_000.0,
        ),
        CalibrationRecord(
            scenario_id="s1",
            session_time_s=2.0,
            predicted_energy_j=2_000_000.0,
            predicted_energy_sigma=20_000.0,
            truth_energy_j=2_500_000.0,
            energy_truth_is_legitimate=False,
        ),
    ]
    report = evaluate(records, split_name="withheld")
    assert report.energy_sample_count == 1
    assert report.energy_truth_withheld_count == 1
    assert report.energy_rmse_j == pytest.approx(10_000.0)
    assert report.energy_mae_j == pytest.approx(10_000.0)


def test_a_metric_with_no_samples_is_none_not_zero() -> None:
    report = evaluate([CalibrationRecord(scenario_id="empty", session_time_s=0.0)], split_name="empty")
    assert report.speed_rmse_mps is None
    assert report.energy_rmse_j is None
    assert report.behaviour_brier_score is None
    assert report.speed_interval_coverage is not None
    assert report.speed_interval_coverage.empirical is None
    assert report.speed_interval_coverage.total == 0


def test_splitting_by_row_is_refused() -> None:
    """The adjacent-row split must not exist as a usable option."""
    with pytest.raises(AdjacentRowSplitError, match="split by scenario, not by row"):
        split_by_row([], fractions=(0.8, 0.2))


def test_split_by_scenario_keeps_every_scenario_whole() -> None:
    records = [
        CalibrationRecord(scenario_id=f"scenario-{index // 20:03d}", session_time_s=float(index))
        for index in range(400)
    ]
    parts = split_by_scenario(records, seed=7)

    seen: dict[str, str] = {}
    for name, part in parts.items():
        for record in part:
            previous = seen.setdefault(record.scenario_id, name)
            assert previous == name, f"scenario {record.scenario_id} appears in both {previous} and {name}"
    assert sum(len(part) for part in parts.values()) == len(records)
    assert len(seen) == len(scenario_ids(records))
    assert sum(1 for part in parts.values() if part) >= 2, "the split must actually separate scenarios"


def test_split_by_scenario_is_deterministic_for_a_given_seed() -> None:
    records = [
        CalibrationRecord(scenario_id=f"scenario-{index % 17:03d}", session_time_s=float(index))
        for index in range(200)
    ]
    first = split_by_scenario(records, seed=11)
    second = split_by_scenario(records, seed=11)
    other = split_by_scenario(records, seed=12)
    assert {k: [r.scenario_id for r in v] for k, v in first.items()} == {
        k: [r.scenario_id for r in v] for k, v in second.items()
    }
    assert first.keys() == other.keys()


def test_split_fractions_must_be_a_distribution() -> None:
    records = [CalibrationRecord(scenario_id="a", session_time_s=0.0)]
    with pytest.raises(ValueError, match=r"must sum to 1\.0"):
        split_by_scenario(records, fractions=(0.5, 0.2), names=("train", "test"))
    with pytest.raises(ValueError, match="same length"):
        split_by_scenario(records, fractions=(0.5, 0.5), names=("train",))


def test_reliability_bins_cover_the_unit_interval(
    own_config: OwnCarConfig, rival_config: RivalConfig
) -> None:
    run = make_run(own_config, rival_config, scenario_id="reliability", seed=321, duration_s=10.0)
    records = _collect(run, own_config, rival_config, duration_s=10.0, seed=321)
    report = evaluate(records, split_name="reliability", reliability_bins=5)
    assert len(report.behaviour_reliability) == 5
    assert report.behaviour_reliability[0].lower == 0.0
    assert report.behaviour_reliability[-1].upper == 1.0
    populated = [b for b in report.behaviour_reliability if b.count]
    assert populated, "the reliability diagram must have at least one populated bin"
    assert sum(b.count for b in report.behaviour_reliability) == 4 * len(records)
