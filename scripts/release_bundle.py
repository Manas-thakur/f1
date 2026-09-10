#!/usr/bin/env python
"""Assemble (and verify) the release bundle.

`operations/TECHNICAL_SPEC.md`:

    Bundle source revision, schema, migrations, frontend assets, approved
    rules/model manifests, synthetic seed scenario, test report and startup
    instructions. Verify a clean machine can launch the synthetic
    demonstration without reading parent-project files. A rollback restores
    compatible schema/model/rules together; never downgrade one silently.
    Include licenses for imported tools/data and clearly separate demonstration
    fixtures from benchmark evidence.

    python scripts/release_bundle.py --out artifacts/release/afterlap-0.1.0
    python scripts/release_bundle.py --out ... --test-report report.txt --web-dist apps/web/dist
    python scripts/release_bundle.py --verify artifacts/release/afterlap-0.1.0

Three decisions in here are deliberate and would otherwise look like
shortcuts:

**Source revision is a content digest, not a VCS revision.** This package is
forbidden from running git, and reading the enclosing repository's internals
would mean reading the parent project this plan is required to leave alone. So
the bundle records a SHA-256 over every source file it ships, sorted by path —
which is what a revision is *for* (identifying exactly these bytes) and is
reproducible on a machine with no VCS at all. `source_revision.kind` says
`content_digest` so nobody mistakes it for a commit id.

**Anything absent is recorded as absent, with the command that would produce
it.** A bundle with no frontend assets says `"state": "unavailable"` and names
`bun run build`. It never ships an empty directory and
calls it assets, and `--require-complete` turns any such gap into a non-zero
exit for a release gate.

**Demonstration fixtures and benchmark evidence are separate trees.** Every
scenario, car, track and rule pack in this repository is a synthetic fixture;
nothing is measured. They live under `fixtures/` with that stated, and
`evidence/` holds only material a benchmark run actually produced. An empty
`evidence/` is the correct state for this release and the bundle says so.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

_HERE = Path(__file__).resolve().parent
WORKSPACE = _HERE.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

MANIFEST_NAME = "manifest.json"
CHECKSUMS_NAME = "MANIFEST.sha256"
BUNDLE_SCHEMA = "afterlap.release.bundle/1"

SOURCE_TREES: tuple[str, ...] = (
    "packages/contracts/afterlap_contracts",
    "packages/contracts/generated",
    "packages/core/afterlap_core",
    "packages/application/afterlap_application",
    "packages/infrastructure/afterlap_infrastructure",
    "apps/api/afterlap_api",
    "apps/web/src",
    "workers",
    "configs",
    "infra",
    "scripts",
    "tests",
)

SOURCE_FILES: tuple[str, ...] = (
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "bun.lock",
    ".python-version",
    "apps/api/alembic.ini",
    "apps/api/pyproject.toml",
    "apps/web/package.json",
    "apps/web/vite.config.ts",
    "apps/web/tsconfig.json",
    "apps/web/index.html",
    "packages/contracts/pyproject.toml",
    "packages/core/pyproject.toml",
    "packages/application/pyproject.toml",
    "packages/infrastructure/pyproject.toml",
)

EXCLUDED_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
    "node_modules",
    ".venv",
    "dist",
    "test-results",
}

SEED_SCENARIO_ID = "two-straight-counterattack"
SEED_RULESET_ID = "synthetic-pack-v1"


def sha256_of(path: Path, *, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def iter_source_files(root: Path) -> Iterable[Path]:
    for relative in SOURCE_FILES:
        candidate = root / relative
        if candidate.is_file():
            yield candidate
    for tree in SOURCE_TREES:
        base = root / tree
        if not base.is_dir():
            continue
        for candidate in sorted(base.rglob("*")):
            if not candidate.is_file():
                continue
            if any(part in EXCLUDED_DIR_NAMES for part in candidate.relative_to(root).parts):
                continue
            if candidate.suffix in {".pyc", ".pyo"}:
                continue
            yield candidate


@dataclass(slots=True)
class Section:
    """One bundle section, present or explicitly absent."""

    name: str
    state: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.state == "available"

    def as_dict(self) -> dict[str, Any]:
        return {"state": self.state, "detail": self.detail, **self.data}


def source_revision(root: Path, staging: Path) -> Section:
    """Copy every source file and hash the sorted (path, digest) listing."""
    files: list[tuple[str, str, int]] = []
    target_root = staging / "source"
    for candidate in iter_source_files(root):
        relative = candidate.relative_to(root)
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, target)
        files.append((relative.as_posix(), sha256_of(candidate), candidate.stat().st_size))

    listing = "\n".join(f"{digest}  {path}" for path, digest, _ in sorted(files))
    revision = hashlib.sha256(listing.encode("utf-8")).hexdigest()
    (staging / "SOURCE_FILES.sha256").write_text(listing + "\n", encoding="utf-8")

    return Section(
        name="source_revision",
        state="available" if files else "unavailable",
        detail=(
            f"SHA-256 over {len(files)} sorted source file digests. Not a VCS revision: this "
            "package runs no git command and does not read the enclosing repository."
        ),
        data={
            "kind": "content_digest",
            "algorithm": "sha256-of-sorted-file-digests",
            "revision": f"sha256:{revision}",
            "file_count": len(files),
            "total_bytes": sum(size for _, _, size in files),
            "listing": "SOURCE_FILES.sha256",
        },
    )


def schema(staging: Path) -> Section:
    """The ORM schema as DDL for both engines, plus the contract schemas."""
    from sqlalchemy.dialects import postgresql, sqlite
    from sqlalchemy.schema import CreateTable

    from afterlap_contracts import CONTRACT_REVISION, SCHEMA_VERSION
    from afterlap_infrastructure.persistence.models import Base

    out = staging / "schema"
    out.mkdir(parents=True, exist_ok=True)

    written: dict[str, str] = {}
    for label, dialect in (("postgresql", postgresql.dialect()), ("sqlite", sqlite.dialect())):
        statements = [
            str(CreateTable(table).compile(dialect=dialect)).strip() + ";"
            for table in Base.metadata.sorted_tables
        ]
        path = out / f"schema.{label}.sql"
        path.write_text(
            f"-- AFTERLAP contract revision {CONTRACT_REVISION}, wire schema {SCHEMA_VERSION}\n"
            f"-- Generated from the ORM metadata for the {label} dialect.\n"
            f"-- The authoritative schema is the Alembic migration under migrations/.\n\n"
            + "\n\n".join(statements)
            + "\n",
            encoding="utf-8",
        )
        written[label] = path.name

    contracts = WORKSPACE / "packages" / "contracts" / "generated" / "schemas.json"
    if contracts.is_file():
        shutil.copy2(contracts, out / "contract-schemas.json")
        written["contract_schemas"] = "contract-schemas.json"

    return Section(
        name="schema",
        state="available",
        detail=f"{len(Base.metadata.sorted_tables)} tables, DDL for both engines",
        data={
            "contract_revision": CONTRACT_REVISION,
            "wire_schema_version": SCHEMA_VERSION,
            "tables": [table.name for table in Base.metadata.sorted_tables],
            "files": written,
        },
    )


def migrations(root: Path, staging: Path) -> Section:
    """The migration scripts and the head revision they upgrade to."""
    source = root / "apps" / "api" / "afterlap_api" / "migrations"
    if not source.is_dir():
        return Section("migrations", "unavailable", f"{source} does not exist", {})

    out = staging / "migrations"
    shutil.copytree(
        source,
        out,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*EXCLUDED_DIR_NAMES, "*.pyc"),
    )
    ini = root / "apps" / "api" / "alembic.ini"
    if ini.is_file():
        shutil.copy2(ini, out / "alembic.ini")

    heads: list[str] = []
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(ini))
        config.set_main_option("script_location", str(source))
        heads = list(ScriptDirectory.from_config(config).get_heads())
    except Exception as exc:  # pragma: no cover - alembic is a hard dependency
        return Section(
            "migrations",
            "degraded",
            f"scripts copied but the head could not be resolved: {type(exc).__name__}: {exc}",
            {"revisions": sorted(p.name for p in (out / "versions").glob("*.py"))},
        )

    return Section(
        name="migrations",
        state="available" if len(heads) == 1 else "degraded",
        detail=(
            f"single head {heads[0]}"
            if len(heads) == 1
            else f"{len(heads)} heads: {heads} — a rollback target is ambiguous"
        ),
        data={
            "heads": heads,
            "revisions": sorted(p.name for p in (out / "versions").glob("*.py")),
        },
    )


def frontend(root: Path, staging: Path, dist: Path | None) -> Section:
    """Built web assets, or an honest statement that they were not built."""
    candidate = dist or (root / "apps" / "web" / "dist")
    index = candidate / "index.html"
    build_command = "bun install --frozen-lockfile && bun run build"
    if not index.is_file():
        return Section(
            "frontend_assets",
            "unavailable",
            f"no built assets at {candidate}. Build them with: {build_command}",
            {"expected_path": str(candidate), "build_command": build_command},
        )

    out = staging / "web"
    shutil.copytree(candidate, out, dirs_exist_ok=True)
    files = [p for p in out.rglob("*") if p.is_file()]
    return Section(
        name="frontend_assets",
        state="available",
        detail=f"{len(files)} file(s) copied from {candidate}",
        data={
            "source": str(candidate),
            "entry": "web/index.html",
            "file_count": len(files),
            "total_bytes": sum(p.stat().st_size for p in files),
            "build_command": build_command,
            "note": (
                "Served by nginx in infra/docker-compose.yml, which proxies /api and /ws on the "
                "same origin. No API host is compiled into the bundle."
            ),
        },
    )


def rules_and_models(root: Path, staging: Path) -> tuple[Section, Section]:
    """Rule packs with their content hashes, and any approved model bundle."""
    from afterlap_contracts import ApprovalStatus, ModelManifest
    from afterlap_core.config import list_configs
    from afterlap_core.rules import load_rule_pack

    out = staging / "rules"
    out.mkdir(parents=True, exist_ok=True)
    packs: list[dict[str, Any]] = []
    for pack_id in list_configs("rules"):
        source = root / "configs" / "rules" / f"{pack_id}.yaml"
        if source.is_file():
            shutil.copy2(source, out / source.name)
        try:
            pack = load_rule_pack(pack_id)
        except Exception as exc:
            packs.append({"ruleset_id": pack_id, "state": "unloadable", "detail": str(exc)})
            continue
        packs.append(
            {
                "ruleset_id": pack_id,
                "ruleset_hash": pack.ruleset_hash,
                "season_revision": getattr(pack.manifest, "season_revision", None),
                "synthetic": True,
                "unknown_conditions": list(getattr(pack.manifest, "unknown_conditions", ()) or ()),
            }
        )

    rules_section = Section(
        name="approved_rules",
        state="available" if packs else "unavailable",
        detail=(
            f"{len(packs)} synthetic rule pack(s). 'Approved' here means loadable and hashed; "
            "no FIA document has been resolved against these packs."
        ),
        data={"packs": packs},
    )

    models_out = staging / "models"
    models_out.mkdir(parents=True, exist_ok=True)
    approved: list[dict[str, Any]] = []
    found: list[dict[str, Any]] = []
    models_root = root / "artifacts" / "models"
    for bundle_json in sorted(models_root.rglob("bundle.json")) if models_root.is_dir() else []:
        try:
            payload = json.loads(bundle_json.read_text(encoding="utf-8"))
            manifest = ModelManifest.model_validate(payload["model_manifest"])
        except Exception as exc:
            found.append({"path": str(bundle_json), "state": "unreadable", "detail": str(exc)})
            continue
        entry = {
            "bundle_id": manifest.id,
            "weights_hash": manifest.weights_hash,
            "feature_schema_hash": manifest.feature_schema_hash,
            "rule_family": manifest.rule_family,
            "reward_revision": manifest.reward_revision,
            "approval_status": manifest.approval_status.value,
            "benchmark_report_hash": manifest.benchmark_report_hash,
        }
        found.append(entry)
        if manifest.approval_status is ApprovalStatus.APPROVED:
            approved.append(entry)
            target = models_out / manifest.id
            shutil.copytree(bundle_json.parent, target, dirs_exist_ok=True)

    models_section = Section(
        name="approved_model_manifests",
        state="available" if approved else "absent",
        detail=(
            f"{len(approved)} approved bundle(s) of {len(found)} found"
            if found
            else (
                "no model bundle exists in artifacts/models. The release runs the validated "
                "baseline path only; the learned contribution is disabled and named as such on "
                "every recommendation. This is the correct state for this release, not a gap in "
                "the bundle."
            )
        ),
        data={"approved": approved, "all_bundles_found": found},
    )
    return rules_section, models_section


def seed_scenario(root: Path, staging: Path) -> Section:
    """The synthetic demonstration scenario and everything it references."""
    from afterlap_core.config import load_config
    from afterlap_core.simulation import load_bundle

    out = staging / "fixtures"
    out.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    missing: list[str] = []

    try:
        bundle = load_bundle(SEED_SCENARIO_ID)
    except Exception as exc:
        return Section(
            "seed_scenario",
            "unavailable",
            f"the seed scenario {SEED_SCENARIO_ID} could not be loaded: {exc}",
            {},
        )

    wanted: list[tuple[str, str]] = [
        ("scenarios", SEED_SCENARIO_ID),
        ("rules", SEED_RULESET_ID),
        ("tracks", bundle.track.id),
        ("objectives", "objective-v1"),
    ]
    wanted.extend(("cars", model_id) for model_id in sorted(set(bundle.scenario.cars.values())))

    for kind, config_id in wanted:
        source = root / "configs" / kind / f"{config_id}.yaml"
        if not source.is_file():
            try:
                load_config(kind, config_id)
            except Exception:
                missing.append(f"{kind}/{config_id}")
                continue
        target = out / kind / f"{config_id}.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(f"{kind}/{config_id}.yaml")

    (out / "README.md").write_text(
        "# Demonstration fixtures\n\n"
        "Everything in this directory is a **synthetic fixture** authored inside this project. "
        "It is not measured telemetry, not a calibrated model of any car or circuit, and not "
        "evidence of performance.\n\n"
        "Benchmark evidence — anything a real evaluation run produced — lives in `../evidence/` "
        "and is kept separate on purpose so a fixture trajectory can never be quoted as a "
        "result.\n\n"
        f"Seed scenario: `{SEED_SCENARIO_ID}` with rule pack `{SEED_RULESET_ID}`, "
        f"track `{bundle.track.id}`, {len(bundle.scenario.cars)} car(s).\n",
        encoding="utf-8",
    )

    return Section(
        name="seed_scenario",
        state="available" if not missing else "degraded",
        detail=(
            f"{SEED_SCENARIO_ID} with {len(copied)} referenced document(s)"
            + (f"; could not resolve {missing}" if missing else "")
        ),
        data={
            "scenario_id": SEED_SCENARIO_ID,
            "ruleset_id": SEED_RULESET_ID,
            "track_id": bundle.track.id,
            "ego_car_id": bundle.scenario.ego_car_id,
            "car_slots": dict(bundle.scenario.cars),
            "documents": copied,
            "unresolved": missing,
            "synthetic": True,
        },
    )


def evidence(staging: Path, reports: Iterable[Path]) -> Section:
    """Benchmark evidence, kept strictly apart from fixtures."""
    out = staging / "evidence"
    out.mkdir(parents=True, exist_ok=True)
    copied = []
    for report in reports:
        if report.is_file():
            shutil.copy2(report, out / report.name)
            copied.append(report.name)
    (out / "README.md").write_text(
        "# Benchmark evidence\n\n"
        "Only material a real evaluation run produced belongs here. Demonstration fixtures are "
        "in `../fixtures/` and must never be moved into this directory.\n\n"
        + (
            "Contents: " + ", ".join(copied) + "\n"
            if copied
            else "This directory is **empty**, which is the accurate state for this release: no "
            "held-out benchmark has been run and promoted. Coordinator decision D-06 also "
            "records that exogenous physical disturbances are not implemented, so a "
            "seed-resampled confidence interval would be falsely tight.\n"
        ),
        encoding="utf-8",
    )
    return Section(
        name="benchmark_evidence",
        state="available" if copied else "absent",
        detail=(
            f"{len(copied)} report(s)"
            if copied
            else "no benchmark evidence is included; the directory is empty and says so"
        ),
        data={"reports": copied},
    )


def test_report(staging: Path, provided: Iterable[Path]) -> Section:
    """Whatever test output the caller supplied, verbatim, plus the commands."""
    out = staging / "tests"
    out.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, Any]] = []
    for path in provided:
        if not path.is_file():
            continue
        shutil.copy2(path, out / path.name)
        copied.append({"file": path.name, "sha256": f"sha256:{sha256_of(path)}"})

    commands = [
        "uv sync --frozen --all-packages --all-extras",
        "uv run python -m afterlap_core.cli doctor",
        "uv run python -m afterlap_core.cli generate-contracts --check",
        "uv run python -m pytest tests/contracts tests/numerics",
        "uv run python -m pytest tests/operations",
        "bun install --frozen-lockfile",
        "bun run typecheck",
        "bun run test",
        "bun run build",
        "bun run test:e2e",
    ]
    (out / "COMMANDS.md").write_text(
        "# Verification commands\n\n"
        "Run from the implementation workspace root. Output that is included in this bundle is "
        "listed in `manifest.json` under `test_report.files`; anything not listed was **not** "
        "run as part of assembling this bundle.\n\n```\n" + "\n".join(commands) + "\n```\n",
        encoding="utf-8",
    )

    return Section(
        name="test_report",
        state="available" if copied else "unavailable",
        detail=(
            f"{len(copied)} report file(s) included verbatim"
            if copied
            else "no test output was supplied to --test-report; the commands are recorded but no "
            "result is claimed"
        ),
        data={"files": copied, "commands": commands},
    )


def third_party_licenses(staging: Path) -> Section:
    """Installed distributions and their declared licenses."""
    from importlib.metadata import distributions

    rows: list[dict[str, str]] = []
    for dist in distributions():
        meta = dist.metadata
        name = meta.get("Name") or getattr(dist, "name", "") or "unknown"
        classifiers = meta.get_all("Classifier") or []
        license_classifiers = [c for c in classifiers if c.startswith("License ::")]
        # `unspecified`, never assumed permissive. `License` can be a whole
        # licence text, so only its first line is kept.
        declared = meta.get("License-Expression") or meta.get("License") or ""
        first_line = str(declared).splitlines()[0][:120].strip() if declared else ""
        rows.append(
            {
                "name": str(name),
                "version": str(dist.version),
                "license": first_line or "unspecified",
                "license_classifiers": "; ".join(license_classifiers) or "none declared",
            }
        )
    rows.sort(key=lambda row: row["name"].lower())

    lines = [
        "# Third-party licenses",
        "",
        (
            "Declared license metadata for every distribution installed in the environment that "
            "assembled this bundle. Read from package metadata, not asserted by hand; a package "
            "whose metadata declares nothing is listed as `unspecified` rather than assumed "
            "permissive."
        ),
        "",
        "| Package | Version | License | Classifiers |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| {row['name']} | {row['version']} | {row['license']} | {row['license_classifiers']} |"
        for row in rows
    )
    lines.extend(
        [
            "",
            "## Data",
            "",
            (
                "No third-party dataset is bundled. Every scenario, track, car, rule pack and "
                "objective is a synthetic fixture authored inside this project (see "
                "`fixtures/README.md`). No measured telemetry and no licensed feed is included."
            ),
            "",
        ]
    )
    (staging / "THIRD_PARTY.md").write_text("\n".join(lines), encoding="utf-8")

    unspecified = [row["name"] for row in rows if row["license"] == "unspecified"]
    return Section(
        name="third_party_licenses",
        state="available",
        detail=f"{len(rows)} distribution(s); {len(unspecified)} declare no license in metadata",
        data={"distribution_count": len(rows), "unspecified": unspecified[:40]},
    )


def startup_instructions(staging: Path, sections: dict[str, Section]) -> Section:
    frontend_state = sections["frontend_assets"].state
    text = f"""# Starting AFTERLAP from this bundle

