"""Frozen import boundaries of the modular monolith.

Nothing else in the repository stops an import from crossing a layer: there is
no import-linter and no banned-api rule. These claims are the enforcement
point, so every one of them reads source with ``ast`` rather than importing a
module. Importing would run module-level side effects and would silently skip
any file that fails to import, which is exactly the file most likely to have
broken a boundary.
"""

from __future__ import annotations

import ast
import importlib
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = Path(__file__).resolve()
PRUNED_DIR_NAMES = frozenset({"node_modules", "__pycache__"})
GENERATED_CONTRACTS = REPO_ROOT / "packages" / "contracts" / "generated"
ALEMBIC_ENV = REPO_ROOT / "apps" / "api" / "afterlap_api" / "migrations" / "env.py"
ALEMBIC_VERSIONS = REPO_ROOT / "apps" / "api" / "afterlap_api" / "migrations" / "versions"
INFRASTRUCTURE_MODELS = (
    REPO_ROOT / "packages" / "infrastructure" / "afterlap_infrastructure" / "persistence" / "models.py"
)

WEB_FRAMEWORKS = frozenset({"fastapi", "starlette", "uvicorn"})
RELATIONAL_TOOLING = frozenset({"sqlalchemy", "alembic"})
HTTP_CLIENTS = frozenset({"httpx", "requests"})
INNER_LAYERS = frozenset(
    {"afterlap_application", "afterlap_contracts", "afterlap_core", "afterlap_infrastructure"}
)


@dataclass(frozen=True, slots=True)
class Layer:
    """One import root and the modules its row of the boundary table permits.

    ``allowed_afterlap`` is the layering rule: any first-party import outside
    it is a violation. ``banned`` names third-party or standard-library
    modules the layer must never reach. ``allowed_third_party`` closes the
    layer completely when it is not ``None``: everything beyond the standard
    library must then be listed.
    """

    import_root: Path
    allowed_afterlap: frozenset[str]
    banned: frozenset[str]
    allowed_third_party: frozenset[str] | None = None


LAYERS: dict[str, Layer] = {
    "afterlap_contracts": Layer(
        import_root=Path("packages", "contracts", "afterlap_contracts"),
        allowed_afterlap=frozenset({"afterlap_contracts"}),
        banned=WEB_FRAMEWORKS | RELATIONAL_TOOLING | HTTP_CLIENTS | {"multiprocessing", "numpy"},
        allowed_third_party=frozenset({"pydantic", "yaml"}),
    ),
    "afterlap_core": Layer(
        import_root=Path("packages", "core", "afterlap_core"),
        allowed_afterlap=frozenset({"afterlap_contracts", "afterlap_core"}),
        banned=WEB_FRAMEWORKS | RELATIONAL_TOOLING | HTTP_CLIENTS | {"multiprocessing"},
    ),
    "afterlap_application": Layer(
        import_root=Path("packages", "application", "afterlap_application"),
        allowed_afterlap=frozenset({"afterlap_application", "afterlap_contracts"}),
        banned=WEB_FRAMEWORKS | RELATIONAL_TOOLING,
    ),
    "afterlap_infrastructure": Layer(
        import_root=Path("packages", "infrastructure", "afterlap_infrastructure"),
        allowed_afterlap=frozenset({"afterlap_contracts", "afterlap_core", "afterlap_infrastructure"}),
        banned=WEB_FRAMEWORKS,
    ),
    "afterlap_api": Layer(
        import_root=Path("apps", "api", "afterlap_api"),
        allowed_afterlap=INNER_LAYERS | {"afterlap_api"},
        banned=WEB_FRAMEWORKS,
    ),
    "workers": Layer(
        import_root=Path("workers"),
        allowed_afterlap=INNER_LAYERS,
        banned=WEB_FRAMEWORKS,
    ),
}


@dataclass(frozen=True, slots=True)
class ImportRecord:
    """One import statement resolved to the absolute module it names."""

    path: Path
    lineno: int
    module: str
    escapes_package: bool

    @property
    def top_level(self) -> str:
        """The distribution-level name the import reaches into."""
        return self.module.partition(".")[0]

    @property
    def site(self) -> str:
        """``file:line`` in repository-relative posix form, stable on every platform."""
        return f"{self.path.relative_to(REPO_ROOT).as_posix()}:{self.lineno}"


