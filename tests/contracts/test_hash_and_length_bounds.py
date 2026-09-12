"""Every digest and every free string on the wire declares its shape.

These are regression tests for a class of defect the contracts could not
express before: a field typed ``str = Field(min_length=1)`` accepted
``"sha256:"``, a truncated digest, an uppercase one, a digest from another
algorithm, and a megabyte of text. Two of those compare unequal to the value
that produced them, so a matching artefact would have been reported as a
changed artefact and a changed one could slip through a prefix comparison.

The suite is deliberately schema-driven rather than a list of field names: a
field added later inherits the rule instead of escaping it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from afterlap_contracts import (
    CONTENT_HASH_PATTERN,
    HEX_DIGEST_PATTERN,
    ExperimentJob,
    ExperimentManifest,
    JobStatus,
    ModelManifest,
    SessionManifest,
    SnapshotReference,
    fixtures as fx,
)

GENERATED = Path(__file__).resolve().parents[2] / "packages" / "contracts" / "generated"

VALID = "sha256:" + "ab" * 32
VALID_PACKAGE = "ab" * 32

MALFORMED_CONTENT_HASHES = [
    "",
    "sha256:",
    "sha256:" + "ab" * 31,
    "sha256:" + "ab" * 33,
    "sha256:" + "AB" * 32,
    "sha512:" + "ab" * 32,
    "ab" * 32,
    "sha256:" + "zz" * 32,
    "sha256:" + "ab" * 32 + " x",
]

MALFORMED_PACKAGE_DIGESTS = ["", "ab" * 31, "ab" * 33, "AB" * 32, "sha256:" + "ab" * 32, "zz" * 32]


def _walk(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Resolve one property schema through $ref, anyOf and additionalProperties."""
    node = schema
    for _ in range(6):
        ref = node.get("$ref")
        if isinstance(ref, str) and "/" in ref:
            node = defs.get(ref.rsplit("/", 1)[1], {})
            continue
        options = node.get("anyOf") or node.get("oneOf")
        if isinstance(options, list):
            concrete = [item for item in options if item.get("type") != "null"]
            if len(concrete) == 1:
                node = concrete[0]
                continue
        extra = node.get("additionalProperties")
        if node.get("type") == "object" and isinstance(extra, dict):
            node = extra
            continue
        items = node.get("items")
        if node.get("type") == "array" and isinstance(items, dict):
            node = items
            continue
        break
    return node


def _definitions() -> dict[str, Any]:
    bundle = json.loads((GENERATED / "schemas.json").read_text(encoding="utf-8"))
    definitions = bundle["definitions"]
    assert isinstance(definitions, dict) and definitions
    return definitions


def _hash_properties() -> list[tuple[str, str, dict[str, Any]]]:
    definitions = _definitions()
    found: list[tuple[str, str, dict[str, Any]]] = []
    for model, schema in sorted(definitions.items()):
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            continue
        for name, definition in sorted(properties.items()):
            if not name.endswith(("_hash", "_hashes", "sha256")) or not isinstance(definition, dict):
                continue
            found.append((model, name, _walk(definition, definitions)))
    return found


def test_the_generated_schema_has_hash_fields_to_check() -> None:
    assert len(_hash_properties()) >= 25


@pytest.mark.parametrize(
    ("model", "field", "node"),
    _hash_properties(),
    ids=[f"{model}.{field}" for model, field, _ in _hash_properties()],
)
def test_every_generated_hash_field_declares_a_digest_pattern(model, field, node) -> None:
    """A new ``*_hash`` field cannot ship as an unconstrained string."""
    pattern = node.get("pattern")
    assert pattern in {CONTENT_HASH_PATTERN, HEX_DIGEST_PATTERN}, (
        f"{model}.{field} declares pattern {pattern!r}; a digest field must declare one of "
        f"{CONTENT_HASH_PATTERN!r} (prefixed) or {HEX_DIGEST_PATTERN!r} (bare package digest)"
    )
    assert node.get("minLength") == node.get("maxLength"), (
        f"{model}.{field} does not pin its length; a digest has exactly one length"
    )


@pytest.mark.parametrize("value", MALFORMED_CONTENT_HASHES)
def test_a_session_manifest_refuses_a_malformed_content_hash(value) -> None:
    payload = fx.session_manifest().model_dump(mode="python")
    payload["ruleset_hash"] = value
    with pytest.raises(ValidationError):
        SessionManifest.model_validate(payload)


@pytest.mark.parametrize("value", MALFORMED_CONTENT_HASHES)
def test_a_snapshot_reference_refuses_a_malformed_content_hash(value) -> None:
    with pytest.raises(ValidationError):
        SnapshotReference(
            snapshot_id="snap-1",
            session_id="ses-1",
            snapshot_hash=value,
            session_time_s=1.0,
            created_at=datetime.now(UTC),
        )


@pytest.mark.parametrize("value", MALFORMED_PACKAGE_DIGESTS)
def test_a_session_manifest_refuses_a_malformed_package_digest(value) -> None:
    payload = fx.session_manifest().model_dump(mode="python")
    payload["track_package_hash"] = value
    with pytest.raises(ValidationError):
        SessionManifest.model_validate(payload)


