"""The ordinary continuation-return ensemble.

Five independent ``192 -> 256 -> 256 -> 1`` MLPs fit the **ordinary discounted
continuation return** under a *named* frozen controller::

    G[t] = r[t] + gamma * r[t + 1] + ... + gamma ^ (T - t - 1) * r[T - 1]

with exactly the environment revision's reward, discount, potential shaping and
terminal treatment. There is **no SAC entropy term** in the labels: this number
is not a soft value function and it is not a race time in seconds. Elapsed time
and finish position are stored as separate evaluation fields.

Three properties the specification insists on, implemented literally:

* targets are standardised on the **training split only** and inverted before
  scoring, so a reported MAE is in the target's own units;
* each member bootstraps **complete episodes**, not individual cutoffs. Closely
  spaced cutoffs inside one episode have correlated targets, and resampling rows
  would understate the disagreement;
* ensemble disagreement approximates model uncertainty. It **is not** a
  calibrated prediction interval and nothing here calls it one.

Out of support — a feature-hash mismatch, too much clipping, too little known
mask, or disagreement above the frozen threshold — the ensemble reports itself
disabled with a reason code and the caller takes the baseline. The disabled path
returns the baseline objects unchanged, so it is bit-for-bit the baseline.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, cast

import numpy as np
import torch
from torch import nn

from afterlap_contracts import NormalizerManifest, SupportThresholds

from ..feature_manifest import ENERGY_V1, OBSERVATION_SIZE, feature_index
from ..paths import atomic_write_bytes, atomic_write_json
from .features import EncodedObservation

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from .config import ValueConfig

__all__ = [
    "ContinuationEnsemble",
    "ContinuationSample",
    "ContinuationScore",
    "FitReport",
    "GroupMetrics",
    "SupportReason",
    "TargetScaler",
    "ValueMember",
    "discounted_returns",
    "fit_ensemble",
]


class SupportReason(StrEnum):
    """Why learned scoring was disabled for one decision."""

    IN_SUPPORT = "in_support"
    FEATURE_HASH_MISMATCH = "feature_hash_mismatch"
    CLIP_FRACTION_EXCEEDED = "clip_fraction_exceeded"
    KNOWN_MASK_TOO_LOW = "known_mask_too_low"
    DISAGREEMENT_EXCEEDED = "ensemble_disagreement_exceeded"
    NON_FINITE_OUTPUT = "non_finite_output"
    THRESHOLDS_NOT_FROZEN = "support_thresholds_not_frozen"


def discounted_returns(rewards: Sequence[float], gamma: float) -> np.ndarray:
    """``G[t]`` for a **complete** episode.

    The caller is responsible for passing a complete episode. A rollout cut at an
    arbitrary point does not have a zero continuation and must not be labelled as
    if it did; ``fit_ensemble`` refuses samples that are not marked complete.
    """
    if not 0.0 < gamma <= 1.0:
        raise ValueError("gamma must lie in (0, 1]")
    out = np.zeros(len(rewards), dtype=np.float64)
    running = 0.0
    for index in range(len(rewards) - 1, -1, -1):
        running = float(rewards[index]) + gamma * running
        out[index] = running
    return out


@dataclass(frozen=True, slots=True)
class ContinuationSample:
    """One saved cutoff: the causal estimate's encoding and its ordinary return.

    ``episode_id`` groups correlated cutoffs so a split or a bootstrap never
    separates them. ``weight`` lets a long episode be down-weighted so it cannot
    dominate the fit.
    """

    observation: np.ndarray
    target: float
    episode_id: str
    scenario_id: str
    family: str
    remaining_distance_m: float | None
    energy_regime: str
    opponent_family: str
    complete_episode: bool = True
    weight: float = 1.0
    elapsed_time_s: float | None = None
    finish_position: int | None = None

    def __post_init__(self) -> None:
        if self.observation.shape != (OBSERVATION_SIZE,):
            raise ValueError(f"a continuation sample needs a ({OBSERVATION_SIZE},) observation")
        if not math.isfinite(self.target):
            raise ValueError("a continuation target must be finite")


@dataclass(frozen=True, slots=True)
class TargetScaler:
    """Standardisation fitted on the training split only."""

    mean: float
    std: float
    fitted_on: str

    @classmethod
    def fit(cls, targets: Sequence[float], *, fitted_on: str) -> TargetScaler:
        array = np.asarray(targets, dtype=np.float64)
        if array.size == 0:
            raise ValueError("cannot fit a target scaler on an empty training split")
        std = float(array.std())
        if std <= 1e-9:
            std = 1.0
        return cls(mean=float(array.mean()), std=std, fitted_on=fitted_on)

    def transform(self, values: np.ndarray) -> np.ndarray:
        return (values - self.mean) / self.std

    def inverse(self, values: np.ndarray) -> np.ndarray:
        return values * self.std + self.mean

    def manifest(self) -> NormalizerManifest:
        return NormalizerManifest(mean=self.mean, std=self.std, fitted_on=self.fitted_on)

    def as_dict(self) -> dict[str, float | str]:
        return {"mean": self.mean, "std": self.std, "fitted_on": self.fitted_on}


class ValueMember(nn.Module):
    """One ensemble member: ``192 -> 256 -> 256 -> 1`` with ReLU."""

    def __init__(self, hidden: Sequence[int] = (256, 256), input_size: int = OBSERVATION_SIZE) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        previous = input_size
        for width in hidden:
            layers.append(nn.Linear(previous, width))
            layers.append(nn.ReLU())
            previous = width
        layers.append(nn.Linear(previous, 1))
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return cast("torch.Tensor", self.net(x).squeeze(-1))


@dataclass(frozen=True, slots=True)
class ContinuationScore:
    """One evaluated continuation value, with its support verdict."""

    value: float
    disagreement: float
    in_support: bool
    reason: SupportReason
    member_values: tuple[float, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "disagreement": self.disagreement,
            "in_support": self.in_support,
            "reason": self.reason.value,
            "member_values": list(self.member_values),
        }


@dataclass(frozen=True, slots=True)
class GroupMetrics:
    """Error for one reporting group. Never aggregated silently across groups."""

    group: str
    key: str
    count: int
    mae: float
    rmse: float
    bias: float

    def as_dict(self) -> dict[str, object]:
        return {
            "group": self.group,
            "key": self.key,
            "count": self.count,
            "mae": self.mae,
            "rmse": self.rmse,
            "bias": self.bias,
        }


@dataclass(frozen=True, slots=True)
class FitReport:
    """What the fit produced. Contains no promotion decision."""

    members: int
    train_episodes: tuple[str, ...]
    tuning_episodes: tuple[str, ...]
    train_samples: int
    tuning_samples: int
    best_epochs: tuple[int, ...]
    bootstrap_episode_ids: tuple[tuple[str, ...], ...]
    overall: GroupMetrics
    groups: tuple[GroupMetrics, ...]
    target_scaler: TargetScaler
    continuation_controller: str
    return_definition_hash: str
    feature_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "members": self.members,
            "train_episodes": list(self.train_episodes),
            "tuning_episodes": list(self.tuning_episodes),
            "train_samples": self.train_samples,
            "tuning_samples": self.tuning_samples,
            "best_epochs": list(self.best_epochs),
            "bootstrap_episode_ids": [list(ids) for ids in self.bootstrap_episode_ids],
            "overall": self.overall.as_dict(),
            "groups": [g.as_dict() for g in self.groups],
            "target_scaler": self.target_scaler.as_dict(),
            "continuation_controller": self.continuation_controller,
            "return_definition_hash": self.return_definition_hash,
            "feature_hash": self.feature_hash,
        }


class ContinuationEnsemble:
    """Five members plus the frozen scaler, hashes and support gates."""

    def __init__(
        self,
        members: Sequence[ValueMember],
        scaler: TargetScaler,
        *,
        feature_hash: str,
        continuation_controller: str,
        return_definition_hash: str,
        support: SupportThresholds,
        hidden: Sequence[int] = (256, 256),
    ) -> None:
        if not members:
            raise ValueError("a continuation ensemble needs at least one member")
        self._members = tuple(members)
        for member in self._members:
            member.eval()
        self._scaler = scaler
        self._feature_hash = feature_hash
        self._controller = continuation_controller
        self._return_hash = return_definition_hash
        self._support = support
        self._hidden = tuple(hidden)

    @property
    def bundle_id(self) -> str:
        return f"continuation/{self._controller}/{self._feature_hash[:16]}"

    @property
    def feature_hash(self) -> str:
        return self._feature_hash

    @property
    def continuation_controller(self) -> str:
        return self._controller

    @property
    def return_definition_hash(self) -> str:
        return self._return_hash

    @property
    def support(self) -> SupportThresholds:
        return self._support

    @property
    def member_count(self) -> int:
        return len(self._members)

    @property
    def target_scaler(self) -> TargetScaler:
        return self._scaler

    def predict(self, observations: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Batch inference. Returns ``(mean, disagreement)`` in target units.

        Single and batch inference agree exactly: a single observation is
        evaluated through the same code path as a batch of one.
        """
        array = np.asarray(observations, dtype=np.float32)
        if array.ndim == 1:
            array = array.reshape(1, -1)
        if array.ndim != 2 or array.shape[1] != OBSERVATION_SIZE:
            raise ValueError(f"expected a batch of ({OBSERVATION_SIZE},) observations, got {array.shape}")
        tensor = torch.from_numpy(np.ascontiguousarray(array))
        with torch.inference_mode():
            stacked = torch.stack([member(tensor) for member in self._members], dim=0)
        standardised = stacked.detach().cpu().numpy().astype(np.float64)
        values = self._scaler.inverse(standardised)
        return values.mean(axis=0), values.std(axis=0)

    def score(self, encoded: EncodedObservation) -> ContinuationScore:
        """Evaluate one encoded observation with the frozen support gates."""
        if encoded.feature_hash != self._feature_hash:
            return ContinuationScore(0.0, 0.0, False, SupportReason.FEATURE_HASH_MISMATCH)
        if encoded.clip_fraction > self._support.max_clip_fraction:
            return ContinuationScore(0.0, 0.0, False, SupportReason.CLIP_FRACTION_EXCEEDED)
        if encoded.known_mask_fraction < self._support.min_known_mask_fraction:
            return ContinuationScore(0.0, 0.0, False, SupportReason.KNOWN_MASK_TOO_LOW)

        mean, spread = self.predict(encoded.observation)
        value = float(mean[0])
        disagreement = float(spread[0])
        if not (math.isfinite(value) and math.isfinite(disagreement)):
            return ContinuationScore(0.0, 0.0, False, SupportReason.NON_FINITE_OUTPUT)
        if disagreement > self._support.max_ensemble_disagreement:
            return ContinuationScore(value, disagreement, False, SupportReason.DISAGREEMENT_EXCEEDED)
        with torch.inference_mode():
            tensor = torch.from_numpy(encoded.observation.reshape(1, -1))
            members = tuple(
                float(self._scaler.inverse(np.asarray(member(tensor).item(), dtype=np.float64)))
                for member in self._members
            )
        return ContinuationScore(value, disagreement, True, SupportReason.IN_SUPPORT, members)

    def state_dicts(self) -> list[dict[str, torch.Tensor]]:
        return [member.state_dict() for member in self._members]

    def save(self, directory: Path) -> dict[str, Path]:
        """Write member weights and the frozen metadata atomically."""
        directory.mkdir(parents=True, exist_ok=True)
        written: dict[str, Path] = {}
        for index, member in enumerate(self._members):
            target = directory / f"value_member_{index}.pt"
            buffer = _serialise_state_dict(member.state_dict())
            atomic_write_bytes(target, buffer)
            written[f"value_member_{index}"] = target
        meta = directory / "value_ensemble.json"
        atomic_write_json(
            meta,
            {
                "members": len(self._members),
                "hidden": list(self._hidden),
                "input_size": OBSERVATION_SIZE,
                "feature_hash": self._feature_hash,
                "continuation_controller": self._controller,
                "return_definition_hash": self._return_hash,
                "target_scaler": self._scaler.as_dict(),
                "support_thresholds": self._support.model_dump(mode="json"),
            },
        )
        written["value_ensemble"] = meta
        return written

    @classmethod
    def load(cls, directory: Path) -> ContinuationEnsemble:
        """Load from a directory, using restricted weights-only deserialisation."""
        meta_path = directory / "value_ensemble.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        hidden = tuple(int(n) for n in meta["hidden"])
        members: list[ValueMember] = []
        for index in range(int(meta["members"])):
            member = ValueMember(hidden=hidden, input_size=int(meta["input_size"]))
            state = torch.load(directory / f"value_member_{index}.pt", map_location="cpu", weights_only=True)
            member.load_state_dict(state)
            member.eval()
            members.append(member)
        scaler_payload = meta["target_scaler"]
        return cls(
            members,
            TargetScaler(
                mean=float(scaler_payload["mean"]),
                std=float(scaler_payload["std"]),
                fitted_on=str(scaler_payload["fitted_on"]),
            ),
            feature_hash=str(meta["feature_hash"]),
            continuation_controller=str(meta["continuation_controller"]),
            return_definition_hash=str(meta["return_definition_hash"]),
            support=SupportThresholds(**meta["support_thresholds"]),
            hidden=hidden,
        )


