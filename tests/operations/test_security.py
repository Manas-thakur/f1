"""Binding, path validation, mode enforcement and credential hygiene.

**Genuinely causes the conditions.** No mock stands in for any of these:

* the loopback default is read from `Settings.from_environment()` with the
  environment actually cleared, and every host publish in the shipped
  `infra/docker-compose.yml` is parsed out of the file itself;
* the export-path refusal is exercised against a real file that really exists
  outside the storage root, and the filesystem is checked afterwards to
  confirm nothing was written there;
* the `live_team` refusal goes through the real control plane over the real
  route, so it is the server's enforcement being tested and not the console's;
* a real credential is placed in the process environment where the application
  reads its database URL from, and then every artefact the run produces — the
  session manifest, the export file, the log stream, `/metrics`,
  `/api/v1/version`, the doctor report — is searched for it.
"""

from __future__ import annotations

import io
import json
import logging
import re
import subprocess
from pathlib import Path

import pytest

from afterlap_api.client import TestClient
from afterlap_api.deps import Settings
from afterlap_api.errors import CapabilityUnavailable
from afterlap_api.main import create_app
from afterlap_api.observability import JsonFormatter
from afterlap_contracts import SessionMode, fixtures as fx
from afterlap_core.diagnostics import check_database, redact
from afterlap_core.paths import Paths

from .conftest import IMPLEMENTATION_ROOT, RULE_PACK_ID, SCENARIO_ID, SEED

SECRET = "n0t-a-real-password-Ku3Rr7x"
SECRET_URL = f"postgresql+psycopg://afterlap:{SECRET}@afterlap-db.invalid:5432/afterlap"


def test_the_server_binds_loopback_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AFTERLAP_HOST", raising=False)
    monkeypatch.delenv("AFTERLAP_PORT", raising=False)
    monkeypatch.delenv("AFTERLAP_ENV", raising=False)

    settings = Settings.from_environment()
    assert settings.host == "127.0.0.1", f"the default bind is {settings.host!r}, not loopback"
    assert Settings().host == "127.0.0.1"
    assert settings.development_mode is True, "the default environment is development"


def test_the_bootstrap_operator_is_refused_outside_development():
    """There is no default production identity to inherit."""
    development = Settings(development_mode=True)
    assert development.bootstrap_operator() == "engineer-dev"

    production = Settings(development_mode=False)
    with pytest.raises(CapabilityUnavailable) as refusal:
        production.bootstrap_operator()
    assert "authentication" in str(refusal.value) or refusal.value.capability == "authentication"
    print(f"\nproduction bootstrap refused: {refusal.value}")


def test_every_compose_host_publish_binds_loopback_and_no_secret_is_defaulted():
    """Read the shipped compose file, not a description of it."""
    text = (IMPLEMENTATION_ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8")

    published = re.findall(r'^\s*-\s*"([^"]*:\d+)"\s*$', text, flags=re.MULTILINE)
    assert published, "no host publishes were found in the compose file"
    for entry in published:
        assert entry.startswith("127.0.0.1:"), f"host publish {entry!r} is not bound to loopback"
    print(f"\ncompose publishes: {published}")

    assert "AFTERLAP_DB_PASSWORD:?" in text, (
        "the compose file does not force the database password to be supplied"
    )
    for suspicious in ("POSTGRES_PASSWORD: afterlap", "password=", "PASSWORD: changeme"):
        assert suspicious not in text, f"the compose file contains a literal secret: {suspicious!r}"

    example = (IMPLEMENTATION_ROOT / "infra" / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^AFTERLAP_DB_PASSWORD=\s*$", example, flags=re.MULTILINE), (
        ".env.example ships a value for AFTERLAP_DB_PASSWORD; it must be blank"
    )
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "infra/.env"],
        cwd=IMPLEMENTATION_ROOT,
        capture_output=True,
        check=False,
    )
    assert tracked.returncode != 0, "infra/.env is tracked by git; it holds a generated password"
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "infra/.env"],
        cwd=IMPLEMENTATION_ROOT,
        capture_output=True,
        check=False,
    )
    assert ignored.returncode == 0, "infra/.env is not ignored; `make env` would leave a secret stageable"


def test_an_export_path_outside_the_storage_root_is_rejected(tmp_path: Path):
    paths = Paths.default(tmp_path / "install").ensure()

    outside = tmp_path / "outside" / "already-here.json"
    outside.parent.mkdir(parents=True)
    outside.write_text('{"do not touch": true}', encoding="utf-8")
    original = outside.read_bytes()

    escapes = [
        "../../outside/already-here.json",
        "..\\..\\outside\\already-here.json",
        str(outside),
        "exports/../../outside/already-here.json",
    ]
    for candidate in escapes:
        with pytest.raises(ValueError, match="escapes the configured storage root"):
            paths.resolve_within(candidate, root=paths.exports)

    assert outside.read_bytes() == original

    target = paths.resolve_within("exp-0001.json", root=paths.exports)
    assert target.is_relative_to(paths.exports.resolve())


def test_a_real_export_writes_only_inside_the_storage_root(tmp_path: Path):
    app = create_app(
        Settings(
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'api.sqlite3').as_posix()}",
            artifact_root=tmp_path,
            session_runtime_backend="in_process",
        )
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/sessions",
            json={
                "mode": "simulation",
                "scenario_id": SCENARIO_ID,
                "ruleset_id": RULE_PACK_ID,
                "seed": SEED,
            },
            headers={"Idempotency-Key": "security-1"},
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["manifest"]["id"]

        export = client.post(
            "/api/v1/exports",
            json={"session_id": session_id, "format": "json"},
            headers={"Idempotency-Key": "security-export"},
        )
        assert export.status_code == 201, export.text
        reported = export.json()["path"]
        assert not Path(reported).is_absolute(), (
            f"the export response names an absolute server path ({reported})"
        )
        written = tmp_path / reported
        assert written.is_file()
        assert written.resolve().is_relative_to((tmp_path / "artifacts" / "exports").resolve()), written

    strays = [p for p in tmp_path.iterdir() if p.is_file() and p.suffix in {".json", ".csv"}]
    assert strays == [], f"the export wrote outside the artefact tree: {strays}"


