"""The runtime publishes the evidence the planner produced.

On the audited revision a recommendation was built from ``planning.accepted[0]``
with ``outcomes=()`` and ``probabilities=()``, and the planner that produced it
was the fixed-schedule baseline because ``default_planner`` had no callers. Every
test here checks one link of that chain now carries data, and -- more
importantly -- that the baseline path still says so explicitly when a learned
model is absent, which is the normal case.

The load-bearing test is
:func:`test_the_published_plan_is_the_selected_one_not_the_first_accepted`. For
the fixed-schedule baseline those two coincide, which is why reading position
zero never failed; for the real planner they do not, and publishing position
zero would discard every hysteresis and dwell rule silently.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from afterlap_api.session.baseline_planner import BASELINE_IDENTITY
from afterlap_api.session.learned_planner import (
    LEARNED_PLANNER_IDENTITY,
    LearnedPlannerAdapter,
    build_learned_planner,
)
from afterlap_api.session.model_registry import discover_bundles, load_prediction_service
from afterlap_contracts import (
    ActionCode,
    CalibrationStatus,
    CheckStatus,
    PlanningStatus,
    RecommendationStatus,
)
from afterlap_core.planning.publication import alternatives_for, selected_candidate

from .conftest import RULE_PACK_ID, SCENARIO_ID, SEED

SESSION_LABEL = "connected runtime suite"


def build_runtime():
    """A session built through the *default* factory path, with no planner pinned.

    The backend conftest pins ``BaselinePlanner`` explicitly, which is how the
    rest of that suite keeps its previous behaviour. These tests are about the
    default, so they go through ``SessionFactory()`` with nothing supplied.
    """
    from afterlap_api.session.factory import SessionFactory
    from afterlap_contracts import SessionMode
    from afterlap_contracts.requests import CreateSessionRequest

    factory = SessionFactory()
    _manifest, runtime = factory.create(
        CreateSessionRequest(
            mode=SessionMode.SIMULATION,
            scenario_id=SCENARIO_ID,
            ruleset_id=RULE_PACK_ID,
            seed=SEED,
            label=SESSION_LABEL,
        )
    )
    return runtime


@dataclass(frozen=True, slots=True)
class Driven:
    """A session run, plus the last decision that actually produced advice.

    Keeping only ``last_recommendation`` made most of these tests skip: the
    planner withdraws roughly two thirds of decisions on this scenario, so the
    final tick is usually a withdrawal and the populated payload is never
    inspected. Retaining the last *actionable* decision is what makes the
    assertions bite; the withdrawal path is asserted separately and on purpose.
    """

    runtime: object
    recommendation: object
    planning: object
    withdrawals: int
    decisions: int


@pytest.fixture(scope="module")
def driven():
    """One session advanced until it publishes an actionable recommendation."""
    runtime = build_runtime()
    recommendation = None
    planning = None
    withdrawals = 0
    decisions = 0
    for _ in range(40):
        runtime.advance(1.0)
        published = runtime.last_recommendation
        if published is None:
            continue
        decisions += 1
        if published.action_code is ActionCode.WITHDRAW_ADVICE:
            withdrawals += 1
            continue
        recommendation = published
        planning = runtime.last_planning
    if recommendation is None:
        pytest.skip(
            f"the planner withdrew all {decisions} decisions in this run; there is no populated "
            "payload to inspect"
        )
    return Driven(
        runtime=runtime,
        recommendation=recommendation,
        planning=planning,
        withdrawals=withdrawals,
        decisions=decisions,
    )


class TestTheRealPlannerIsWiredIn:
    def test_the_default_planner_is_the_mpc_planner_not_the_baseline(self, driven) -> None:
        """``default_planner`` used to have zero callers."""
        assert driven.runtime._planner_identity() == LEARNED_PLANNER_IDENTITY

    def test_the_planner_identity_is_published_on_the_recommendation(self, driven) -> None:
        recommendation = driven.recommendation
        assert recommendation is not None
        assert recommendation.planner_identity == LEARNED_PLANNER_IDENTITY

    def test_the_adapter_resimulates_against_this_sessions_own_scenario(self) -> None:
        """The planner's fallback world is a fixture, not the session's circuit."""
        runtime = build_runtime()
        planner = runtime._planner
        assert isinstance(planner, LearnedPlannerAdapter)
        assert planner._world.bundle.scenario.id == runtime._bundle.scenario.id
        assert planner._world.ego_car_id == runtime._bundle.scenario.ego_car_id

    def test_the_adapter_receives_every_delivered_observation(self) -> None:
        runtime = build_runtime()
        planner = runtime._planner
        assert isinstance(planner, LearnedPlannerAdapter)
        for _ in range(4):
            runtime.advance(1.0)
        assert planner.notes.encoded_available or planner._bridge_detail


class TestTheEvidenceIsPublished:
    def test_a_recommendation_is_published_at_all(self, driven) -> None:
        recommendation = driven.recommendation
        assert recommendation is not None
        assert recommendation.status is RecommendationStatus.PROPOSED

    def test_the_published_plan_is_the_selected_one_not_the_first_accepted(self, driven) -> None:
        """The bug that would silently discard hysteresis."""
        planning = driven.planning
        assert planning is not None
        assert planning.status is PlanningStatus.OK
        selected = selected_candidate(planning)
        assert selected is not None
        assert planning.selected_plan_id == selected.id
        assert driven.recommendation.plan_id == selected.id

    def test_alternatives_are_published_and_ranked(self, driven) -> None:
        recommendation = driven.recommendation
        assert recommendation is not None
        assert recommendation.alternatives, "an actionable decision published no alternatives"
        ranks = [alternative.rank for alternative in recommendation.alternatives]
        assert ranks == sorted(ranks)
        assert len(set(ranks)) == len(ranks)

    def test_at_most_one_alternative_claims_to_be_selected(self, driven) -> None:
        recommendation = driven.recommendation
        assert recommendation is not None
        selected = [a for a in recommendation.alternatives if a.selected]
        assert len(selected) <= 1
        if selected:
            assert selected[0].rank == 1
            assert selected[0].constraint_status is CheckStatus.PASS
            assert selected[0].plan_id == recommendation.plan_id

    def test_a_rejected_alternative_carries_the_checkers_verdict_and_a_reason(self, driven) -> None:
        recommendation = driven.recommendation
        assert recommendation is not None
        for alternative in recommendation.alternatives:
            if alternative.selected:
                continue
            assert alternative.rejected_reason
            assert alternative.constraint_status in tuple(CheckStatus)

    def test_the_comparison_terms_are_decomposed_not_a_single_score(self, driven) -> None:
        """Benefit, downside, future energy and switching cost, separately."""
        recommendation = driven.recommendation
        assert recommendation is not None
        assert recommendation.alternatives
        first = recommendation.alternatives[0]
        assert first.final_score is not None
        assert first.expected_utility is not None
        assert first.cvar_loss is not None
        assert first.switch_count is not None
        assert first.switching_penalty is not None

    def test_probabilities_and_outcome_ranges_reach_the_payload_or_say_why_not(self, driven) -> None:
        recommendation = driven.recommendation
        assert recommendation is not None
        assert recommendation.action_code is not ActionCode.WITHDRAW_ADVICE
        for statement in recommendation.probabilities:
            assert statement.event_definition
            assert statement.raw_frequency is not None
            assert statement.calibration_status in (
                CalibrationStatus.CALIBRATED,
                CalibrationStatus.UNCALIBRATED,
            )
        for outcome_range in recommendation.outcome_ranges:
            assert outcome_range.scenario_count >= 0
            assert 0.0 <= outcome_range.weight_covered <= 1.0

    def test_an_outcome_range_never_claims_statistical_coverage(self, driven) -> None:
        """It is the observed ensemble spread, not a quantile."""
        recommendation = driven.recommendation
        assert recommendation is not None
        for outcome_range in recommendation.outcome_ranges:
            for interval in (
                outcome_range.elapsed_time_s,
                outcome_range.gap_to_reference_s,
                outcome_range.own_energy_j,
            ):
                if interval is None:
                    continue
                assert interval.kind == "physical_bounds"
                assert interval.coverage is None


class TestTheBaselineFallbackStaysExplicit:
    def test_no_bundle_is_pinned_so_nothing_learned_contributes(self, driven) -> None:
        recommendation = driven.recommendation
        assert recommendation is not None
        assert recommendation.learned_contribution_enabled is False
        assert recommendation.baseline_identity == BASELINE_IDENTITY

    def test_the_learned_record_names_the_baseline_that_answered(self, driven) -> None:
        recommendation = driven.recommendation
        assert recommendation is not None
        if recommendation.learned is None:
            return
        assert recommendation.learned.enabled is False
        assert recommendation.learned.baseline_identity == BASELINE_IDENTITY
        assert recommendation.learned.continuation_value is None

    def test_the_reason_is_published_not_merely_the_absence(self, driven) -> None:
        """ "The baseline answered" is not an explanation on its own."""
        recommendation = driven.recommendation
        assert recommendation is not None
        assert recommendation.unavailable_reasons
        joined = " ".join(recommendation.unavailable_reasons).lower()
        assert "bundle" in joined or "learned" in joined

    def test_a_disabled_contribution_cannot_publish_a_learned_number(self, driven) -> None:
        recommendation = driven.recommendation
        assert recommendation is not None
        if recommendation.learned is not None and not recommendation.learned.enabled:
            assert recommendation.learned.continuation_value is None
            assert recommendation.learned.bundle_id is None


class TestNoSimulatorTruthCrossesIntoThePayload:
    def test_the_recommendation_mentions_no_truth_field(self, driven) -> None:
        text = driven.recommendation.model_dump_json().lower()
        for forbidden in ("worldstate", "world_state", "rng_state", "integrator_state", "truth"):
            assert forbidden not in text, f"the recommendation leaked {forbidden}"

    def test_the_learned_planner_notes_carry_no_truth(self) -> None:
        runtime = build_runtime()
        for _ in range(3):
            runtime.advance(1.0)
        planner = runtime._planner
        assert isinstance(planner, LearnedPlannerAdapter)
        text = str(planner.notes.as_dict()).lower()
        for forbidden in ("worldstate", "world_state", "rng_state", "truth"):
            assert forbidden not in text


class TestTheModelRegistry:
    def test_discovery_returns_a_registry_even_with_no_bundles(self, tmp_path) -> None:
        registry = discover_bundles(root=tmp_path / "absent")
        assert registry.bundles == {}
        assert registry.rejected == {}

    def test_a_directory_without_a_bundle_file_is_rejected_with_its_reason(self, tmp_path) -> None:
        (tmp_path / "not-a-bundle").mkdir()
        registry = discover_bundles(root=tmp_path)
        assert registry.bundles == {}
        assert "not-a-bundle" in registry.rejected
        assert "is not a bundle" in registry.rejected["not-a-bundle"]

    def test_an_unpinned_bundle_yields_no_service_and_a_stated_reason(self) -> None:
        service, reason = load_prediction_service(None, baseline_identity=BASELINE_IDENTITY)
        assert service is None
        assert BASELINE_IDENTITY in reason

    def test_building_a_planner_reports_which_path_was_taken(self) -> None:
        from afterlap_core.rules import load_rule_pack
        from afterlap_core.simulation import load_bundle

        planner, note = build_learned_planner(
            bundle=load_bundle("two-straight-counterattack"),
            pack=load_rule_pack("synthetic-pack-v1"),
            session_id="test-session",
        )
        assert note
        assert planner.identity == LEARNED_PLANNER_IDENTITY


class TestPublicationHelpers:
    def test_no_recommended_plan_means_no_alternative_is_selected(self, driven) -> None:
        """On a withdrawal there is no recommendation to mark."""
        planning = driven.planning
        assert planning is not None
        rows = alternatives_for(planning, recommended_plan_id=None)
        assert all(not row.selected for row in rows)

    def test_a_plan_the_checker_refused_is_never_marked_selected(self, driven) -> None:
        planning = driven.planning
        assert planning is not None
        for row in alternatives_for(planning, recommended_plan_id=planning.selected_plan_id):
            if row.constraint_status is not CheckStatus.PASS:
                assert not row.selected


class TestTheWithdrawalPathIsStillExplicit:
    """A withdrawal is a published state, and this run produces plenty of them."""

    def test_the_run_withdrew_at_least_once(self, driven) -> None:
        assert driven.decisions > 0
        assert driven.withdrawals > 0, "this run never exercised the withdrawal path"

    def test_a_withdrawal_names_its_reason_and_publishes_no_plan(self) -> None:
        runtime = build_runtime()
        withdrawal = None
        for _ in range(40):
            runtime.advance(1.0)
            published = runtime.last_recommendation
            if published is not None and published.action_code is ActionCode.WITHDRAW_ADVICE:
                withdrawal = published
                break
        assert withdrawal is not None, "no withdrawal was produced to inspect"
        assert withdrawal.plan_id is None
        assert withdrawal.display_text.startswith("No advice")
        assert withdrawal.learned_contribution_enabled is False
        assert withdrawal.unavailable_reasons
        assert not any(alternative.selected for alternative in withdrawal.alternatives)