def _serialise_state_dict(state: Mapping[str, torch.Tensor]) -> bytes:
    import io

    buffer = io.BytesIO()
    torch.save({key: value.cpu() for key, value in state.items()}, buffer)
    return buffer.getvalue()


def _energy_regime(sample: ContinuationSample) -> str:
    return sample.energy_regime


def _remaining_bucket(sample: ContinuationSample) -> str:
    if sample.remaining_distance_m is None:
        return "unknown"
    edges = (250.0, 500.0, 1000.0, 2000.0)
    for edge in edges:
        if sample.remaining_distance_m < edge:
            return f"<{int(edge)}m"
    return f">={int(edges[-1])}m"


_GROUPINGS: dict[str, object] = {
    "remaining_distance": _remaining_bucket,
    "energy_regime": _energy_regime,
    "track": lambda s: s.scenario_id,
    "opponent_family": lambda s: s.opponent_family,
}


def _metrics(name: str, key: str, predicted: np.ndarray, actual: np.ndarray) -> GroupMetrics:
    residual = predicted - actual
    return GroupMetrics(
        group=name,
        key=key,
        count=int(residual.size),
        mae=float(np.abs(residual).mean()) if residual.size else float("nan"),
        rmse=float(np.sqrt((residual**2).mean())) if residual.size else float("nan"),
        bias=float(residual.mean()) if residual.size else float("nan"),
    )


