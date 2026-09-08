"""Session creation: resolve manifests, hash them, validate, then start.

``routes/sessions.py`` calls ``app.state.session_factory.create(payload)`` and
expects ``(SessionManifest, runtime)``. Everything a session's identity depends
on is resolved and hashed *before* the runtime exists, so a session cannot be
started against artefacts that were never validated together.

Refusals are explicit. An unknown scenario id or an unknown ruleset id is a
typed :class:`~afterlap_api.db.LifecycleError` naming what is available — never a
silent fallback to a default scenario, which would produce a session whose
manifest describes something the operator did not ask for.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from afterlap_contracts import (
    SCHEMA_VERSION,
    ErrorCode,
    ModelManifest,
    SessionManifest,
    SessionMode,
)
from afterlap_contracts.requests import CreateSessionRequest
from afterlap_core.config import load_config
from afterlap_core.paths import Paths, sha256_json
from afterlap_core.rules import RulePack, list_rule_packs, load_rule_pack
from afterlap_core.simulation import ScenarioBundle, load_bundle
from afterlap_core.simulation.config import load_scenario

from ..db import LifecycleError
from .baseline_planner import BaselinePlanner
from .observation_source import simulator_session_capability
from .recorder import SessionRecorder
from .runtime import InProcessSessionRuntime, Planner, RuntimeConfig, default_runtime_config

DEFAULT_OBJECTIVE_ID = "objective-v1"


class SessionValidationError(LifecycleError):
    """The requested combination of artefacts cannot form a valid session."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(ErrorCode.VALIDATION_FAILED, message, **details)


@dataclass(frozen=True, slots=True)
class ResolvedArtefacts:
    """Everything a session's identity is built from, with real content hashes."""

    bundle: ScenarioBundle
    pack: RulePack
    objective_id: str
    objective_hash: str
    model: ModelManifest | None

    @property
    def track_hash(self) -> str:
        return self.bundle.track.config_hash

    @property
    def car_hashes(self) -> dict[str, str]:
        return {car_id: config.config_hash for car_id, config in sorted(self.bundle.car_configs.items())}

    @property
    def scenario_hash(self) -> str:
        return self.bundle.scenario.config_hash

    @property
    def bundle_hash(self) -> str:
        return self.bundle.bundle_hash


def available_scenarios(paths: Paths | None = None) -> tuple[str, ...]:
    root = (paths or Paths.default()).configs / "scenarios"
    return tuple(sorted(p.stem for p in root.glob("*.yaml"))) if root.is_dir() else ()


def resolve_artefacts(
    *,
    scenario_id: str,
    ruleset_id: str,
    model_bundles: dict[str, ModelManifest] | None = None,
    model_bundle_id: str | None = None,
    objective_id: str = DEFAULT_OBJECTIVE_ID,
    paths: Paths | None = None,
) -> ResolvedArtefacts:
    """Load and hash every artefact, refusing anything unknown by name."""
    try:
        scenario = load_scenario(scenario_id, paths)
    except FileNotFoundError as exc:
        raise LifecycleError(
            ErrorCode.NOT_FOUND,
            f"scenario {scenario_id!r} does not exist; available: {list(available_scenarios(paths))}",
            scenario_id=scenario_id,
        ) from exc
    bundle = load_bundle(scenario, paths)

    try:
        pack = load_rule_pack(ruleset_id, paths)
    except FileNotFoundError as exc:
        raise LifecycleError(
            ErrorCode.NOT_FOUND,
            f"ruleset {ruleset_id!r} does not exist; available: {list(list_rule_packs(paths))}",
            ruleset_id=ruleset_id,
        ) from exc

    objective_hash = _objective_hash(objective_id, paths)

    model: ModelManifest | None = None
    if model_bundle_id is not None:
        available = model_bundles or {}
        model = available.get(model_bundle_id)
        if model is None:
            raise LifecycleError(
                ErrorCode.NOT_FOUND,
                f"model bundle {model_bundle_id!r} is not loaded; available: {sorted(available)}",
                model_bundle_id=model_bundle_id,
            )

    return ResolvedArtefacts(
        bundle=bundle,
        pack=pack,
        objective_id=objective_id,
        objective_hash=objective_hash,
        model=model,
    )


