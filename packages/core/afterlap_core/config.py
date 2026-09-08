"""Configuration loading with mandatory units, provenance and bounds.

Every configured physical parameter carries units, a source and a verification
status. A synthetic configuration makes the software executable; it never
establishes realism, and the loader keeps that distinction machine-readable.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .paths import Paths, sha256_json


class VerificationStatus(StrEnum):
    """How much confidence a configured parameter has earned."""

    SYNTHETIC_ASSUMPTION = "synthetic_assumption"
    LITERATURE_DERIVED = "literature_derived"
    CALIBRATED_ON_SYNTHETIC = "calibrated_on_synthetic"
    MEASURED = "measured"


class Parameter(BaseModel):
    """One physical parameter with the provenance the plan demands."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float
    unit: str = Field(min_length=1)
    source: str = Field(min_length=1)
    verification: VerificationStatus = VerificationStatus.SYNTHETIC_ASSUMPTION
    lower_bound: float | None = None
    upper_bound: float | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _within_declared_bounds(self) -> Parameter:
        if self.lower_bound is not None and self.value < self.lower_bound:
            raise ValueError(f"value {self.value} below declared lower bound {self.lower_bound}")
        if self.upper_bound is not None and self.value > self.upper_bound:
            raise ValueError(f"value {self.value} above declared upper bound {self.upper_bound}")
        return self

    @property
    def is_measured(self) -> bool:
        return self.verification is VerificationStatus.MEASURED


class ConfigDocument(BaseModel):
    """Base class for a loadable YAML configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    synthetic: bool = True
    description: str | None = None

    @property
    def config_hash(self) -> str:
        return sha256_json(self.model_dump(mode="json"))


def load_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML document, failing loudly on anything that is not a mapping."""
    if not path.exists():
        raise FileNotFoundError(f"configuration {path} does not exist")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"configuration {path} must contain a mapping at the top level")
    return payload


def config_dir(kind: str, paths: Paths | None = None) -> Path:
    base = (paths or Paths.default()).configs / kind
    if not base.is_dir():
        raise FileNotFoundError(f"configuration directory {base} does not exist")
    return base


def list_configs(kind: str, paths: Paths | None = None) -> tuple[str, ...]:
    return tuple(sorted(p.stem for p in config_dir(kind, paths).glob("*.yaml")))


def load_config(kind: str, config_id: str, paths: Paths | None = None) -> dict[str, Any]:
    return load_yaml(config_dir(kind, paths) / f"{config_id}.yaml")


__all__ = [
    "ConfigDocument",
    "Parameter",
    "VerificationStatus",
    "config_dir",
    "list_configs",
    "load_config",
    "load_yaml",
]
