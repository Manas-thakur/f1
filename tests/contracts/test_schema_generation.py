"""Generated artefacts must match the models exactly.

CI fails on drift so a hand-edited generated file is a build error rather than
a silent divergence between Python and TypeScript.
"""

from __future__ import annotations

import json

import pytest

from afterlap_contracts import SCHEMA_VERSION
from afterlap_contracts.schema_export import (
    EXPORTED_MODELS,
    build_bundle,
    build_json_schemas,
    build_typescript,
    check_drift,
    default_output_dir,
)


def test_generated_files_are_current():
    problems = check_drift()
    assert problems == [], (
        "generated contracts are stale; run "
        "`python -m afterlap_contracts.schema_export` and commit the result: " + "; ".join(problems)
    )


def test_every_exported_model_appears_in_the_bundle():
    bundle = build_bundle()
    assert bundle["schema_version"] == SCHEMA_VERSION
    exported = {m.__name__ for m in EXPORTED_MODELS}
    assert set(bundle["models"]) == exported
    assert set(bundle["definitions"]) == exported


def test_every_wire_model_forbids_unknown_fields():
    for model in EXPORTED_MODELS:
        schema = model.model_json_schema(mode="serialization")
        assert schema.get("additionalProperties") is False, (
            f"{model.__name__} accepts unexpected fields; boundaries must fail closed"
        )


def test_versioned_models_require_their_schema_version():
    from afterlap_contracts.base import VersionedContract

    for model in EXPORTED_MODELS:
        if not issubclass(model, VersionedContract):
            continue
        schema = model.model_json_schema(mode="serialization")
        assert "schema_version" in schema.get("required", ()), (
            f"{model.__name__} must transport its schema version"
        )


def test_typescript_declares_every_model():
    text = build_typescript()
    assert 'export const SCHEMA_VERSION = "1.0" as const;' in text
    for model in EXPORTED_MODELS:
        name = model.__name__
        assert f"export interface {name} " in text or f"export type {name} =" in text, name


def test_typescript_has_no_unresolved_placeholder_types():
    text = build_typescript()
    suspicious = [line for line in text.splitlines() if ": unknown;" in line]
    assert suspicious == [], f"unresolved TypeScript types: {suspicious[:5]}"


def test_schema_bundle_is_valid_json_and_stable():
    first = json.dumps(build_json_schemas(), sort_keys=True)
    second = json.dumps(build_json_schemas(), sort_keys=True)
    assert first == second, "schema generation must be deterministic"


@pytest.mark.parametrize("filename", ["schemas.json", "contracts.ts"])
def test_generated_artifacts_exist_on_disk(filename):
    path = default_output_dir() / filename
    assert path.exists(), f"{path} must be committed so the web build can consume it"
    assert path.stat().st_size > 0
