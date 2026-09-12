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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from afterlap_contracts import (
    SCHEMA_VERSION,
    ErrorCode,
    ModelManifest,
    SessionManifest,
    SessionMode,
)
from afterlap_core.config import load_config
from afterlap_core.feature_manifest import ENERGY_V1
from afterlap_core.paths import Paths, sha256_json
from afterlap_core.rules import RulePack, list_rule_packs, load_rule_pack
from afterlap_core.simulation import ScenarioBundle, load_bundle
from afterlap_core.simulation.config import ScenarioConfig, load_car, load_scenario, load_track

from ..db import LifecycleError
from .baseline_planner import BASELINE_IDENTITY
from .circuit import (
    CircuitIdentity,
    describe_track,
    resolve_conditions,
    resolve_event,
    resolve_track_package,
)
from .learned_planner import build_learned_planner
from .model_registry import ModelRegistry, discover_bundles, load_prediction_service
from .observation_source import relational_channels_for, simulator_session_capability
from .runtime import InProcessSessionRuntime, Planner, RuntimeConfig, default_runtime_config

if TYPE_CHECKING:
    from afterlap_contracts.requests import CreateSessionRequest

    from .recorder import SessionRecorder

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
    circuit: CircuitIdentity | None = None

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


def _bundle_for(scenario: ScenarioConfig, track_id: str, paths: Paths | None) -> ScenarioBundle:
    """Resolve the bundle, honouring a request-level track override.

    When the request names the scenario's own track this is exactly
    ``load_bundle``. When it names a different circuit the scenario document is
    left untouched -- its ``config_hash`` still identifies the document on disk
    -- and only the resolved track is swapped, after checking that the
    scenario's evaluation checkpoints exist on the substituted circuit. A
    scenario that cannot be evaluated on the requested track is refused, not
    silently evaluated against nothing.
    """
    if track_id == scenario.track_id:
        return load_bundle(scenario, paths)

    track = load_track(track_id, paths)
    wanted = tuple(scenario.evaluation_checkpoints) + (
        (scenario.retention_checkpoint_id,) if scenario.retention_checkpoint_id else ()
    )
    missing = [cp for cp in dict.fromkeys(wanted) if cp not in track.checkpoint_ids]
    if missing:
        raise SessionValidationError(
            f"scenario {scenario.id!r} evaluates checkpoints {missing} which circuit {track_id!r} does "
            f"not define; it offers {list(track.checkpoint_ids)[:12]}",
            scenario_id=scenario.id,
            track_id=track_id,
        )
    car_configs = {car_id: load_car(cfg_id, paths) for car_id, cfg_id in scenario.cars.items()}
    return ScenarioBundle(scenario=scenario, track=track, car_configs=car_configs)


def resolve_artefacts(
    *,
    scenario_id: str,
    ruleset_id: str,
    model_bundles: dict[str, ModelManifest] | None = None,
    model_bundle_id: str | None = None,
    objective_id: str = DEFAULT_OBJECTIVE_ID,
    paths: Paths | None = None,
    track_id: str | None = None,
    event_id: str | None = None,
    conditions_id: str | None = None,
    seed: int = 0,
) -> ResolvedArtefacts:
    """Load and hash every artefact, refusing anything unknown by name.

    ``track_id``, ``event_id`` and ``conditions_id`` come from the request and
    **override** the scenario document's own values. The override is recorded
    on the manifest, so a session never silently runs on a different circuit
    from the one its identity reports.
    """
    try:
        scenario = load_scenario(scenario_id, paths)
    except FileNotFoundError as exc:
        raise LifecycleError(
            ErrorCode.NOT_FOUND,
            f"scenario {scenario_id!r} does not exist; available: {list(available_scenarios(paths))}",
            scenario_id=scenario_id,
        ) from exc

    effective_track_id = track_id or scenario.track_id
    package = resolve_track_package(effective_track_id, paths)
    bundle = _bundle_for(scenario, effective_track_id, paths)

    circuit = describe_track(bundle.track, package)
    circuit = resolve_event(circuit, event_id or scenario.event_id, paths)
    circuit, environment, _tape = resolve_conditions(
        circuit,
        conditions_id or scenario.conditions_id,
        bundle.track,
        seed=seed,
        paths=paths,
    )
    if environment is not None:
        bundle = bundle.model_copy(
            update={"environment": environment, "environment_hash": circuit.conditions_hash}
        )

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
        circuit=circuit,
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
    circuit = artefacts.circuit
    capability = simulator_session_capability(
        energy_channel_available=observation.energy_channel_available,
        rate_hz=observation_rate_hz,
        relational_channels=relational_channels_for(artefacts.bundle),
        observation_delay_s=float(observation.delay_s.value),
        extra_limitations=() if circuit is None else circuit.notes,
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
        track_id=None if circuit is None else circuit.track_id,
        event_id=None if circuit is None else circuit.event_id,
        track_package_hash=None if circuit is None else circuit.track_package_hash,
        event_package_hash=None if circuit is None else circuit.event_package_hash,
        track_readiness=None if circuit is None else circuit.track_readiness,
        geometry_provenance=None if circuit is None else circuit.geometry_provenance,
        conditions_id=None if circuit is None else circuit.conditions_id,
        conditions_hash=None if circuit is None else circuit.conditions_hash,
    )