def fit_ensemble(
    samples: Sequence[ContinuationSample],
    config: ValueConfig,
    *,
    return_definition_hash: str,
    seed: int = 0,
    tuning_fraction: float = 0.3,
    feature_hash: str | None = None,
) -> tuple[ContinuationEnsemble, FitReport]:
    """Fit the ensemble on complete episodes and report grouped error.

    The train/tuning split is by **episode**, never by row: adjacent cutoffs of
    the same episode cannot be split across it to imply independent
    generalisation.
    """
    if not samples:
        raise ValueError("cannot fit a continuation ensemble with no samples")
    incomplete = [s.episode_id for s in samples if not s.complete_episode]
    if incomplete:
        raise ValueError(
            "every training sample must come from a complete episode with a real terminal "
            f"outcome; {len(set(incomplete))} episode(s) were marked incomplete. A truncated "
            "rollout needs a separately justified bootstrap target and is out of scope here."
        )

    rng = np.random.default_rng(seed)
    episodes = sorted({s.episode_id for s in samples})
    if len(episodes) < 2:
        raise ValueError("a train/tuning split by episode needs at least two complete episodes")
    shuffled = list(episodes)
    rng.shuffle(shuffled)
    tuning_count = max(1, round(len(shuffled) * tuning_fraction))
    tuning_ids = set(shuffled[:tuning_count])
    train_ids = set(shuffled[tuning_count:])
    if not train_ids:  # pragma: no cover - guarded by the length check above
        raise ValueError("the split left no training episodes")

    train = [s for s in samples if s.episode_id in train_ids]
    tuning = [s for s in samples if s.episode_id in tuning_ids]

    scaler = TargetScaler.fit([s.target for s in train], fitted_on="train")
    x_train = np.stack([s.observation for s in train]).astype(np.float32)
    y_train = scaler.transform(np.array([s.target for s in train], dtype=np.float64)).astype(np.float32)
    w_train = np.array([s.weight for s in train], dtype=np.float32)
    x_tune = np.stack([s.observation for s in tuning]).astype(np.float32)
    y_tune = scaler.transform(np.array([s.target for s in tuning], dtype=np.float64)).astype(np.float32)

    tune_x = torch.from_numpy(x_tune)
    tune_y = torch.from_numpy(y_tune)

    train_episode_list = sorted(train_ids)
    by_episode: dict[str, list[int]] = {}
    for index, sample in enumerate(train):
        by_episode.setdefault(sample.episode_id, []).append(index)

    members: list[ValueMember] = []
    best_epochs: list[int] = []
    bootstrap_ids: list[tuple[str, ...]] = []

    for member_index in range(config.members):
        member_seed = seed * 1000 + member_index
        torch.manual_seed(member_seed)
        member_rng = np.random.default_rng(member_seed)
        drawn = member_rng.choice(len(train_episode_list), size=len(train_episode_list), replace=True)
        drawn_ids = tuple(train_episode_list[int(i)] for i in drawn)
        bootstrap_ids.append(drawn_ids)
        rows = [index for episode in drawn_ids for index in by_episode[episode]]
        member_x = torch.from_numpy(x_train[rows])
        member_y = torch.from_numpy(y_train[rows])
        member_w = torch.from_numpy(w_train[rows])

        member = ValueMember(hidden=config.hidden)
        optimiser = torch.optim.Adam(
            member.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
        )
        loss_fn = nn.HuberLoss(delta=config.huber_delta, reduction="none")

        best_loss = math.inf
        best_state = {k: v.clone() for k, v in member.state_dict().items()}
        best_epoch = 0
        patience = 0
        count = member_x.shape[0]

        for epoch in range(1, config.max_epochs + 1):
            member.train()
            order = torch.from_numpy(member_rng.permutation(count))
            for start in range(0, count, config.batch_size):
                batch = order[start : start + config.batch_size]
                optimiser.zero_grad()
                predicted = member(member_x[batch])
                weights = member_w[batch]
                loss = (loss_fn(predicted, member_y[batch]) * weights).sum() / weights.sum().clamp(min=1e-8)
                loss.backward()
                optimiser.step()
            member.eval()
            with torch.inference_mode():
                tuning_loss = float(
                    nn.functional.huber_loss(member(tune_x), tune_y, delta=config.huber_delta).item()
                )
            if tuning_loss < best_loss - 1e-9:
                best_loss = tuning_loss
                best_state = {k: v.clone() for k, v in member.state_dict().items()}
                best_epoch = epoch
                patience = 0
            else:
                patience += 1
                if patience >= config.patience:
                    break
        member.load_state_dict(best_state)
        member.eval()
        members.append(member)
        best_epochs.append(best_epoch)

    ensemble = ContinuationEnsemble(
        members,
        scaler,
        feature_hash=feature_hash or ENERGY_V1.content_hash(),
        continuation_controller=config.continuation_controller,
        return_definition_hash=return_definition_hash,
        support=config.support,
        hidden=config.hidden,
    )

    predicted, _ = ensemble.predict(x_tune)
    actual = np.array([s.target for s in tuning], dtype=np.float64)
    overall = _metrics("overall", "all", predicted, actual)
    groups: list[GroupMetrics] = []
    for name, key_fn in _GROUPINGS.items():
        buckets: dict[str, list[int]] = {}
        for index, sample in enumerate(tuning):
            buckets.setdefault(str(key_fn(sample)), []).append(index)  # type: ignore[operator]
        for key, indices in sorted(buckets.items()):
            groups.append(_metrics(name, key, predicted[indices], actual[indices]))

    report = FitReport(
        members=config.members,
        train_episodes=tuple(sorted(train_ids)),
        tuning_episodes=tuple(sorted(tuning_ids)),
        train_samples=len(train),
        tuning_samples=len(tuning),
        best_epochs=tuple(best_epochs),
        bootstrap_episode_ids=tuple(bootstrap_ids),
        overall=overall,
        groups=tuple(groups),
        target_scaler=scaler,
        continuation_controller=config.continuation_controller,
        return_definition_hash=return_definition_hash,
        feature_hash=ensemble.feature_hash,
    )
    return ensemble, report


