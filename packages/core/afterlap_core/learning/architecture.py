"""Architecture description and trainable-parameter counting.

A model card that names a hidden width but not a parameter count describes an
intention rather than an artifact. Everything here is *read off the constructed
modules*, never off the configuration document: a ``net_arch`` entry is a
request, and the tensors that exist afterwards are the answer.

Counts are reported separately because they answer different questions, and one
distinction here is easy to get wrong in a way that inflates a headline figure.

``trainable_parameters`` is what ``requires_grad`` says. ``frozen_parameters``
is what is carried with ``requires_grad`` off. ``buffer_elements`` is state that
is neither.

None of those is the number a reader wants for "how big is this model", because
Stable-Baselines3 builds the target critic as a *full copy of the critic* and
leaves ``requires_grad=True`` on it -- verified against the pinned 2.9.0, whose
``SACPolicy._build`` calls only ``load_state_dict`` and
``set_training_mode(False)``. The target is updated by Polyak averaging, not by
the optimiser, which is constructed over ``critic.parameters()`` alone. Summing
``trainable_parameters`` across actor, critic and target therefore counts the
critic twice.

``optimiser_updated_parameters`` is the honest headline: parameters some
optimiser actually steps. A network is marked ``optimiser_updated=False`` when
its updates come from somewhere else, and the report carries both totals so
neither can be quoted without the other being available.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any

from torch import nn

from ..paths import sha256_bytes

__all__ = [
    "ArchitectureReport",
    "LayerSpec",
    "NetworkArchitecture",
    "describe_ensemble",
    "describe_module",
    "describe_sac",
    "parameter_totals",
]


@dataclass(frozen=True, slots=True)
class LayerSpec:
    """One parameterised leaf module, as it exists after construction."""

    name: str
    kind: str
    in_features: int | None
    out_features: int | None
    parameter_count: int
    trainable: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "in_features": self.in_features,
            "out_features": self.out_features,
            "parameter_count": self.parameter_count,
            "trainable": self.trainable,
        }


@dataclass(frozen=True, slots=True)
class NetworkArchitecture:
    """A described network: its layers, its counts and its shape."""

    identity: str
    module_class: str
    layers: tuple[LayerSpec, ...]
    trainable_parameters: int
    frozen_parameters: int
    buffer_elements: int
    input_size: int | None = None
    output_size: int | None = None
    activation: str | None = None
    optimiser_updated: bool = True
    update_rule: str = "optimiser"

    @property
    def total_parameters(self) -> int:
        return self.trainable_parameters + self.frozen_parameters

    @property
    def optimiser_updated_parameters(self) -> int:
        """Parameters an optimiser steps. Zero for a Polyak-tracked copy."""
        return self.trainable_parameters if self.optimiser_updated else 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "module_class": self.module_class,
            "input_size": self.input_size,
            "output_size": self.output_size,
            "activation": self.activation,
            "trainable_parameters": self.trainable_parameters,
            "frozen_parameters": self.frozen_parameters,
            "total_parameters": self.total_parameters,
            "optimiser_updated": self.optimiser_updated,
            "optimiser_updated_parameters": self.optimiser_updated_parameters,
            "update_rule": self.update_rule,
            "buffer_elements": self.buffer_elements,
            "layers": [layer.as_dict() for layer in self.layers],
        }

    def as_markdown_table(self) -> str:
        header = "| layer | kind | in | out | parameters | trainable |\n|---|---|---:|---:|---:|---|\n"
        rows = "".join(
            f"| `{layer.name}` | {layer.kind} | "
            f"{'-' if layer.in_features is None else layer.in_features} | "
            f"{'-' if layer.out_features is None else layer.out_features} | "
            f"{layer.parameter_count:,} | {'yes' if layer.trainable else 'no'} |\n"
            for layer in self.layers
        )
        total = (
            f"| **total** | {self.module_class} | "
            f"{'-' if self.input_size is None else self.input_size} | "
            f"{'-' if self.output_size is None else self.output_size} | "
            f"**{self.total_parameters:,}** | "
            f"{self.update_rule} |\n"
        )
        return header + rows + total


@dataclass(frozen=True, slots=True)
class ArchitectureReport:
    """Every described network in one artifact, plus the totals across them."""

    networks: tuple[NetworkArchitecture, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def trainable_parameters(self) -> int:
        """Sum of ``requires_grad`` parameters. Counts a target copy again."""
        return sum(net.trainable_parameters for net in self.networks)

    @property
    def optimiser_updated_parameters(self) -> int:
        """Parameters an optimiser steps. This is the headline model size."""
        return sum(net.optimiser_updated_parameters for net in self.networks)

    @property
    def total_parameters(self) -> int:
        return sum(net.total_parameters for net in self.networks)

    def named(self, identity: str) -> NetworkArchitecture | None:
        for net in self.networks:
            if net.identity == identity:
                return net
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "networks": [net.as_dict() for net in self.networks],
            "optimiser_updated_parameters": self.optimiser_updated_parameters,
            "trainable_parameters": self.trainable_parameters,
            "total_parameters": self.total_parameters,
            "counting_note": (
                "optimiser_updated_parameters is the model size; trainable_parameters sums every "
                "requires_grad tensor and therefore counts a Polyak-tracked target copy a second "
                "time"
            ),
            "notes": list(self.notes),
        }

    def content_hash(self) -> str:
        return sha256_bytes(json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8"))

    def as_markdown(self) -> str:
        if not self.networks:
            return "No network was described, which is itself a defect.\n"
        blocks = [
            f"**{net.identity}** ({net.module_class})\n\n{net.as_markdown_table()}" for net in self.networks
        ]
        summary = (
            f"Across {len(self.networks)} network(s): "
            f"**{self.optimiser_updated_parameters:,} optimiser-updated parameters** of "
            f"{self.total_parameters:,} total. The `trainable` sum "
            f"({self.trainable_parameters:,}) counts a Polyak-tracked target copy a second time "
            f"and is not the model size.\n"
        )
        note_lines = "".join(f"- {note}\n" for note in self.notes)
        return "\n".join(blocks) + "\n" + summary + (f"\n{note_lines}" if note_lines else "")


def parameter_totals(module: nn.Module) -> tuple[int, int, int]:
    """``(trainable, frozen, buffer_elements)`` for one module tree."""
    trainable = 0
    frozen = 0
    for parameter in module.parameters():
        if parameter.requires_grad:
            trainable += int(parameter.numel())
        else:
            frozen += int(parameter.numel())
    buffers = sum(int(buffer.numel()) for buffer in module.buffers())
    return trainable, frozen, buffers


def _leaf_specs(module: nn.Module) -> tuple[LayerSpec, ...]:
    specs: list[LayerSpec] = []
    for name, child in module.named_modules():
        own = list(child.named_parameters(recurse=False))
        if not own:
            continue
        count = sum(int(parameter.numel()) for _, parameter in own)
        trainable = any(parameter.requires_grad for _, parameter in own)
        specs.append(
            LayerSpec(
                name=name or type(child).__name__,
                kind=type(child).__name__,
                in_features=getattr(child, "in_features", None),
                out_features=getattr(child, "out_features", None),
                parameter_count=count,
                trainable=trainable,
            )
        )
    return tuple(specs)


def _activation_name(module: nn.Module) -> str | None:
    for child in module.modules():
        if isinstance(child, nn.ReLU | nn.Tanh | nn.ELU | nn.GELU | nn.SiLU | nn.LeakyReLU):
            return type(child).__name__
    return None


def describe_module(
    module: nn.Module,
    *,
    identity: str,
    input_size: int | None = None,
    output_size: int | None = None,
) -> NetworkArchitecture:
    """Describe a constructed module by walking its own parameters."""
    trainable, frozen, buffers = parameter_totals(module)
    specs = _leaf_specs(module)
    resolved_input = input_size
    if resolved_input is None:
        for spec in specs:
            if spec.in_features is not None:
                resolved_input = spec.in_features
                break
    resolved_output = output_size
    if resolved_output is None:
        for spec in reversed(specs):
            if spec.out_features is not None:
                resolved_output = spec.out_features
                break
    return NetworkArchitecture(
        identity=identity,
        module_class=type(module).__name__,
        layers=specs,
        trainable_parameters=trainable,
        frozen_parameters=frozen,
        buffer_elements=buffers,
        input_size=resolved_input,
        output_size=resolved_output,
        activation=_activation_name(module),
    )


def describe_sac(model: Any, *, identity_prefix: str = "sac") -> ArchitectureReport:
    """Describe an SB3 ``SAC`` model's actor, critic and target critic.

    The model is duck-typed so this module does not import Stable-Baselines3.
    Only the target critic's frozen status is asserted here: SB3 sets
    ``requires_grad=False`` on it, and a target that reports itself trainable
    would mean the algorithm was modified.
    """
    policy = getattr(model, "policy", None)
    if policy is None:
        raise TypeError("a SAC model with a .policy attribute is required")

    networks: list[NetworkArchitecture] = []
    notes: list[str] = []
    for attribute, label, optimiser_updated, rule in (
        ("actor", "actor", True, "optimiser"),
        ("critic", "critic", True, "optimiser"),
        ("critic_target", "critic_target", False, "polyak_average_of_critic"),
    ):
        module = getattr(policy, attribute, None)
        if module is None:
            notes.append(f"{attribute} is absent from the policy; it was not described")
            continue
        described = describe_module(module, identity=f"{identity_prefix}/{label}")
        networks.append(replace(described, optimiser_updated=optimiser_updated, update_rule=rule))

    target = next((net for net in networks if net.identity.endswith("critic_target")), None)
    critic = next((net for net in networks if net.identity.endswith("/critic")), None)
    if target is not None and critic is not None and target.total_parameters == critic.total_parameters:
        notes.append(
            "the target critic is a same-shape copy of the critic updated by Polyak averaging, "
            "not by the optimiser; it is excluded from optimiser_updated_parameters so the model "
            "size is not reported twice"
        )
    if target is not None and target.frozen_parameters > 0:
        notes.append(
            f"{target.frozen_parameters:,} target-critic parameter(s) carry "
            f"requires_grad=False in this library version"
        )

    entropy = getattr(model, "log_ent_coef", None)
    if entropy is not None and getattr(entropy, "requires_grad", False):
        count = int(entropy.numel())
        notes.append(
            f"the entropy coefficient is learned: {count} additional optimiser-updated scalar(s) "
            "outside the actor and critic, not included in the network totals above"
        )
    return ArchitectureReport(networks=tuple(networks), notes=tuple(notes))


def describe_ensemble(ensemble: Any, *, identity_prefix: str = "continuation") -> ArchitectureReport:
    """Describe every member of a continuation ensemble.

    Members share one architecture but are separately initialised and separately
    fitted, so the count is reported per member and summed rather than
    multiplied from one member and a declared count.
    """
    members = getattr(ensemble, "members", None)
    if members is None:
        raise TypeError("a ContinuationEnsemble with fitted members is required")
    networks = tuple(
        describe_module(member, identity=f"{identity_prefix}/member-{index}")
        for index, member in enumerate(members)
    )
    notes = (
        (
            f"the {len(networks)} members are averaged for the value and their spread is the "
            "reported disagreement; the spread is not a calibrated uncertainty"
        ),
    )
    return ArchitectureReport(networks=networks, notes=notes)