Everything needed is in this directory. Nothing here reads the parent project.

## What this is

A synthetic, simulator-only engineer decision-support product. Every scenario,
car, track and rule pack is an invented fixture. Nothing in this bundle is
evidence of physics fidelity, latency on your hardware, calibration, or
comparative performance.

## Option A — Docker Compose (the packaged product)

```
cd source
cp infra/.env.example infra/.env
# set AFTERLAP_DB_PASSWORD in infra/.env — there is no default
python -c "import secrets; print(secrets.token_urlsafe(32))"

docker compose -f infra/docker-compose.yml --env-file infra/.env up --build
```

Then open http://127.0.0.1:8080. The API is at http://127.0.0.1:8010 and
PostgreSQL is on 127.0.0.1:5433. All three bind loopback only.

The `migrate` service runs the Alembic upgrade to head and the API waits for it
to succeed. `docker compose down` stops everything; `docker compose down -v`
also discards the four named volumes (`afterlap-db`, `afterlap-artifacts`,
`afterlap-trajectories`, `afterlap-models`).

## Option B — from source, no containers

```
cd source
uv sync --frozen --all-packages --all-extras
uv run python -m afterlap_core.cli doctor        # must report contracts, numerics, storage available

AFTERLAP_ENV=development uv run python -m afterlap_api.cli serve \\
    --host 127.0.0.1 --port 8000

# second terminal
cd apps/web && bun install --frozen-lockfile && bun run dev
```