@dataclass(frozen=True, slots=True)
class MetadataSite:
    """One place the repository creates a SQLAlchemy mapping registry."""

    path: Path
    lineno: int
    kind: str

    @property
    def site(self) -> str:
        """``file:line`` in repository-relative posix form."""
        return f"{self.path.relative_to(REPO_ROOT).as_posix()}:{self.lineno}"


@cache
def files_under(root: Path, suffix: str) -> tuple[Path, ...]:
    """Every file under ``root`` ending in ``suffix``, skipping caches and generated output.

    The walk prunes directories in place so it never descends into ``.venv``
    or ``node_modules``, which is what keeps the whole module well under a
    second.
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not name.startswith(".")
            and name not in PRUNED_DIR_NAMES
            and here / name != GENERATED_CONTRACTS
        )
        found.extend(
            sorted(
                here / name
                for name in filenames
                if name.endswith(suffix) and not name.startswith("._")
            )
        )
    return tuple(found)


def python_files(root: Path) -> tuple[Path, ...]:
    """Every ``.py`` file under ``root``."""
    return files_under(root, ".py")


@cache
def parse_module(path: Path) -> ast.Module:
    """Parse ``path`` into a syntax tree without importing it."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def resolve_relative(node: ast.ImportFrom, path: Path, root: Path, package: str) -> tuple[str, bool]:
    """Resolve one ``from ... import`` to an absolute module name.

    The second element is ``True`` when the relative level climbs past the
    owning package, which is itself an escape from the layer and never legal.
    """
    if not node.level:
        return node.module or "", False
    parts = [package, *path.parent.relative_to(root).parts]
    kept = len(parts) - (node.level - 1)
    if kept <= 0:
        return "." * node.level + (node.module or ""), True
    base = ".".join(parts[:kept])
    return f"{base}.{node.module}" if node.module else base, False