@dataclass
class PlannerContinuationAdapter:
    """Adapts the ensemble to the planner's :class:`ContinuationModel` protocol.

    The planner hands over a small mapping describing the *terminal belief state*
    at the end of its explicit horizon: rolled-out final energy, the horizon
    length and the frame's energy window. That is fewer fields than the 192-value
    encoding, so the terminal encoding is built as **the decision-time encoding
    with the rolled-out terminal energy substituted**.

    That substitution is an approximation and it is recorded as one: fields the
    rollout does not predict are carried forward from the decision-time estimate
    rather than being invented, and the resulting known-mask fraction still has
    to clear the frozen support gate. A caller that wants an exact terminal
    encoding must encode a terminal ``StateEstimate`` and call
    :meth:`ContinuationEnsemble.score` directly.
    """

    ensemble: ContinuationEnsemble
    encoder_reference: EncodedObservation | None = None
    _last_reason: SupportReason = field(default=SupportReason.IN_SUPPORT, init=False)

    @property
    def bundle_id(self) -> str:
        return self.ensemble.bundle_id

    @property
    def last_reason(self) -> SupportReason:
        return self._last_reason

    def set_reference(self, encoded: EncodedObservation) -> None:
        """Pin the decision-time encoding the terminal state is built from."""
        self.encoder_reference = encoded

    def _terminal_encoding(self, features: Mapping[str, float]) -> EncodedObservation | None:
        if self.encoder_reference is None:
            return None
        values = self.encoder_reference.values.copy()
        mask = self.encoder_reference.mask.copy()
        energy = features.get("own_energy_j")
        if energy is not None:
            index = feature_index("own_energy_mean")
            scaled = float(energy) / ENERGY_V1.fields[index].scale
            values[index] = float(np.clip(scaled, -5.0, 5.0))
            mask[index] = 1.0
        observation = np.concatenate([values, mask]).astype(np.float32)
        return EncodedObservation(
            observation=observation,
            values=values,
            mask=mask,
            pre_clip_values=self.encoder_reference.pre_clip_values,
            clipped_indices=self.encoder_reference.clipped_indices,
            unknown_indices=tuple(int(i) for i in np.flatnonzero(mask == 0.0)),
            non_finite_indices=(),
            feature_hash=self.encoder_reference.feature_hash,
            revision=self.encoder_reference.revision,
        )

    def in_support(self, features: Mapping[str, float]) -> bool:
        encoded = self._terminal_encoding(features)
        if encoded is None:
            self._last_reason = SupportReason.KNOWN_MASK_TOO_LOW
            return False
        score = self.ensemble.score(encoded)
        self._last_reason = score.reason
        return score.in_support

    def continuation_value(self, features: Mapping[str, float]) -> tuple[float, float]:
        encoded = self._terminal_encoding(features)
        if encoded is None:  # pragma: no cover - in_support gates this
            return 0.0, math.inf
        score = self.ensemble.score(encoded)
        self._last_reason = score.reason
        return score.value, score.disagreement


