"""AFTERLAP learning: environment, SAC training, continuation value and serving.

Module map
----------

``features``     the frozen ``energy-v1`` encoder, driven by ``ENERGY_V1``
``actions``      the two bounded soft preferences and their reachable bounds
``reward``       reward revision ``objective-v1`` and its potential shaping
``bridge``       simulator observation -> belief -> rule context -> features
``env``          the Gymnasium environment at a one-second policy cadence
``config``       readers for ``configs/learning/``
``value``        the ordinary continuation-return ensemble
``serving``      the frozen bundle, its hashes and the loader that refuses
``promotion``    ``promote_bundle``, whose default answer is no
``architecture``  layer tables and trainable-parameter counts, read off the modules
``policy``       the frozen actor, rebuilt from bundle weights and made runnable
``packaging``    a verified checkpoint becomes a loadable bundle with a real card
``jobs``         the operator entry points behind the coordinator CLI
``checkpoints``  atomic checkpointing and resume
``callbacks``    training metrics and the non-finite-loss guard
``train_sac``    SB3 SAC training, resume and the throughput benchmark

What this package will not do
-----------------------------

* It does not replace a constraint. Preferences are soft; the planner still
  returns a legal plan and the independent checker's verdict is final.
* It does not promote itself. Promotion needs frozen thresholds and a real
  benchmark report, and refuses without them.
* It does not report a training result it did not observe. A smoke run is
  labelled a smoke run wherever it appears.
* Nothing here is a measured result about a real car, circuit or race.
"""

from __future__ import annotations

from .actions import (
    ActionBounds,
    BoundsStatus,
    DecodedPreferences,
    action_space,
    compute_bounds,
    decode_action,
)
from .architecture import (
    ArchitectureReport,
    LayerSpec,
    NetworkArchitecture,
    describe_ensemble,
    describe_module,
    describe_sac,
    parameter_totals,
)
from .config import (
    EnvConfig,
    SacConfig,
    ScenarioSpec,
    ValueConfig,
    load_env_config,
    load_sac_config,
    load_value_config,
)
from .features import (
    EncodedObservation,
    FeatureContext,
    FeatureEncoder,
    HistorySummary,
    LookaheadSample,
    encode,
)
from .policy import ActorPolicy, PolicyLoadError, load_actor
from .promotion import (
    FrozenPromotionPolicy,
    PromotionDecision,
    RefusalCode,
    decide_from_paths,
    load_promotion_policy,
    promote_bundle,
)
from .reward import (
    REWARD_REVISION,
    RewardTerms,
    load_reward_manifest,
    objective_content_hash,
    potential,
    step_reward,
)
from .serving import (
    BUNDLE_SCHEMA_VERSION,
    DEFAULT_BASELINE_IDENTITY,
    BundleRejection,
    LoadedBundle,
    RejectionReason,
    load_bundle,
    write_bundle,
)
from .value import (
    ContinuationEnsemble,
    ContinuationSample,
    ContinuationScore,
    FitReport,
    SupportReason,
    TargetScaler,
    ValueMember,
    discounted_returns,
    fit_ensemble,
)

__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "DEFAULT_BASELINE_IDENTITY",
    "REWARD_REVISION",
    "ActionBounds",
    "ActorPolicy",
    "ArchitectureReport",
    "BoundsStatus",
    "BundleRejection",
    "ContinuationEnsemble",
    "ContinuationSample",
    "ContinuationScore",
    "DecodedPreferences",
    "EncodedObservation",
    "EnvConfig",
    "FeatureContext",
    "FeatureEncoder",
    "FitReport",
    "FrozenPromotionPolicy",
    "HistorySummary",
    "LayerSpec",
    "LoadedBundle",
    "LookaheadSample",
    "NetworkArchitecture",
    "PolicyLoadError",
    "PromotionDecision",
    "RefusalCode",
    "RejectionReason",
    "RewardTerms",
    "SacConfig",
    "ScenarioSpec",
    "SupportReason",
    "TargetScaler",
    "ValueConfig",
    "ValueMember",
    "action_space",
    "compute_bounds",
    "decide_from_paths",
    "decode_action",
    "describe_ensemble",
    "describe_module",
    "describe_sac",
    "discounted_returns",
    "encode",
    "fit_ensemble",
    "load_actor",
    "load_bundle",
    "load_env_config",
    "load_promotion_policy",
    "load_reward_manifest",
    "load_sac_config",
    "load_value_config",
    "objective_content_hash",
    "parameter_totals",
    "potential",
    "promote_bundle",
    "step_reward",
    "write_bundle",
]
