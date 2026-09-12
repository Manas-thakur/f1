"""Base model configuration and version negotiation for contract revision 1.

Every wire object is immutable and rejects unexpected fields. A renamed unit or
changed meaning increments the major version; additive optional fields increment
the minor version only after generated-client tests pass.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION: Final = "1.0"
"""Wire envelope schema version (DOMAIN_MODEL.md, "Version negotiation")."""

CONTRACT_REVISION: Final[int] = 1
"""Coordinator-controlled contract revision. Workers may not increment this."""

SchemaVersion = Literal["1.0"]


class Contract(BaseModel):
    """Immutable, strictly-validated wire record.

    ``extra="forbid"`` implements the "reject unexpected fields at service
    boundaries" rule: an unknown required field fails closed rather than being
    silently dropped.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
        use_enum_values=False,
        ser_json_inf_nan="strings",
    )

    def canonical_json(self) -> str:
        """Deterministic JSON used for hashing and idempotency body comparison."""
        payload = self.model_dump(mode="json")
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def content_hash(self) -> str:
        """SHA-256 of the canonical JSON, prefixed with its algorithm."""
        digest = hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def revise(self, **changes: Any) -> Self:
        """Return a new record with ``changes`` applied.

        State transitions create new revisions; they never mutate a stored one.
        """
        return self.model_copy(update=changes, deep=False).model_validate(
            {**self.model_dump(mode="python"), **changes}
        )


class VersionedContract(Contract):
    """Wire record that carries its own schema version.

    The field is required, not defaulted: the normative telemetry schema lists
    it under ``required``, and a payload that omits its version is a payload of
    unknown version. Construct with ``schema_version=SCHEMA_VERSION``.
    """

    schema_version: SchemaVersion


def content_hash_of(payload: Any) -> str:
    """SHA-256 of an arbitrary JSON-serialisable payload, deterministically ordered."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


__all__ = [
    "CONTRACT_REVISION",
    "SCHEMA_VERSION",
    "Contract",
    "SchemaVersion",
    "VersionedContract",
    "content_hash_of",
]