The API creates its schema on startup, so no separate migration step is needed
for the SQLite development store.

## Verify it works, without a browser

```
uv run python scripts/demo.py --base-url http://127.0.0.1:3000 --json demo-report.json
```

That executes the demonstration runbook against the live server: create a
session, take the control lease, start, step to an actionable instruction
(about t = 26 s of simulated time), select it, mark it communicated, have the
simulated driver act, observe the execution event, snapshot, branch two
treatments, export the record. It prints what it observed at every step and
exits non-zero if any step does not happen.

## Frontend assets

State in this bundle: **{frontend_state}**. If `unavailable`, build them with
`bun install --frozen-lockfile && bun run build`; the
compose `web` service builds them itself.

## Rollback

See `ROLLBACK.md`. Schema, rules and model move together.
"""
    (staging / "STARTUP.md").write_text(text, encoding="utf-8")
    return Section("startup_instructions", "available", "STARTUP.md", {"file": "STARTUP.md"})


def rollback_instructions(staging: Path, sections: dict[str, Section]) -> Section:
    schema_section = sections["schema"]
    migration_section = sections["migrations"]
    rules_section = sections["approved_rules"]
    models_section = sections["approved_model_manifests"]

    heads = migration_section.data.get("heads", [])
    pack_lines = "\n".join(
        f"- `{p.get('ruleset_id')}` → `{p.get('ruleset_hash', 'unloadable')}`"
        for p in rules_section.data.get("packs", [])
    )
    approved = models_section.data.get("approved", [])
    model_lines = (
        "\n".join(f"- `{m['bundle_id']}` weights `{m['weights_hash']}`" for m in approved)
        or "- none. The validated baseline path is in force and is named on every recommendation."
    )

    text = f"""# Rollback

