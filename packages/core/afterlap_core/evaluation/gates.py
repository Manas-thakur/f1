"""Release-gate status, with certification made inexpressible.

``validation/TECHNICAL_SPEC.md``:

    Publish each gate's status with test IDs, run date, source revision and
    evidence path. Physics fidelity, numerical convergence and real-car
    validation are separate statuses. Passing simulated tests is not
    certification.

Three things follow, and all three are enforced by code rather than by prose:

* the three fidelity statuses are three separate records that cannot be
  collapsed into one;
* :class:`RealCarValidation` has exactly one reachable value —
  ``UNMEASURABLE_NO_REAL_CAR_DATA`` — because this package contains no real-car
  measurement and no argument from simulated results can produce one;
* any note or claim string containing a certification phrase is rejected by
  :class:`CertificationClaimError`, so the module has no way to say it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

__all__ = [
    "FORBIDDEN_CLAIM_PATTERNS",
    "CertificationClaimError",
    "FidelityStatus",
    "Gate",
    "GateEvidence",
    "GateReport",
    "GateStatus",
    "NumericalConvergence",
    "PhysicsFidelity",
    "RealCarValidation",
    "gate_descriptions",
]


class CertificationClaimError(ValueError):
    """Raised when a gate record tries to assert certification or real fidelity."""


FORBIDDEN_CLAIM_PATTERNS: tuple[str, ...] = (
    r"\bcertifi",
    r"\bfia[- ]approved\b",
    r"\bhomologat",
    r"\bvalidated against a real car\b",
    r"\breal[- ]car (fidelity|validated)\b",
    r"\bproven safe\b",
    r"\bguarantee[sd]?\b",
)
"""Phrases a gate record may not contain. Matched case-insensitively."""

_COMPILED = tuple(re.compile(pattern, re.IGNORECASE) for pattern in FORBIDDEN_CLAIM_PATTERNS)


def _reject_claims(text: str | None, where: str) -> None:
    if not text:
        return
    for pattern in _COMPILED:
        if pattern.search(text):
            raise CertificationClaimError(
                f"{where} contains the forbidden claim pattern {pattern.pattern!r}: {text!r}. "
                "Passing simulated tests is not certification."
            )


class Gate(StrEnum):
    """The release gates from ``program/EXECUTION_PLAN.md``."""

    G0 = "G0"
    G1 = "G1"
    G2 = "G2"
    G3 = "G3"
    G4 = "G4"
    G5 = "G5"
    G6 = "G6"
    G7 = "G7"
    G8 = "G8"


_DESCRIPTIONS: dict[Gate, str] = {
    Gate.G0: "schema compatibility and unit tests",
    Gate.G1: "physics convergence and no free energy",
    Gate.G2: "rule boundary cases with independent expected values",
    Gate.G3: "partial-observation isolation and estimation coverage",
    Gate.G4: "baseline constrained planning including timeout/expiry",
    Gate.G5: "human lifecycle and connected simulator display",
    Gate.G6: "branching determinism and reactive rivals",
    Gate.G7: "held-out model comparison including RL ablation",
    Gate.G8: "failure recovery, export reproducibility and honest presentation",
}


def gate_descriptions() -> dict[str, str]:
    return {gate.value: text for gate, text in _DESCRIPTIONS.items()}


class GateStatus(StrEnum):
    """A gate's state. There is no ``certified``."""

    PASSED = "passed"
    """Every declared test for this gate ran here and passed."""

    FAILED = "failed"
    NOT_RUN = "not_run"
    BLOCKED = "blocked"
    """A dependency is not merged, so the gate cannot be evaluated yet."""

    PARTIAL = "partial"
    """Some of the gate's evidence exists; the rest is named as missing."""


@dataclass(frozen=True, slots=True)
class GateEvidence:
    """One gate's status with everything needed to reproduce it."""

    gate: Gate
    status: GateStatus
    owner: str
    test_ids: tuple[str, ...] = ()
    run_date: datetime | None = None
    source_revision: str | None = None
    evidence_path: str | None = None
    missing: tuple[str, ...] = ()
    note: str | None = None

    def __post_init__(self) -> None:
        _reject_claims(self.note, f"gate {self.gate.value} note")
        if self.status is GateStatus.PASSED and not self.test_ids:
            raise ValueError(f"gate {self.gate.value} cannot pass without naming its test ids")
        if self.status is GateStatus.PASSED and self.evidence_path is None:
            raise ValueError(f"gate {self.gate.value} cannot pass without an evidence path")
        if self.status is GateStatus.PARTIAL and not self.missing:
            raise ValueError(f"gate {self.gate.value} is partial but names nothing missing")

    @property
    def description(self) -> str:
        return _DESCRIPTIONS[self.gate]

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate.value,
            "description": self.description,
            "status": self.status.value,
            "owner": self.owner,
            "test_ids": list(self.test_ids),
            "run_date": None if self.run_date is None else self.run_date.isoformat(),
            "source_revision": self.source_revision,
            "evidence_path": self.evidence_path,
            "missing": list(self.missing),
            "note": self.note,
        }


