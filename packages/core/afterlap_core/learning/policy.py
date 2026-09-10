"""The frozen actor, made runnable.

``serving.load_bundle`` validates a bundle and hands back ``actor_state`` as a
mapping of tensors. A mapping of tensors is not a policy: something has to know
which architecture those tensors belong to. This module is that step, and it is
deliberately the *only* one.

Two decisions here are load-bearing.

**The network is rebuilt with the pinned library's own actor class**, not with a
local re-implementation of it. A hand-written forward pass that squashes with
the wrong convention would produce plausible actions from correct weights, and
nothing downstream could detect it. ``load_state_dict`` is called with
``strict=True`` so a shape or key that does not match refuses rather than
loading partially.

**Inference is deterministic and has no exploration path.** ``AGENTS.md``
forbids live exploration, so there is no sampling branch to switch on: the
actor mean is the only output, evaluated under ``torch.inference_mode`` with
the module in evaluation mode. A caller that wants a stochastic action would
have to write one, which is the intended amount of friction.

The actor's output is a pair of *soft preferences*, never a control. It reaches
the planner as a warm start and nothing else; the feasible set, the independent
checker and the baseline candidates are untouched by it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import torch

from ..feature_manifest import ACTION_SIZE, OBSERVATION_SIZE
from .actions import ACTION_HIGH, ACTION_LOW, ActionBounds, DecodedPreferences, decode_action

__all__ = [
    "ActorPolicy",
    "PolicyLoadError",
    "load_actor",
]


class PolicyLoadError(RuntimeError):
    """The actor weights could not be turned into a runnable network."""


@dataclass(frozen=True, slots=True)
class ActorPolicy:
    """A frozen deterministic actor over the ``energy-v1`` observation.

    ``net_arch`` is recovered from the weights themselves rather than taken
    from a configuration document, so a bundle trained at one width cannot be
    loaded into a network of another and silently reinitialised.
    """

    module: torch.nn.Module
    net_arch: tuple[int, ...]
    bundle_id: str
    observation_size: int = OBSERVATION_SIZE
    action_size: int = ACTION_SIZE

    def act(self, observation: np.ndarray) -> np.ndarray:
        """One deterministic action in ``[-1, 1]^2``. No exploration path."""
        array = np.asarray(observation, dtype=np.float32).reshape(-1)
        if array.shape != (self.observation_size,):
            raise PolicyLoadError(
                f"the actor expects a ({self.observation_size},) observation, got {array.shape}"
            )
        if not np.all(np.isfinite(array)):
            raise PolicyLoadError("the observation contains a non-finite component")
        tensor = torch.from_numpy(np.ascontiguousarray(array)).unsqueeze(0)
        with torch.inference_mode():
            action = self.module(tensor, deterministic=True)
        decoded = action.detach().cpu().numpy().astype(np.float64).reshape(-1)
        return np.clip(decoded, ACTION_LOW, ACTION_HIGH)

    def preferences(self, observation: np.ndarray, bounds: ActionBounds) -> DecodedPreferences:
        """The decoded soft preferences for one tick, under this tick's bounds."""
        return decode_action(self.act(observation), bounds)

    def __call__(self, observation: np.ndarray) -> np.ndarray:
        return self.act(observation)


def _hidden_widths(state: dict[str, torch.Tensor]) -> tuple[int, ...]:
    widths: list[int] = []
    index = 0
    while True:
        key = f"latent_pi.{index}.weight"
        tensor = state.get(key)
        if tensor is None:
            break
        widths.append(int(tensor.shape[0]))
        index += 2
    if not widths:
        raise PolicyLoadError(
            "the actor weights declare no `latent_pi.*.weight` layer; this is not a "
            "Stable-Baselines3 SAC actor state dict"
        )
    return tuple(widths)


def _observation_size(state: dict[str, torch.Tensor]) -> int:
    first = state.get("latent_pi.0.weight")
    if first is None:  # pragma: no cover - guarded by _hidden_widths
        raise PolicyLoadError("the actor weights have no input layer")
    return int(first.shape[1])


def _action_size(state: dict[str, torch.Tensor]) -> int:
    head = state.get("mu.weight")
    if head is None:
        raise PolicyLoadError("the actor weights have no `mu` head; a mean action cannot be produced")
    return int(head.shape[0])


def load_actor(
    actor_state: dict[str, torch.Tensor],
    *,
    bundle_id: str,
    expected_observation_size: int = OBSERVATION_SIZE,
    expected_action_size: int = ACTION_SIZE,
) -> ActorPolicy:
    """Rebuild the frozen actor from a validated bundle's weights.

    Raises :class:`PolicyLoadError` rather than returning a degraded policy: a
    caller that cannot load an actor must fall back to the named baseline, and
    a half-initialised network would look like a working one.
    """
    if not actor_state:
        raise PolicyLoadError("the bundle carried no actor weights")

    widths = _hidden_widths(actor_state)
    observation_size = _observation_size(actor_state)
    action_size = _action_size(actor_state)
    if observation_size != expected_observation_size:
        raise PolicyLoadError(
            f"the actor was trained on a {observation_size}-value observation but this "
            f"environment encodes {expected_observation_size}; the feature revisions differ"
        )
    if action_size != expected_action_size:
        raise PolicyLoadError(
            f"the actor emits {action_size} preferences but the action manifest declares "
            f"{expected_action_size}"
        )

    try:
        from gymnasium import spaces
        from stable_baselines3.common.torch_layers import FlattenExtractor
        from stable_baselines3.sac.policies import Actor
    except ImportError as exc:
        raise PolicyLoadError(
            f"the learning extra is not installed, so the frozen actor cannot be rebuilt: {exc}"
        ) from exc

    observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(observation_size,), dtype=np.float32)
    action_space = spaces.Box(low=ACTION_LOW, high=ACTION_HIGH, shape=(action_size,), dtype=np.float32)
    module: Any = Actor(
        observation_space=observation_space,
        action_space=action_space,
        net_arch=list(widths),
        features_extractor=FlattenExtractor(observation_space),
        features_dim=observation_size,
    )
    try:
        module.load_state_dict(actor_state, strict=True)
    except (RuntimeError, KeyError) as exc:
        raise PolicyLoadError(f"the actor weights do not fit the rebuilt network: {exc}") from exc

    module.set_training_mode(False)
    for parameter in module.parameters():
        parameter.requires_grad_(False)
    return ActorPolicy(
        module=module,
        net_arch=widths,
        bundle_id=bundle_id,
        observation_size=observation_size,
        action_size=action_size,
    )