def imports_in(tree: ast.Module, path: Path, root: Path, package: str) -> list[ImportRecord]:
    """Every import anywhere in ``tree``, including deferred ones inside functions."""
    records: list[ImportRecord] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            records.extend(ImportRecord(path, node.lineno, alias.name, False) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module, escaped = resolve_relative(node, path, root, package)
            records.append(ImportRecord(path, node.lineno, module, escaped))
    return records


@cache
def imports_of(layer_name: str) -> tuple[ImportRecord, ...]:
    """Every import reachable in the source of ``layer_name``."""
    root = REPO_ROOT / LAYERS[layer_name].import_root
    records: list[ImportRecord] = []
    for path in python_files(root):
        records.extend(imports_in(parse_module(path), path, root, root.name))
    return tuple(records)


def violations_of(layer_name: str) -> list[str]:
    """Every import in ``layer_name`` that its row of the boundary table forbids."""
    layer = LAYERS[layer_name]
    found: list[str] = []
    for record in imports_of(layer_name):
        top = record.top_level
        first_party = top.startswith("afterlap")
        if record.escapes_package:
            found.append(f"{record.site}: relative import {record.module} climbs out of {layer_name}")
        elif top in layer.banned or (first_party and top not in layer.allowed_afterlap):
            found.append(f"{record.site}: {layer_name} must not import {record.module}")
        elif (
            layer.allowed_third_party is not None
            and not first_party
            and top not in sys.stdlib_module_names
            and top not in layer.allowed_third_party
        ):
            allowed = sorted(layer.allowed_third_party)
            found.append(
                f"{record.site}: {layer_name} may depend only on stdlib and {allowed}, not {record.module}"
            )
    return found


def render(heading: str, lines: Sequence[str]) -> str:
    """One actionable block: the claim that broke, then every offending site."""
    return "\n".join([f"{heading} ({len(lines)}):", *lines])


def discovered_import_roots() -> set[Path]:
    """Every directory the repository layout treats as a distributable package root."""
    roots: set[Path] = set()
    for parent in (REPO_ROOT / "packages", REPO_ROOT / "apps"):
        for project in sorted(child for child in parent.iterdir() if child.is_dir()):
            for candidate in sorted(child for child in project.iterdir() if child.is_dir()):
                if (candidate / "__init__.py").is_file():
                    roots.add(candidate.relative_to(REPO_ROOT))
    workers = REPO_ROOT / "workers"
    if (workers / "__init__.py").is_file():
        roots.add(workers.relative_to(REPO_ROOT))
    return roots


def called_name(node: ast.expr) -> str:
    """The trailing identifier of a ``Name`` or attribute chain, or an empty string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def metadata_sites() -> tuple[list[MetadataSite], list[MetadataSite]]:
    """Declarative bases and explicit ``MetaData`` constructions across the repository.

    A cheap text prefilter keeps the scan to the handful of files that could
    possibly declare a registry; the syntax tree then confirms it, so a mere
    mention inside a string or a docstring never counts.
    """
    markers = ("DeclarativeBase", "declarative_base", "MetaData")
    bases: list[MetadataSite] = []
    registries: list[MetadataSite] = []
    for path in python_files(REPO_ROOT):
        if path == THIS_FILE or ALEMBIC_VERSIONS in path.parents:
            continue
        if not any(marker in path.read_text(encoding="utf-8") for marker in markers):
            continue
        for node in ast.walk(parse_module(path)):
            if isinstance(node, ast.ClassDef):
                bases.extend(
                    MetadataSite(path, node.lineno, f"class {node.name}(DeclarativeBase)")
                    for base in node.bases
                    if called_name(base) == "DeclarativeBase"
                )
            elif isinstance(node, ast.Call):
                name = called_name(node.func)
                if name == "declarative_base":
                    bases.append(MetadataSite(path, node.lineno, "declarative_base()"))
                elif name == "MetaData":
                    registries.append(MetadataSite(path, node.lineno, "MetaData()"))
    return bases, registries


def alembic_metadata_binding() -> tuple[str, str]:
    """Resolve ``target_metadata = <name>.metadata`` in the Alembic env to (module, attribute).

    The env module runs migrations at import time, so it is read, never
    imported. An empty pair means the assignment or its import was not found
    in the shape this claim depends on.
    """
    tree = parse_module(ALEMBIC_ENV)
    bound = ""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "target_metadata" for t in node.targets):
            continue
        value = node.value
        if (
            isinstance(value, ast.Attribute)
            and value.attr == "metadata"
            and isinstance(value.value, ast.Name)
        ):
            bound = value.value.id
    if not bound:
        return "", ""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
            continue
        for alias in node.names:
            if (alias.asname or alias.name) == bound:
                return node.module, alias.name
    return "", ""


def test_the_boundary_table_covers_every_python_package_in_the_repository():
    """A new import root under packages/, apps/ or workers/ must get a row before it can drift."""
    declared = {layer.import_root for layer in LAYERS.values()}
    missing = sorted(root.as_posix() for root in discovered_import_roots() - declared)
    assert not missing, render("import roots with no boundary rule", missing)

    empty = sorted(name for name, layer in LAYERS.items() if not python_files(REPO_ROOT / layer.import_root))
    assert not empty, render("boundary rows pointing at nothing", empty)


def test_the_import_walk_sees_deferred_imports_inside_functions():
    """A deferred import is still a dependency, so a vacuous walk must not make these claims pass."""
    root = REPO_ROOT / LAYERS["afterlap_core"].import_root
    path = root / "planning" / "example.py"
    source = "def build():\n    import fastapi\n\n    from ...outside import thing\n\n    return thing\n"
    records = imports_in(ast.parse(source), path, root, root.name)

    assert [record.module for record in records] == ["fastapi", "...outside"]
    assert [record.lineno for record in records] == [2, 4]
    assert [record.escapes_package for record in records] == [False, True]


def test_the_wire_contracts_package_imports_only_the_standard_library_and_pydantic():
    """``afterlap_contracts`` carries wire schemas, so it reaches no other layer and no adapter."""
    found = violations_of("afterlap_contracts")
    assert not found, render("afterlap_contracts import boundary violations", found)


def test_the_domain_core_imports_no_web_framework_database_or_outer_layer():
    """``afterlap_core`` is pure domain logic above the contracts and below every adapter."""
    found = violations_of("afterlap_core")
    assert not found, render("afterlap_core import boundary violations", found)


def test_the_application_layer_owns_the_process_transport_but_no_adapter():
    """``afterlap_application`` may hold ``multiprocessing``; it may not hold HTTP or SQL."""
    found = violations_of("afterlap_application")
    assert not found, render("afterlap_application import boundary violations", found)

    reached = {record.top_level for record in imports_of("afterlap_application")}
    assert "multiprocessing" in reached, "the process transport left the layer that owns it"


def test_the_infrastructure_layer_imports_no_application_layer_and_no_web_framework():
    """``afterlap_infrastructure`` adapts contracts and core onto SQLAlchemy, nothing above it."""
    found = violations_of("afterlap_infrastructure")
    assert not found, render("afterlap_infrastructure import boundary violations", found)


def test_the_http_composition_root_wires_every_inner_layer():
    found = violations_of("afterlap_api")
    assert not found, render("afterlap_api import boundary violations", found)

    reached = {record.top_level for record in imports_of("afterlap_api")}
    missing = sorted(INNER_LAYERS - reached)
    assert not missing, render("layers the composition root no longer wires", missing)


def test_no_layer_below_the_http_boundary_imports_afterlap_api():
    """Only the HTTP app names the HTTP app, at module level or deferred inside a function."""
    offenders = [
        f"{record.site}: {name} imports {record.module}"
        for name in LAYERS
        if name != "afterlap_api"
        for record in imports_of(name)
        if record.top_level == "afterlap_api"
    ]
    assert not offenders, render("imports of afterlap_api from below the HTTP boundary", offenders)


def test_the_worker_entrypoints_never_import_the_http_application():
    """``workers/`` are composition roots of their own and must run without the HTTP app."""
    found = violations_of("workers")
    assert not found, render("workers import boundary violations", found)

    offenders = [
        f"{record.site}: {record.module}"
        for record in imports_of("workers")
        if record.top_level == "afterlap_api"
    ]
    assert not offenders, render("worker imports of afterlap_api", offenders)


def test_exactly_one_sqlalchemy_declarative_base_exists_in_the_infrastructure_layer():
    """One declarative base owns the schema; a second registry would split the migration history."""
    bases, registries = metadata_sites()
    listed = [f"{site.site}: {site.kind}" for site in bases]
    assert len(bases) == 1, render("expected exactly one declarative base", listed)

    expected = INFRASTRUCTURE_MODELS.relative_to(REPO_ROOT).as_posix()
    assert bases[0].path == INFRASTRUCTURE_MODELS, (
        f"the declarative base must live in {expected}, found {bases[0].site}"
    )

    stray = [site.site for site in registries if site.path != INFRASTRUCTURE_MODELS]
    assert not stray, render("MetaData registries outside the one declarative base", stray)


def test_the_api_persistence_shim_reexports_the_infrastructure_declarative_base():
    """``afterlap_api.db.models.Base`` is a compatibility alias, so identity must hold, not equality."""
    from afterlap_api.db import models as api_models
    from afterlap_infrastructure.persistence import models as infrastructure_models

    assert api_models.Base is infrastructure_models.Base
    assert api_models.Base.metadata is infrastructure_models.Base.metadata


def test_the_alembic_environment_targets_the_one_infrastructure_metadata():
    """The Alembic env's ``target_metadata`` is that same ``MetaData`` object, not a parallel one."""
    from afterlap_infrastructure.persistence import models as infrastructure_models

    module_name, attribute = alembic_metadata_binding()
    location = ALEMBIC_ENV.relative_to(REPO_ROOT).as_posix()
    assert module_name and attribute, (
        f"{location} must bind target_metadata to an imported base's .metadata attribute"
    )

    bound = getattr(importlib.import_module(module_name), attribute)
    assert bound.metadata is infrastructure_models.Base.metadata, (
        f"{location} resolves target_metadata to {module_name}.{attribute}.metadata, "
        "which is not the infrastructure MetaData"
    )


def test_the_application_layer_names_no_concrete_adapter():
    """``WorkerConfig.runtime_builder`` is required precisely so this layer never spells an adapter."""
    root = REPO_ROOT / LAYERS["afterlap_application"].import_root
    forbidden = ("afterlap_api", "afterlap_infrastructure")
    scanned = files_under(root, "")
    assert scanned, f"nothing to scan under {root.relative_to(REPO_ROOT).as_posix()}"

    offenders: list[str] = []
    for path in scanned:
        relative = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            offenders.extend(f"{relative}:{lineno}: names {name}" for name in forbidden if name in line)
    assert not offenders, render("concrete adapters named by the application layer", offenders)