def test_the_two_digest_encodings_do_not_accept_each_other() -> None:
    """A package digest is not a content hash and the reverse is also refused."""
    payload = fx.session_manifest().model_dump(mode="python")
    payload["track_package_hash"] = VALID
    with pytest.raises(ValidationError):
        SessionManifest.model_validate(payload)

    payload = fx.session_manifest().model_dump(mode="python")
    payload["track_hash"] = VALID_PACKAGE
    with pytest.raises(ValidationError):
        SessionManifest.model_validate(payload)


def _experiment_manifest(**changes: Any) -> ExperimentManifest:
    fields: dict[str, Any] = {
        "schema_version": "1.0",
        "id": "exp-1",
        "snapshot_hash": VALID,
        "treatment_ids": ("reference", "candidate"),
        "controller_ids": ("legal_fixed_schedule", "legal_greedy_attacker"),
        "disturbance_seed_ids": (42,),
        "evaluator_version": "eval-1",
        "metrics_version": "metrics-v1",
        "evaluation_horizon_s": 1.0,
        "created_at": datetime.now(UTC),
    }
    fields.update(changes)
    return ExperimentManifest(**fields)


@pytest.mark.parametrize("value", MALFORMED_CONTENT_HASHES)
def test_an_experiment_manifest_refuses_a_malformed_snapshot_hash(value) -> None:
    with pytest.raises(ValidationError):
        _experiment_manifest(snapshot_hash=value)


def test_an_experiment_manifest_accepts_a_well_formed_snapshot_hash() -> None:
    assert _experiment_manifest().snapshot_hash == VALID


@pytest.mark.parametrize("value", MALFORMED_CONTENT_HASHES)
def test_an_experiment_job_refuses_a_malformed_manifest_hash(value) -> None:
    with pytest.raises(ValidationError):
        ExperimentJob(
            schema_version="1.0",
            id="job-1",
            manifest_hash=value,
            status=JobStatus.QUEUED,
            created_at=datetime.now(UTC),
        )


def _model_manifest(**changes: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "schema_version": "1.0",
        "id": "bounds-bundle",
        "algorithm": "SAC",
        "weights_hash": VALID,
        "feature_schema_hash": VALID,
        "rule_family": "synthetic-pack-v1",
        "reward_revision": "objective-v1",
        "created_at": datetime.now(UTC),
    }
    fields.update(changes)
    return fields


def test_a_model_manifest_refuses_a_prefixed_track_package_digest() -> None:
    """``track_package_hashes`` is compared against the package's own bare digest."""
    with pytest.raises(ValidationError):
        ModelManifest.model_validate(_model_manifest(track_package_hashes={"monza": VALID}))
    accepted = ModelManifest.model_validate(_model_manifest(track_package_hashes={"monza": VALID_PACKAGE}))
    assert accepted.track_package_hashes == {"monza": VALID_PACKAGE}


def _string_properties(models: set[str] | None = None) -> list[tuple[str, str, dict[str, Any]]]:
    definitions = _definitions()
    found: list[tuple[str, str, dict[str, Any]]] = []
    for model, schema in sorted(definitions.items()):
        if models is not None and model not in models:
            continue
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            continue
        for name, definition in sorted(properties.items()):
            if not isinstance(definition, dict):
                continue
            node = _walk(definition, definitions)
            if node.get("type") == "string" and "enum" not in node and "format" not in node:
                found.append((model, name, node))
    return found


def _request_models() -> set[str]:
    """Every contract a client may POST, by generated schema name."""
    import afterlap_contracts.requests as module

    return {
        name
        for name in dir(module)
        if isinstance(getattr(module, name), type)
        and issubclass(getattr(module, name), module.RequestContract)
        and getattr(module, name) is not module.RequestContract
    }


def test_there_are_request_contracts_to_check() -> None:
    assert len(_request_models()) >= 8


def test_every_string_a_client_can_send_is_bounded() -> None:
    """A request body is the attack surface; nothing in one may be unbounded.

    ``Contract`` refuses unknown fields, but a known field typed ``str`` with
    no ``max_length`` accepts as much text as the 64 KiB body cap allows, and
    that text reaches a database column, an export and the console's layout.
    """
    unbounded = [
        f"{model}.{field}"
        for model, field, node in _string_properties(_request_models())
        if node.get("maxLength") is None and node.get("pattern") is None
    ]
    assert unbounded == [], f"unbounded strings on request contracts: {sorted(unbounded)}"


UNBOUNDED_RESPONSE_STRINGS = 199
"""How many server-generated strings still declare neither a length nor a shape.

These are produced by the server rather than accepted from a client, so they
are a rendering and storage concern rather than an input-validation one. The
number is pinned so the set cannot grow unnoticed; lowering it is the direction
of travel and lowering the constant with it is part of that work.
"""


def test_the_unbounded_response_string_count_does_not_grow() -> None:
    unbounded = sorted(
        f"{model}.{field}"
        for model, field, node in _string_properties()
        if node.get("maxLength") is None and node.get("pattern") is None
    )
    assert len(unbounded) <= UNBOUNDED_RESPONSE_STRINGS, (
        f"{len(unbounded)} unbounded wire strings, up from {UNBOUNDED_RESPONSE_STRINGS}. "
        f"Give the new field a maxLength or a pattern. All: {unbounded}"
    )