class FidelityStatus(StrEnum):
    """Values a fidelity statement may take. Deliberately not a gate status."""

    ESTABLISHED_IN_SIMULATION = "established_in_simulation"
    NOT_ESTABLISHED = "not_established"
    UNMEASURABLE_NO_REAL_CAR_DATA = "unmeasurable_no_real_car_data"


@dataclass(frozen=True, slots=True)
class PhysicsFidelity:
    """Whether the model reproduces its own stated reference equations.

    This is a *self-consistency* statement about a reduced model. It says
    nothing about any real vehicle, which is why real-car validation is a
    separate record that this one cannot influence.
    """

    status: FidelityStatus
    reference: str
    independent_checker: str
    residual_summary: str
    test_ids: tuple[str, ...] = ()
    note: str | None = None

    def __post_init__(self) -> None:
        _reject_claims(self.note, "physics fidelity note")
        _reject_claims(self.residual_summary, "physics fidelity residual summary")
        if self.status is FidelityStatus.UNMEASURABLE_NO_REAL_CAR_DATA:
            raise ValueError(
                "physics fidelity against the model's own equations is measurable here; "
                "the real-car status is a separate record"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "scope": "self-consistency of the reduced model against its stated reference equations",
            "reference": self.reference,
            "independent_checker": self.independent_checker,
            "residual_summary": self.residual_summary,
            "test_ids": list(self.test_ids),
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class NumericalConvergence:
    """Whether the integration resolution has been shown not to change results."""

    status: FidelityStatus
    resolutions: tuple[float, ...]
    quantity_summary: str
    ranking_stable: bool
    test_ids: tuple[str, ...] = ()
    note: str | None = None

    def __post_init__(self) -> None:
        _reject_claims(self.note, "numerical convergence note")
        if self.status is FidelityStatus.UNMEASURABLE_NO_REAL_CAR_DATA:
            raise ValueError("numerical convergence does not depend on real-car data")

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "resolutions_s": list(self.resolutions),
            "quantity_summary": self.quantity_summary,
            "ranking_stable": self.ranking_stable,
            "test_ids": list(self.test_ids),
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class RealCarValidation:
    """Real-car fidelity. Exactly one value is reachable.

    ``NUMERICS_AND_VALIDATION.md``: "A formal real-car fidelity claim requires
    real-car measurements unavailable in this package." There is therefore no
    constructor argument that can make this say anything else, and no amount of
    simulated evidence changes it.
    """

    measurements_available: bool = False
    note: str = (
        "No real-car measurement exists in this package. Every parameter is a synthetic "
        "assumption and no result here supports a claim about a real vehicle."
    )

    def __post_init__(self) -> None:
        _reject_claims(self.note, "real-car validation note")
        if self.measurements_available:
            raise CertificationClaimError(
                "this package contains no real-car measurements; a real-car fidelity status "
                "cannot be asserted from simulated results"
            )

    @property
    def status(self) -> FidelityStatus:
        return FidelityStatus.UNMEASURABLE_NO_REAL_CAR_DATA

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "measurements_available": False,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class GateReport:
    """Every gate status plus the three separate fidelity statements."""

    generated_at: datetime
    source_revision: str
    gates: tuple[GateEvidence, ...]
    physics_fidelity: PhysicsFidelity
    numerical_convergence: NumericalConvergence
    real_car_validation: RealCarValidation = field(default_factory=RealCarValidation)
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        seen = [evidence.gate for evidence in self.gates]
        if len(set(seen)) != len(seen):
            raise ValueError("each gate appears at most once in a gate report")
        for note in self.notes:
            _reject_claims(note, "gate report note")

    def status_of(self, gate: Gate) -> GateStatus:
        for evidence in self.gates:
            if evidence.gate is gate:
                return evidence.status
        return GateStatus.NOT_RUN

    @property
    def passed(self) -> tuple[Gate, ...]:
        return tuple(e.gate for e in self.gates if e.status is GateStatus.PASSED)

    @property
    def blocked(self) -> tuple[Gate, ...]:
        return tuple(e.gate for e in self.gates if e.status is GateStatus.BLOCKED)

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "source_revision": self.source_revision,
            "gates": [evidence.as_dict() for evidence in self.gates],
            "fidelity": {
                "physics": self.physics_fidelity.as_dict(),
                "numerical_convergence": self.numerical_convergence.as_dict(),
                "real_car_validation": self.real_car_validation.as_dict(),
            },
            "certification": "not_claimed",
            "scope": (
                "All statuses here describe behaviour inside this synthetic simulator. Passing "
                "simulated tests is not certification and no status in this document asserts one."
            ),
            "notes": list(self.notes),
        }


def build_gate_report(
    *,
    source_revision: str,
    generated_at: datetime,
    gates: Sequence[GateEvidence],
    physics_fidelity: PhysicsFidelity,
    numerical_convergence: NumericalConvergence,
    notes: Sequence[str] = (),
) -> GateReport:
    """Assemble a gate report. Every gate not supplied reads as ``not_run``."""
    return GateReport(
        generated_at=generated_at,
        source_revision=source_revision,
        gates=tuple(gates),
        physics_fidelity=physics_fidelity,
        numerical_convergence=numerical_convergence,
        notes=tuple(notes),
    )


__all__ += ["build_gate_report"]