def validate_combination(artefacts: ResolvedArtefacts, mode: SessionMode) -> None:
    """Refuse a combination that cannot produce a legal session.

    These are checks the individual modules cannot make on their own: each is
    valid in isolation and only their *combination* is wrong.
    """
    if mode is not SessionMode.SIMULATION:
        raise SessionValidationError(
            f"the in-process session runtime drives a simulator; mode {mode.value!r} needs a "
            "replay or team-feed runtime, which is not implemented",
            mode=mode.value,
        )

    manifest = artefacts.pack.manifest
    scenario = artefacts.bundle.scenario
    track_length = artefacts.bundle.track.length

    for line in manifest.detection_lines:
        if not 0.0 <= line.s_m < track_length:
            raise SessionValidationError(
                f"rule pack {manifest.ruleset_id!r} places {line.line_id!r} at {line.s_m} m, "
                f"outside track {artefacts.bundle.track.id!r} of length {track_length} m",
                line_id=line.line_id,
            )

    for car_id, car in sorted(artefacts.bundle.car_configs.items()):
        low = float(car.battery_energy_min_j.value)
        high = float(car.battery_energy_max_j.value)
        if low < manifest.battery_energy_min_j or high > manifest.battery_energy_max_j:
            raise SessionValidationError(
                f"car {car_id!r} operates in [{low}, {high}] J, outside the rule pack window "
                f"[{manifest.battery_energy_min_j}, {manifest.battery_energy_max_j}] J",
                car_id=car_id,
            )

    for car_id, initial in sorted(scenario.initial_states.items()):
        energy = float(initial.energy_j.value)
        if not manifest.battery_energy_min_j <= energy <= manifest.battery_energy_max_j:
            raise SessionValidationError(
                f"car {car_id!r} starts at {energy} J, outside the rule pack battery window",
                car_id=car_id,
            )

    for checkpoint in scenario.evaluation_checkpoints:
        if checkpoint not in artefacts.bundle.track.checkpoint_ids:
            raise SessionValidationError(
                f"scenario {scenario.id!r} evaluates unknown checkpoint {checkpoint!r}",
                checkpoint_id=checkpoint,
            )


def build_manifest(
    artefacts: ResolvedArtefacts,
    *,
    mode: SessionMode,
    seed: int,
    label: str | None,
    session_id: str | None = None,
    observation_rate_hz: float = 20.0,
) -> SessionManifest:
    """Immutable session identity with real content hashes."""
    observation = artefacts.bundle.scenario.observation
    capability = simulator_session_capability(
        energy_channel_available=observation.energy_channel_available,
        rate_hz=observation_rate_hz,
        observation_delay_s=float(observation.delay_s.value),
    )
    return SessionManifest(
        schema_version=SCHEMA_VERSION,
        id=session_id or f"ses-{uuid.uuid4().hex[:16]}",
        mode=mode,
        track_hash=artefacts.track_hash,
        car_hashes=artefacts.car_hashes,
        ruleset_hash=artefacts.pack.ruleset_hash,
        model_hash=None if artefacts.model is None else artefacts.model.content_hash(),
        objective_hash=artefacts.objective_hash,
        seed=seed,
        created_at=datetime.now(UTC),
        source_capabilities=(capability,),
        scenario_id=artefacts.bundle.scenario.id,
        synthetic=artefacts.bundle.scenario.synthetic and artefacts.pack.manifest.synthetic,
        label=label,
    )


class SessionFactory:
    """Creates a validated session and the runtime that owns it."""

    def __init__(
        self,
        *,
        paths: Paths | None = None,
        planner: Planner | None = None,
        recorder_factory=None,  # type: ignore[no-untyped-def]
        model_bundles: dict[str, ModelManifest] | None = None,
        objective_id: str = DEFAULT_OBJECTIVE_ID,
        config: RuntimeConfig | None = None,
    ) -> None:
        self._paths = paths
        self._planner = planner or BaselinePlanner()
        self._recorder_factory = recorder_factory
        self._model_bundles = model_bundles or {}
        self._objective_id = objective_id
        self._config = config

    def create(self, payload: CreateSessionRequest) -> tuple[SessionManifest, InProcessSessionRuntime]:
        artefacts = resolve_artefacts(
            scenario_id=payload.scenario_id,
            ruleset_id=payload.ruleset_id,
            model_bundles=self._model_bundles,
            model_bundle_id=payload.model_bundle_id,
            objective_id=self._objective_id,
            paths=self._paths,
        )
        validate_combination(artefacts, payload.mode)

        config = self._config or default_runtime_config(artefacts.bundle)
        manifest = build_manifest(
            artefacts,
            mode=payload.mode,
            seed=payload.seed,
            label=payload.label,
            observation_rate_hz=config.observation_rate_hz,
        )
        recorder: SessionRecorder | None = None
        if self._recorder_factory is not None:
            recorder = self._recorder_factory(manifest.id)

        runtime = InProcessSessionRuntime(
            bundle=artefacts.bundle,
            pack=artefacts.pack,
            planner=self._planner,
            config=config,
            recorder=recorder,
            model_bundle=artefacts.model,
            objective_version=artefacts.objective_id,
        )
        runtime.initialise(manifest, artefacts.bundle.scenario.id, payload.seed)
        return manifest, runtime


def _objective_hash(objective_id: str, paths: Paths | None) -> str:
    """Content hash of the frozen objective revision."""
    try:
        document = load_config("objectives", objective_id, paths)
    except FileNotFoundError as exc:
        raise LifecycleError(
            ErrorCode.NOT_FOUND,
            f"objective revision {objective_id!r} does not exist",
            objective_id=objective_id,
        ) from exc
    return sha256_json(document)


__all__ = [
    "DEFAULT_OBJECTIVE_ID",
    "ResolvedArtefacts",
    "SessionFactory",
    "SessionValidationError",
    "available_scenarios",
    "build_manifest",
    "resolve_artefacts",
    "validate_combination",
]
