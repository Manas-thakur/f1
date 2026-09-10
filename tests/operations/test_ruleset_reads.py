"""`GET /rulesets/{id}` has to answer for the packs this build ships.

Nothing in the product ever wrote a row to ``rule_manifest``, so the route
answered 404 for every id on a real runtime, including the pack the shipped
demo creates its session from. Three surfaces broke on that one gap: the
laboratory's create-session form validates the rule pack id before it will
enable the button, so **no session could be created from the browser at all**;
the workspace rail's "Rules" entry always landed on an error state; and a
decision's ruleset hash could not be resolved to the pack it named.

`contracts/API.md` describes the route as returning the "immutable source
manifest and supported checks" — a property of the pack, not of whether some
session happens to have used it yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from afterlap_api.client import TestClient
from afterlap_api.deps import Settings
from afterlap_api.main import create_app

from .conftest import RULE_PACK_ID, SCENARIO_ID, SEED

if TYPE_CHECKING:
    from pathlib import Path

OPERATOR = "console-operator"


def _settings(root: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+pysqlite:///{(root / 'afterlap.sqlite3').as_posix()}",
        artifact_root=root,
        session_runtime_backend="in_process",
    )


def test_a_shipped_pack_reads_before_any_session_has_used_it(tmp_path: Path):
    """The laboratory validates this id before it can create the first session."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get(f"/api/v1/rulesets/{RULE_PACK_ID}")

    assert response.status_code == 200, (
        f"the pack the shipped scenario runs on is unreadable, so the browser cannot "
        f"create a session: {response.text}"
    )
    manifest = response.json()["manifest"]
    assert manifest["ruleset_id"] == RULE_PACK_ID
    assert manifest["synthetic"] is True, "a shipped pack must still declare itself synthetic"


def test_an_unknown_pack_is_still_refused_with_what_is_available(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/v1/rulesets/current")

    assert response.status_code == 404, response.text
    error = response.json()["error"]
    assert "current" in error["message"]
    assert error["details"]["available"], "a refusal should name the packs that do resolve"


TRAVERSAL_IDS = [
    "../../../pyproject",
    "..%2F..%2Fpyproject",
    "%2e%2e%2f%2e%2e%2fpyproject",
    "synthetic-pack-v1/../../../pyproject",
    "/etc/passwd",
    "synthetic-pack-v1.yaml",
    "..%2Frules%2Fsynthetic-pack-v1",
    "%2e%2e%2frules%2fsynthetic-pack-v1",
    "..%5Crules%5Csynthetic-pack-v1",
]
"""Ids that name a path rather than a pack.

The last three are the discriminating ones: they resolve to a real, valid rule
pack file when the id is concatenated into a path, so a resolver that reaches
the loader before checking the listing answers 200 for them.
"""


@pytest.mark.parametrize("requested", TRAVERSAL_IDS)
def test_a_pack_id_never_names_a_file_outside_the_rules_directory(tmp_path: Path, requested: str):
    """The id is concatenated into a path, so it may only come from the listing.

    Nothing here should reach the loader at all: an id that is not one of the
    enumerated packs can only fail to match. The assertion is on the status
    rather than the body, because a traversal that produced a 500 would be as
    much of a finding as one that produced a 200.
    """
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get(f"/api/v1/rulesets/{requested}")

    assert response.status_code in {404, 405}, (
        f"a pack id of {requested!r} was resolved to something: {response.status_code} {response.text[:200]}"
    )


def test_a_session_pins_its_pack_so_the_hash_resolves(tmp_path: Path):
    """A decision names a ruleset hash; that hash has to resolve to a document."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/sessions",
            json={
                "mode": "simulation",
                "scenario_id": SCENARIO_ID,
                "ruleset_id": RULE_PACK_ID,
                "seed": SEED,
                "label": "ruleset pin drill",
            },
            headers={"Idempotency-Key": "pin-create", "X-Operator-Id": OPERATOR},
        )
        assert created.status_code == 201, created.text
        ruleset_hash = created.json()["snapshot"]["manifest"]["ruleset_hash"]

        by_hash = client.get(f"/api/v1/rulesets/{ruleset_hash}")

    assert by_hash.status_code == 200, f"the hash this session pinned resolves to nothing: {by_hash.text}"
    assert by_hash.json()["manifest"]["ruleset_id"] == RULE_PACK_ID