A rollback restores **schema, rules and model together**. Never downgrade one
of the three on its own: a session pins its model version and its ruleset hash
for its whole life, and a recommendation records both, so a mismatched trio
produces decision records that cannot be re-checked against anything.

## The compatible set in this bundle

| Component | Identity |
|---|---|
| Contract revision | {schema_section.data.get("contract_revision")} |
| Wire schema version | {schema_section.data.get("wire_schema_version")} |
| Alembic head | {", ".join(heads) if heads else "unresolved"} |

Rule packs:

{pack_lines or "- none"}

Approved model bundles:

{model_lines}

## Procedure

1. Stop the API and the batch worker. Leave the database running.
2. Note the current Alembic head:
   `select version_num from alembic_version;`
3. Restore the *whole* bundle for the target release — `source/`, `migrations/`,
   `rules/`, `models/` — not a subset.
4. Downgrade the schema to the target bundle's head:
   `alembic -c apps/api/alembic.ini downgrade <head from the target bundle>`
5. Start the API. `doctor` must report contracts, numerics and storage
   available before any session is created.
6. Confirm the trio matches: `GET /api/v1/version` reports the contract
   revision, and every rule pack hash above must resolve.

## What a rollback does not do

It does not rewrite archived decision records. Sessions recorded under the
newer trio keep their own manifest, ruleset hash and model hash, and remain
readable evidence of what was decided under those versions. Replay never
mutates the archived original.
"""
    (staging / "ROLLBACK.md").write_text(text, encoding="utf-8")
    return Section("rollback_instructions", "available", "ROLLBACK.md", {"file": "ROLLBACK.md"})


def checksum_everything(staging: Path) -> tuple[Path, str, int]:
    """Write MANIFEST.sha256 over every file, and hash the listing itself."""
    rows: list[tuple[str, str]] = []
    for candidate in sorted(staging.rglob("*")):
        if not candidate.is_file() or candidate.name in {CHECKSUMS_NAME, MANIFEST_NAME}:
            continue
        rows.append((candidate.relative_to(staging).as_posix(), sha256_of(candidate)))
    listing = "\n".join(f"{digest}  {path}" for path, digest in rows) + "\n"
    target = staging / CHECKSUMS_NAME
    target.write_text(listing, encoding="utf-8")
    return target, f"sha256:{hashlib.sha256(listing.encode('utf-8')).hexdigest()}", len(rows)


def build(
    out: Path,
    *,
    root: Path = WORKSPACE,
    web_dist: Path | None = None,
    test_reports: Iterable[Path] = (),
    evidence_reports: Iterable[Path] = (),
    require_complete: bool = False,
) -> tuple[Path, dict[str, Any], list[str]]:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    sections: dict[str, Section] = {}

    def record(section: Section) -> Section:
        sections[section.name] = section
        print(f"  {section.state:<12} {section.name}: {section.detail}", flush=True)
        return section

    print(f"assembling {out}", flush=True)
    record(source_revision(root, out))
    record(schema(out))
    record(migrations(root, out))
    record(frontend(root, out, web_dist))
    rules_section, models_section = rules_and_models(root, out)
    record(rules_section)
    record(models_section)
    record(seed_scenario(root, out))
    record(evidence(out, evidence_reports))
    record(test_report(out, test_reports))
    record(third_party_licenses(out))
    record(startup_instructions(out, sections))
    record(rollback_instructions(out, sections))

    checksums, listing_hash, file_count = checksum_everything(out)

    from afterlap_contracts import CONTRACT_REVISION, SCHEMA_VERSION

    manifest = {
        "schema": BUNDLE_SCHEMA,
        "assembled_at": datetime.now(UTC).isoformat(),
        "synthetic": True,
        "notice": (
            "Synthetic, simulator-only release bundle. Nothing here is measured telemetry, a "
            "calibrated model, or evidence of physics fidelity, latency, calibration or "
            "comparative performance."
        ),
        "contract_revision": CONTRACT_REVISION,
        "wire_schema_version": SCHEMA_VERSION,
        "assembled_on": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "checksums": {
            "file": CHECKSUMS_NAME,
            "file_count": file_count,
            "listing_sha256": listing_hash,
        },
        "sections": {name: section.as_dict() for name, section in sections.items()},
    }
    (out / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    gaps = [name for name, section in sections.items() if section.state not in {"available", "absent"}]
    print(f"\n{file_count} file(s), checksum listing {listing_hash}", flush=True)
    if gaps:
        print(f"incomplete sections: {', '.join(gaps)}", flush=True)
    del require_complete, checksums
    return out, manifest, gaps


def verify(bundle: Path) -> tuple[bool, list[str]]:
    """Re-hash every file and compare against the bundle's own listing."""
    problems: list[str] = []
    manifest_path = bundle / MANIFEST_NAME
    checksums_path = bundle / CHECKSUMS_NAME
    if not manifest_path.is_file():
        return False, [f"{MANIFEST_NAME} is missing"]
    if not checksums_path.is_file():
        return False, [f"{CHECKSUMS_NAME} is missing"]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    listing = checksums_path.read_text(encoding="utf-8")
    expected_listing_hash = manifest.get("checksums", {}).get("listing_sha256")
    actual_listing_hash = f"sha256:{hashlib.sha256(listing.encode('utf-8')).hexdigest()}"
    if expected_listing_hash != actual_listing_hash:
        problems.append(
            f"{CHECKSUMS_NAME} hashes to {actual_listing_hash} but the manifest declares "
            f"{expected_listing_hash}"
        )

    declared: dict[str, str] = {}
    for line in listing.splitlines():
        if not line.strip():
            continue
        digest, _, path = line.partition("  ")
        declared[path] = digest

    present = {
        p.relative_to(bundle).as_posix()
        for p in bundle.rglob("*")
        if p.is_file() and p.name not in {CHECKSUMS_NAME, MANIFEST_NAME}
    }
    for path in sorted(set(declared) - present):
        problems.append(f"declared file is missing: {path}")
    for path in sorted(present - set(declared)):
        problems.append(f"undeclared file present: {path}")
    for path in sorted(set(declared) & present):
        actual = sha256_of(bundle / path)
        if actual != declared[path]:
            problems.append(f"{path} hashes to {actual}, declared {declared[path]}")

    print(f"verified {len(present)} file(s) in {bundle}", flush=True)
    for problem in problems:
        print(f"  PROBLEM {problem}", flush=True)
    return not problems, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble or verify the AFTERLAP release bundle.")
    parser.add_argument("--out", type=Path, default=None, help="Directory to assemble into.")
    parser.add_argument("--verify", type=Path, default=None, help="Verify an assembled bundle instead.")
    parser.add_argument("--root", type=Path, default=WORKSPACE, help="Implementation workspace root.")
    parser.add_argument("--web-dist", type=Path, default=None, help="Built web assets directory.")
    parser.add_argument(
        "--test-report",
        type=Path,
        action="append",
        default=[],
        help="Test output to include verbatim. Repeatable.",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        action="append",
        default=[],
        help="Benchmark report to include as evidence. Repeatable.",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Exit non-zero if any section is missing or degraded.",
    )
    args = parser.parse_args(argv)

    if args.verify is not None:
        ok, _ = verify(args.verify)
        return 0 if ok else 1

    if args.out is None:
        parser.error("provide --out DIRECTORY (or --verify DIRECTORY)")

    _, _, gaps = build(
        args.out,
        root=args.root,
        web_dist=args.web_dist,
        test_reports=args.test_report,
        evidence_reports=args.evidence,
        require_complete=args.require_complete,
    )
    ok, _ = verify(args.out)
    if not ok:
        return 1
    if args.require_complete and gaps:
        print(f"--require-complete: {len(gaps)} section(s) incomplete", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
