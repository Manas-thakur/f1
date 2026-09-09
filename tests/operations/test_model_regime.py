"""A learned bundle only contributes inside the regime it was evaluated in.

`AGENTS.md`: *"No live RL exploration, silent model replacement or automatic
promotion."* Approval and the feature-manifest hash were already gates. These
drills add the three the 23-circuit catalogue makes reachable, and every one of
them fails closed:

* **the ruleset's contents**, not only its id. A pack whose energy window moved
  keeps its `ruleset_id` and is a different environment.
* **the circuit split and the compiled package hash.** The same circuit id
  recompiled from different telemetry is different geometry. A bundle that
  names no circuit at all is refused on a compiled circuit: "we did not record
  which circuits this trained on" is not evidence that it trained on this one.
* **the conditions regime.** A session running under a weather tape is outside
  the regime of a bundle that was never evaluated under one.

Every refusal leaves the validated baseline in force and names it, which is the
half that matters operationally: the session keeps advising, from the path that
was checked.

No torch here on purpose. `test_model_hash.py` covers the bundle *format* and
needs the real weights; what is under test here is the compatibility decision,
which reads a manifest.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from afterlap_api.session.baseline_planner import BASELINE_IDENTITY
from afterlap_api.session.degradation import DegradationRow, check_model_compatibility
from afterlap_contracts import (
    SCHEMA_VERSION,
    ApprovalStatus,
    ModelManifest,
    PromotionPolicy,
    ReasonCode,
)
from afterlap_core.feature_manifest import ENERGY_V1

from .conftest import RULE_PACK_ID

REWARD_REVISION = "objective-v1"
RULESET_HASH = "sha256:" + "1" * 64
MONZA_PACKAGE = "sha256:" + "2" * 64
SPA_PACKAGE = "sha256:" + "3" * 64


def _approved(**overrides: object) -> ModelManifest:
    """An approved bundle that agrees with the session on everything not overridden."""
    fields: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "id": "regime-drill-bundle",
        "algorithm": "SAC",
        "weights_hash": "sha256:" + "a" * 64,
        "feature_schema_hash": ENERGY_V1.content_hash(),
        "rule_family": RULE_PACK_ID,
        "reward_revision": REWARD_REVISION,
        "ruleset_hash": RULESET_HASH,
        "supported_scenario_families": ("two-straight-counterattack",),
        "supported_track_ids": ("monza",),
        "track_package_hashes": {"monza": MONZA_PACKAGE},
        "supported_conditions_ids": ("monza-2026-race",),
        "approval_status": ApprovalStatus.APPROVED,
        "benchmark_report_hash": "sha256:" + "b" * 64,
        "promotion_policy": PromotionPolicy(
            enabled=True,
            minimum_benefit=0.1,
            benefit_metric="elapsed_s",
            downside_noninferiority_limit=0.05,
            latency_limit_ms=200.0,
            frozen_at=datetime.now(UTC),
        ),
        "created_at": datetime.now(UTC),
    }
    fields.update(overrides)
    return ModelManifest(**fields)  # type: ignore[arg-type]


def _decide(bundle: ModelManifest | None, **session: object):  # type: ignore[no-untyped-def]
    defaults: dict[str, object] = {
        "expected_feature_hash": ENERGY_V1.content_hash(),
        "expected_rule_family": RULE_PACK_ID,
        "expected_reward_revision": REWARD_REVISION,
        "expected_ruleset_hash": RULESET_HASH,
        "scenario_family": "two-straight-counterattack",
        "expected_track_id": "monza",
        "expected_track_package_hash": MONZA_PACKAGE,
        "expected_conditions_id": "monza-2026-race",
    }
    defaults.update(session)
    return check_model_compatibility(
        requested_model_hash=None if bundle is None else bundle.content_hash(),
        bundle=bundle,
        baseline_identity=BASELINE_IDENTITY,
        **defaults,  # type: ignore[arg-type]
    )


def test_a_bundle_that_agrees_on_every_pinned_field_is_enabled():
    """The positive case, so the drills below are not passing on an inert check."""
    decision = _decide(_approved())
    print(f"\nagreeing bundle: enabled={decision.enabled}: {decision.detail}")
    assert decision.enabled is True
    assert decision.finding is None
    assert decision.mismatches == ()


@pytest.mark.parametrize(
    ("label", "session_override", "expected_fragment"),
    [
        (
            "the rule pack kept its id but its contents moved",
            {"expected_ruleset_hash": "sha256:" + "9" * 64},
            "limits moved",
        ),
        (
            "the session runs on a circuit outside the split",
            {"expected_track_id": "spa", "expected_track_package_hash": SPA_PACKAGE},
            "outside the bundle's split",
        ),
        (
            "the circuit was recompiled since training",
            {"expected_track_package_hash": SPA_PACKAGE},
            "recompiled geometry",
        ),
        (
            "the session runs under a tape the bundle never saw",
            {"expected_conditions_id": "spa-2026-wet"},
            "outside the bundle's declared regime",
        ),
    ],
)
def test_a_session_outside_the_bundles_regime_falls_back_to_the_named_baseline(
    label: str, session_override: dict[str, object], expected_fragment: str
):
    decision = _decide(_approved(), **session_override)
    print(f"\n{label}: {decision.detail}")

    assert decision.enabled is False, f"{label} was accepted"
    assert any(expected_fragment in m for m in decision.mismatches), decision.mismatches
    assert decision.baseline_identity == BASELINE_IDENTITY
    assert BASELINE_IDENTITY in decision.detail
    assert decision.finding is not None
    assert decision.finding.row is DegradationRow.MODEL_MISMATCH
    assert ReasonCode.BASELINE_FALLBACK in decision.finding.reason_codes
    assert decision.finding.halts_recommendations is False, (
        "a model mismatch disables the learned contribution; it must not stop the session advising "
        "from the baseline that was validated"
    )


def test_an_undeclared_circuit_split_is_unknown_coverage_not_coverage():
    """The gate that matters most while the 23-circuit catalogue is being filled.

    Every bundle written before circuit identity existed declares no split. On
    a synthetic sketch that is simply silence, but on a compiled circuit it is
    a claim nobody made, and a claim nobody made is not permission.
    """
    silent = _approved(supported_track_ids=(), track_package_hashes={})

    on_a_sketch = _decide(silent, expected_track_id=None, expected_track_package_hash=None)
    assert on_a_sketch.enabled is True, (
        "a bundle with no circuit split was refused on a synthetic sketch, where there is no "
        f"compiled circuit to be outside of: {on_a_sketch.detail}"
    )

    on_a_circuit = _decide(silent)
    print(f"\nsilent split on a compiled circuit: {on_a_circuit.detail}")
    assert on_a_circuit.enabled is False
    assert any("undeclared split" in m for m in on_a_circuit.mismatches), on_a_circuit.mismatches


def test_a_named_circuit_with_no_recorded_package_hash_is_refused():
    """Naming a circuit is not the same as identifying the geometry."""
    vague = _approved(track_package_hashes={})
    decision = _decide(vague)
    print(f"\nnamed but unidentified: {decision.detail}")
    assert decision.enabled is False
    assert any("records no compiled package hash" in m for m in decision.mismatches)


def test_an_undeclared_ruleset_hash_is_unknown_not_permission():
    """An older bundle cannot inherit compatibility with the current limits."""
    decision = _decide(_approved(ruleset_hash=None))
    assert decision.enabled is False
    assert any("declares no rule pack content hash" in mismatch for mismatch in decision.mismatches)


def test_no_bundle_at_all_is_the_baseline_path_and_not_a_degradation():
    """The common case. Running without a learned bundle is not a fault."""
    decision = _decide(None, expected_track_id=None, expected_track_package_hash=None)
    assert decision.enabled is False
    assert decision.finding is None, "running on the validated baseline raised a degradation row"
    assert BASELINE_IDENTITY in decision.detail