def samples_from_episode(
    observations: Sequence[np.ndarray],
    rewards: Sequence[float],
    *,
    gamma: float,
    episode_id: str,
    scenario_id: str,
    family: str,
    opponent_family: str,
    remaining_distance_m: Sequence[float | None] | None = None,
    energy_regimes: Sequence[str] | None = None,
    complete_episode: bool = True,
    elapsed_time_s: float | None = None,
    finish_position: int | None = None,
) -> list[ContinuationSample]:
    """Turn one complete episode into per-cutoff samples with ordinary returns.

    ``weight`` is ``1 / len(episode)`` so a long episode contributes the same
    total weight as a short one and cannot dominate the fit.
    """
    if len(observations) != len(rewards):
        raise ValueError("one observation per reward is required")
    returns = discounted_returns(rewards, gamma)
    weight = 1.0 / max(1, len(rewards))
    out: list[ContinuationSample] = []
    for index, (observation, target) in enumerate(zip(observations, returns, strict=True)):
        out.append(
            ContinuationSample(
                observation=np.asarray(observation, dtype=np.float32),
                target=float(target),
                episode_id=episode_id,
                scenario_id=scenario_id,
                family=family,
                remaining_distance_m=(None if remaining_distance_m is None else remaining_distance_m[index]),
                energy_regime="unknown" if energy_regimes is None else energy_regimes[index],
                opponent_family=opponent_family,
                complete_episode=complete_episode,
                weight=weight,
                elapsed_time_s=elapsed_time_s,
                finish_position=finish_position,
            )
        )
    return out


