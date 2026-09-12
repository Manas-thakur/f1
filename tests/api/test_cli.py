from __future__ import annotations

import json

from typer.testing import CliRunner

from afterlap_api.cli import app, perform_in_process_request
from afterlap_api.deps import Settings
from afterlap_contracts import fixtures as fx


def test_version_command_prints_contract_revision():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "schema_version" in payload
    assert "contract_revision" in payload
    assert payload["runtime_url"] == "http://127.0.0.1:8000"


def test_in_process_liveness_matches_the_contract(tmp_path):
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'cli.sqlite3').as_posix()}",
        artifact_root=tmp_path,
    )
    result = perform_in_process_request("GET", "/api/v1/health/live", settings=settings)
    assert result["status"] == 200
    assert result["body"]["status"] == "live"
    assert result["headers"]["x-request-id"].startswith("req-")


def test_in_process_missing_session_is_a_typed_error(tmp_path):
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'cli.sqlite3').as_posix()}",
        artifact_root=tmp_path,
    )
    result = perform_in_process_request(
        "GET", f"/api/v1/sessions/{fx.FIXTURE_SESSION_ID}/snapshot", settings=settings
    )
    assert result["status"] == 404
    error = result["body"]["error"]
    assert error["code"] == "not_found"
    assert "traceback" not in json.dumps(result["body"]).lower()


def test_production_refuses_a_self_asserted_operator_identity():
    import pytest

    from afterlap_api.call import Headers
    from afterlap_api.deps import operator_from_headers
    from afterlap_api.errors import CapabilityUnavailable

    with pytest.raises(CapabilityUnavailable):
        operator_from_headers(Settings(development_mode=False), Headers({"X-Operator-Id": "admin"}))


def test_idempotency_header_requires_a_bounded_visible_token():
    import pytest

    from afterlap_api.call import Headers
    from afterlap_api.db import LifecycleError
    from afterlap_api.deps import require_idempotency

    for key in ["", " ", "a" * 129, "a\nvalue", "\u03b1"]:
        with pytest.raises(LifecycleError):
            require_idempotency(Headers({"Idempotency-Key": key}))
    assert require_idempotency(Headers({"Idempotency-Key": "a" * 128})) == "a" * 128