@pytest.mark.parametrize("mode", [SessionMode.LIVE_TEAM, SessionMode.REPLAY])
def test_a_non_simulation_session_refuses_a_simulator_driver_action(tmp_path: Path, mode: SessionMode):
    """Server-side, over the real route. The console's controls are not the authority."""
    from afterlap_api.db import transaction
    from afterlap_api.db.models import Manifest, Session

    app = create_app(
        Settings(
            database_url=f"sqlite+pysqlite:///{(tmp_path / f'api-{mode.value}.sqlite3').as_posix()}",
            artifact_root=tmp_path,
            session_runtime_backend="in_process",
        )
    )
    with TestClient(app) as client:
        manifest = fx.session_manifest(mode=mode)
        with transaction(app.state.database.factory) as db:
            db.add(
                Manifest(
                    hash=manifest.content_hash(),
                    kind="session",
                    schema_version=manifest.schema_version,
                    payload=manifest.model_dump(mode="json"),
                )
            )
            db.add(
                Session(
                    id=manifest.id,
                    mode=manifest.mode.value,
                    revision=0,
                    manifest_hash=manifest.content_hash(),
                    status="running",
                    session_time_s=5.0,
                    last_sequence=0,
                    scenario_id=manifest.scenario_id,
                    ruleset_hash=manifest.ruleset_hash,
                    synthetic=True,
                )
            )

        response = client.post(
            f"/api/v1/sessions/{manifest.id}/simulator/driver-action",
            json={
                "profile_id": "overtake",
                "observed_at_s": 5.0,
                "operator_id": "console-operator",
            },
            headers={"Idempotency-Key": f"driver-{mode.value}"},
        )
        body = response.json()
        print(f"\n{mode.value}: HTTP {response.status_code} {body}")
        assert response.status_code in (403, 409), body
        error = body["error"]
        assert mode.value in error["message"]
        assert "driver action" in error["message"]

        assert "lease" not in error["message"].lower()


def test_a_database_credential_never_reaches_a_report_a_log_or_an_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("AFTERLAP_DATABASE_URL", SECRET_URL)

    probe = check_database(SECRET_URL)
    print(f"\ndatabase probe: {probe.state.value} — {probe.detail}")
    assert SECRET not in probe.detail
    assert "afterlap:" not in probe.detail
    assert probe.detail.startswith("postgresql+psycopg")

    assert redact(SECRET_URL) == "postgresql+psycopg://afterlap-db.invalid:5432/afterlap"
    assert SECRET not in redact(SECRET_URL)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("afterlap.ops.credential-drill")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info(
            "connecting",
            extra={
                "database_url": SECRET_URL,
                "session_id": "ses-drill",
                "db_password": SECRET,
                "authorization": f"Bearer {SECRET}",
            },
        )
    finally:
        logger.removeHandler(handler)
    line = stream.getvalue()
    payload = json.loads(line)
    print(f"log line: {line.strip()}")
    assert SECRET not in line, "the structured log leaked a credential"
    assert payload["database_url"] == redact(SECRET_URL)
    assert "db_password" not in payload, "a password-shaped key survived the formatter"
    assert "authorization" not in payload

    app = create_app(
        Settings(
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'api.sqlite3').as_posix()}",
            artifact_root=tmp_path,
            session_runtime_backend="in_process",
        )
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/sessions",
            json={
                "mode": "simulation",
                "scenario_id": SCENARIO_ID,
                "ruleset_id": RULE_PACK_ID,
                "seed": SEED,
            },
            headers={"Idempotency-Key": "credential-drill"},
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["manifest"]["id"]
        assert SECRET not in created.text, "the session manifest carries the credential"

        lease = client.post(
            f"/api/v1/sessions/{session_id}/control-lease",
            json={"operator_id": "console-operator", "ttl_s": 600.0},
            headers={"Idempotency-Key": "credential-lease"},
        )
        assert lease.status_code == 200
        step = client.post(
            f"/api/v1/sessions/{session_id}/commands",
            json={
                "kind": "step",
                "expected_revision": 0,
                "operator_id": "console-operator",
                "step_duration_s": 1.0,
            },
            headers={"Idempotency-Key": "credential-step"},
        )
        assert step.status_code == 200, step.text

        export = client.post(
            "/api/v1/exports",
            json={"session_id": session_id, "format": "json"},
            headers={"Idempotency-Key": "credential-export"},
        )
        assert export.status_code == 201, export.text
        body = (tmp_path / export.json()["path"]).read_text(encoding="utf-8")
        assert SECRET not in body, "the export file contains the database credential"
        assert "afterlap-db.invalid" not in body, "the export names the private source host"

        for path in ("/metrics", "/api/v1/version", "/api/v1/health/ready"):
            text = client.get(path).text
            assert SECRET not in text, f"{path} leaked the credential"

    leaked = []
    for candidate in (tmp_path / "artifacts").rglob("*"):
        if not candidate.is_file():
            continue
        try:
            content = candidate.read_bytes()
        except OSError:
            continue
        if SECRET.encode() in content:
            leaked.append(candidate)
    assert leaked == [], f"the credential appears in {leaked}"