def energy_regime_of(encoded: EncodedObservation) -> str:
    """Coarse energy bucket from the encoded observation alone."""
    index = feature_index("own_energy_mean")
    if encoded.mask[index] == 0.0:
        return "unknown"
    normalised = float(encoded.values[index])
    if normalised < 0.15:
        return "low"
    if normalised < 0.5:
        return "medium"
    return "high"


def remaining_distance_of(encoded: EncodedObservation) -> float | None:
    """Remaining segment distance in metres, or ``None`` when it is masked.

    Read back through the manifest's own scale so the reporting group is in
    metres rather than in normalised units.
    """
    index = feature_index("remaining_race_distance")
    if encoded.mask[index] == 0.0:
        return None
    field = ENERGY_V1.fields[index]
    return float(encoded.values[index]) * field.scale + field.offset


def collect_episodes(
    env: object,
    *,
    policy: object,
    episodes: int,
    gamma: float,
    seed: int = 0,
    max_steps: int | None = None,
) -> tuple[list[ContinuationSample], list[dict[str, object]]]:
    """Roll out complete episodes under a named frozen controller.

    ``policy`` is any callable ``observation -> action``. The controller's
    identity belongs in the bundle: an ensemble fitted under one controller is
    not a universal value function and must not be reused under another.
    """
    from .env import AfterlapEnv

    if not isinstance(env, AfterlapEnv):  # pragma: no cover - defensive
        raise TypeError("collect_episodes needs an AfterlapEnv")
    if not callable(policy):
        raise TypeError("policy must be callable")

    samples: list[ContinuationSample] = []
    records: list[dict[str, object]] = []
    for episode in range(episodes):
        observation, reset_info = env.reset(seed=seed + episode)
        scenario_id = str(reset_info.get("scenario_id", "unknown"))
        family = str(reset_info.get("scenario_family", "unknown"))
        opponent_family = env.opponent_family

        observations: list[np.ndarray] = []
        rewards: list[float] = []
        remaining: list[float | None] = []
        regimes: list[str] = []
        info: dict[str, object] = {}
        terminated = truncated = False
        steps = 0
        while not (terminated or truncated):
            encoded = env.encoded
            observations.append(np.asarray(observation, dtype=np.float32))
            assert encoded is not None
            regimes.append(energy_regime_of(encoded))
            remaining.append(remaining_distance_of(encoded))
            action = policy(observation)
            observation, reward, terminated, truncated, info = env.step(action)
            rewards.append(float(reward))
            steps += 1
            if max_steps is not None and steps >= max_steps:
                break
        outcome = info.get("episode_outcome", {}) if isinstance(info, dict) else {}
        assert isinstance(outcome, dict)
        complete = bool(terminated)
        episode_id = f"{scenario_id}:{seed + episode}"
        if complete:
            samples.extend(
                samples_from_episode(
                    observations,
                    rewards,
                    gamma=gamma,
                    episode_id=episode_id,
                    scenario_id=scenario_id,
                    family=family,
                    opponent_family=opponent_family,
                    remaining_distance_m=remaining,
                    energy_regimes=regimes,
                    complete_episode=True,
                    elapsed_time_s=outcome.get("elapsed_time_s"),
                    finish_position=outcome.get("finish_position"),
                )
            )
        records.append(
            {
                "episode_id": episode_id,
                "scenario_id": scenario_id,
                "family": family,
                "opponent_family": opponent_family,
                "complete": complete,
                "steps": steps,
                "outcome": outcome,
            }
        )
    return samples, records