class SessionFactory:
    """Creates a validated session and the runtime that owns it."""

    def __init__(
        self,
        *,
        paths: Paths | None = None,
        planner: Planner | None = None,
        recorder_factory: Callable[..., SessionRecorder] | None = None,
        model_bundles: dict[str, ModelManifest] | None = None,
        objective_id: str = DEFAULT_OBJECTIVE_ID,
        config: RuntimeConfig | None = None,
        registry: ModelRegistry | None = None,
        discover_models: bool = True,
    ) -> None:
        self._paths = paths
        self._planner = planner
        self._recorder_factory = recorder_factory
        self._objective_id = objective_id
        self._config = config
        self._registry = registry
        if self._registry is None and discover_models:
            self._registry = discover_bundles(paths)
        self._model_bundles = dict(model_bundles or {})
        if not self._model_bundles and self._registry is not None:
            self._model_bundles = self._registry.manifests

    @property
    def registry(self) -> ModelRegistry | None:
        """What the artefact tree offered, including what it refused and why."""
        return self._registry

    def _planner_for(
        self, artefacts: ResolvedArtefacts, config: RuntimeConfig, session_id: str, seed: int
    ) -> tuple[Planner, tuple[str, ...]]:
        """One planner per session, because a learned planner carries session state.

        An explicitly supplied planner is used unchanged -- that is how a test
        or an operator pins a known planner -- and is the only path that reuses
        one instance across sessions. Otherwise the real MPC planner is built
        for this session's own scenario, with the learned model attached only
        when an approved bundle is pinned for it.
        """
        if self._planner is not None:
            return self._planner, ()
        directory = (
            None
            if self._registry is None
            else self._registry.directory_for(None if artefacts.model is None else artefacts.model.id)
        )
        service, reason = load_prediction_service(
            directory,
            expected_rule_family=artefacts.pack.manifest.ruleset_id,
            expected_reward_revision=artefacts.objective_id,
            baseline_identity=BASELINE_IDENTITY,
        )
        planner, note = build_learned_planner(
            bundle=artefacts.bundle,
            pack=artefacts.pack,
            session_id=session_id,
            prediction=service,
            seed=seed,
            plan_validity_s=config.recommendation_validity_s,
            rollout_enabled=config.planner_rollout_enabled,
        )
        notes = tuple(item for item in (reason, note) if item)
        return planner, notes

    @property
    def paths(self) -> Paths | None:
        """The artefact tree sessions resolve from.

        The read-only catalogue routes read this, so ``GET /tracks`` cannot
        report a package from one tree while a session runs one from another --
        which is precisely how a hash reported to an operator stops matching
        the hash a session actually used.
        """
        return self._paths

    def create(
        self, payload: CreateSessionRequest, *, session_id: str | None = None
    ) -> tuple[SessionManifest, InProcessSessionRuntime]:
        """Resolve, validate and start one session.

        ``session_id`` pins the manifest id instead of minting one. An
        out-of-process worker is addressed by an id the control plane chose
        before the child existed; without this the child's durable records
        would carry a different id from the commands that produced them, and
        one session's history would silently split in two.
        """
        artefacts, config = self._resolve(payload)
        manifest = build_manifest(
            artefacts,
            mode=payload.mode,
            seed=payload.seed,
            label=payload.label,
            session_id=session_id,
            observation_rate_hz=config.observation_rate_hz,
        )
        return manifest, self.create_from_manifest(payload, manifest, resolved=(artefacts, config))

    def prepare(self, payload: CreateSessionRequest, *, session_id: str | None = None) -> SessionManifest:
        """Validate inputs and freeze identity without constructing dynamics."""
        artefacts, config = self._resolve(payload)
        return build_manifest(
            artefacts,
            mode=payload.mode,
            seed=payload.seed,
            label=payload.label,
            session_id=session_id,
            observation_rate_hz=config.observation_rate_hz,
        )

    def create_from_manifest(
        self,
        payload: CreateSessionRequest,
        manifest: SessionManifest,
        *,
        resolved: tuple[ResolvedArtefacts, RuntimeConfig] | None = None,
    ) -> InProcessSessionRuntime:
        """Construct the in-process adapter for an already frozen identity."""
        artefacts, config = resolved or self._resolve(payload)
        expected = build_manifest(
            artefacts,
            mode=payload.mode,
            seed=payload.seed,
            label=payload.label,
            session_id=manifest.id,
            observation_rate_hz=config.observation_rate_hz,
        )
        comparable = expected.model_copy(update={"created_at": manifest.created_at})
        if comparable.content_hash() != manifest.content_hash():
            raise SessionValidationError("session artefacts changed after the manifest was frozen")
        recorder: SessionRecorder | None = None
        if self._recorder_factory is not None:
            recorder = self._recorder_factory(manifest.id)
        planner, planner_notes = self._planner_for(artefacts, config, manifest.id, payload.seed)
        runtime = InProcessSessionRuntime(
            bundle=artefacts.bundle,
            pack=artefacts.pack,
            planner=planner,
            config=config,
            recorder=recorder,
            model_bundle=artefacts.model,
            objective_version=artefacts.objective_id,
            expected_feature_hash=ENERGY_V1.content_hash(),
            planner_notes=planner_notes,
        )
        runtime.initialise(manifest, artefacts.bundle.scenario.id, payload.seed)
        return runtime

    def _resolve(self, payload: CreateSessionRequest) -> tuple[ResolvedArtefacts, RuntimeConfig]:
        artefacts = resolve_artefacts(
            scenario_id=payload.scenario_id,
            ruleset_id=payload.ruleset_id,
            model_bundles=self._model_bundles,
            model_bundle_id=payload.model_bundle_id,
            objective_id=self._objective_id,
            paths=self._paths,
            track_id=payload.track_id,
            event_id=payload.event_id,
            conditions_id=payload.conditions_id,
            seed=payload.seed,
        )
        validate_combination(artefacts, payload.mode)
        config = self._config or default_runtime_config(artefacts.bundle)
        return artefacts, config


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
