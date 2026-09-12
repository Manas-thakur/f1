"""Base model configuration and version negotiation for contract revision 1.

Every wire object is immutable and rejects unexpected fields. A renamed unit or
changed meaning increments the major version; additive optional fields increment
the minor version only after generated-client tests pass.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION: Final = "1.0"
"""Wire envelope schema version (DOMAIN_MODEL.md, "Version negotiation")."""

CONTRACT_REVISION: Final[int] = 1
"""Coordinator-controlled contract revision. Workers may not increment this."""

SchemaVersion = Literal["1.0"]

CONTENT_HASH_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"
"""Shape of every digest on the wire: the algorithm, then its lowercase hex.

``min_length=1`` accepted ``sha256:``, a truncated digest, an uppercase one and
a digest from a different algorithm. Two of those compare unequal to the value
that produced them, so a mismatched artefact would have been reported as a
changed artefact. The prefix is part of the value because a bare digest cannot
say which algorithm produced it.
"""

ContentHash = Annotated[str, Field(min_length=71, max_length=71, pattern=CONTENT_HASH_PATTERN)]
"""A ``sha256:<64 lowercase hex>`` digest."""

HEX_DIGEST_PATTERN: Final = r"^[0-9a-f]{64}$"
"""Shape of a digest that is written without its algorithm: bare lowercase hex.

Two things on this wire record a digest of a *file*: a compiled track or event
package, which writes its own hash into itself, and a cached source document,
whose hash names the directory it is stored under. Neither can gain the
``sha256:`` prefix without invalidating every artefact already on disk, so they
keep the bare encoding and say so in the type. Everything else uses
:data:`ContentHash`; the two are distinct types precisely so a reader can see
which encoding a field carries instead of discovering it from a failed
comparison.
"""

HexDigest = Annotated[str, Field(min_length=64, max_length=64, pattern=HEX_DIGEST_PATTERN)]
"""A bare ``<64 lowercase hex>`` digest of a stored file."""


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
    "CONTENT_HASH_PATTERN",
    "CONTRACT_REVISION",
    "HEX_DIGEST_PATTERN",
    "SCHEMA_VERSION",
    "ContentHash",
    "Contract",
    "HexDigest",
    "SchemaVersion",
    "VersionedContract",
    "content_hash_of",
]
