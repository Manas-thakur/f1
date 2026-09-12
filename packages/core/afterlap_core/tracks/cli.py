"""Track pipeline command line: ``python -m afterlap_core.tracks.cli <command>``.

Subcommands defined by TRACK_DATA_PIPELINE.md. ``registry`` and ``sources`` are
implemented here. ``ingest``, ``compile``, ``validate``, ``ingest-fia`` and
``review-overlay`` dispatch lazily to modules other A16 workers own; when such a
module is not yet importable the command prints
``capability not yet available: <module>`` and exits with status 2. It never
reports success it did not earn.

Exit codes: 0 done, 1 refused (bad input, validation failure, unknown id),
2 capability unavailable.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import urllib.error
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO, cast

from pydantic import ValidationError

from ..paths import Paths
from .provenance import CachedSource, RawSourceCache
from .registry import (
    ManifestRegistryMismatch,
    RegistryEntry,
    SourceManifest,
    load_registry,
    load_source_manifest,
    manifest_path,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_UNAVAILABLE = 2

F1COM_PERMISSION = "reference-only; review terms before redistribution"
FIA_PERMISSION = "FIA public decision document; reference-only"


class CapabilityUnavailable(RuntimeError):
    """A pipeline stage owned by another worker is not importable yet."""

    def __init__(self, module: str, attribute: str | None = None) -> None:
        target = module if attribute is None else f"{module}.{attribute}"
        super().__init__(f"capability not yet available: {target}")
        self.module = module
        self.attribute = attribute


def _capability(module: str, attribute: str) -> Callable[..., Any]:
    """Import ``module`` now and return ``attribute``; an absent module is an explicit unavailability."""
    try:
        loaded = importlib.import_module(module)
    except ImportError as exc:
        raise CapabilityUnavailable(module) from exc
    function = getattr(loaded, attribute, None)
    if function is None or not callable(function):
        raise CapabilityUnavailable(module, attribute)
    return cast("Callable[..., Any]", function)


def _dump(payload: Any, out: TextIO) -> None:
    out.write(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")


def _paths(args: argparse.Namespace) -> Paths:
    root = getattr(args, "root", None)
    return Paths.default(Path(root)) if root else Paths.default()


def _entry_summary(entry: RegistryEntry) -> dict[str, Any]:
    return {
        "track_id": entry.track_id,
        "display_name": entry.display_name,
        "official_length_m": entry.official_length_m.value,
        "length_verified": entry.official_length_m.verified,
        "events": list(entry.event_ids),
        "readiness": entry.readiness.value,
    }


def cmd_registry_list(args: argparse.Namespace, out: TextIO) -> int:
    registry = load_registry(_paths(args), args.season)
    if args.json:
        _dump([_entry_summary(e) for e in registry.entries], out)
        return EXIT_OK
    out.write(
        f"season {registry.season} registry: {len(registry.entries)} circuits "
        f"(snapshot {registry.snapshot_date})\n"
    )
    for entry in registry.entries:
        length = entry.official_length_m
        shown = "unknown" if length.value is None else f"{length.value:.0f} m"
        mark = "verified" if length.verified else "snapshot"
        out.write(
            f"  {entry.track_id:<14} {entry.display_name:<34} {shown:>9} [{mark}]  "
            f"{', '.join(entry.event_ids)}  {entry.readiness.value}\n"
        )
    return EXIT_OK


def cmd_registry_show(args: argparse.Namespace, out: TextIO) -> int:
    registry = load_registry(_paths(args), args.season)
    try:
        entry = registry.get(args.track_id)
    except KeyError as exc:
        out.write(f"refused: {exc.args[0]}\n")
        return EXIT_REFUSED
    _dump(entry.model_dump(mode="json"), out)
    return EXIT_OK


def _record_line(cached: CachedSource) -> dict[str, Any]:
    record = cached.record
    return {
        "source_id": record.source_id,
        "url": record.url,
        "sha256": record.sha256,
        "retrieved_at": record.retrieved_at,
        "priority": record.priority,
        "permission": record.permission,
        "path": str(cached.path),
    }


def fetch_entry_sources(
    entry: RegistryEntry,
    manifest: SourceManifest | None,
    cache: RawSourceCache,
    *,
    refresh: bool = False,
) -> tuple[list[CachedSource], list[dict[str, str]]]:
    """Fetch every URL the registry entry and its manifest declare; return records and failures.

    A failed retrieval is reported, never substituted. The Formula1.com page is
    a priority-5 scale check; FIA documents are priority 1.
    """
    fetched: list[CachedSource] = []
    failures: list[dict[str, str]] = []
    targets: list[tuple[str, str, str, str, str, int, str | None]] = []
    for event in entry.events:
        if event.f1_page:
            targets.append(
                (
                    event.f1_page,
                    "f1com",
                    f"f1com-{event.event_id}",
                    f"Formula1.com circuit page: {event.event_name}",
                    F1COM_PERMISSION,
                    5,
                    None,
                )
            )
    if manifest is not None:
        for document in manifest.fia_documents:
            stem = document.url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            targets.append(
                (
                    document.url,
                    "fia",
                    f"fia-{document.event_id}-{stem}",
                    document.title,
                    FIA_PERMISSION,
                    1,
                    document.event_id,
                )
            )
    for url, source, source_id, title, permission, priority, locator in targets:
        try:
            fetched.append(
                cache.fetch(
                    url,
                    source=source,
                    source_id=source_id,
                    title=title,
                    permission=permission,
                    priority=priority,
                    locator=locator,
                    refresh=refresh,
                )
            )
        except urllib.error.HTTPError as exc:
            failures.append({"url": url, "error": f"HTTP {exc.code}"})
        except (urllib.error.URLError, OSError, ValueError) as exc:
            failures.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
    return fetched, failures


def cmd_sources_fetch(args: argparse.Namespace, out: TextIO) -> int:
    paths = _paths(args)
    registry = load_registry(paths, args.season)
    try:
        entry = registry.get(args.registry_entry)
    except KeyError as exc:
        out.write(f"refused: {exc.args[0]}\n")
        return EXIT_REFUSED
    manifest: SourceManifest | None = None
    if manifest_path(entry.track_id, paths).exists():
        manifest = load_source_manifest(entry.track_id, paths, registry)
    cache = RawSourceCache(paths=paths)
    fetched, failures = fetch_entry_sources(entry, manifest, cache, refresh=args.refresh)
    _dump(
        {
            "track_id": entry.track_id,
            "manifest": None if manifest is None else str(manifest_path(entry.track_id, paths)),
            "records": [_record_line(c) for c in fetched],
            "failures": failures,
        },
        out,
    )
    if not fetched and not failures:
        out.write("nothing to fetch: the entry and its manifest declare no URLs\n")
    return EXIT_REFUSED if failures else EXIT_OK


def cmd_ingest(args: argparse.Namespace, out: TextIO) -> int:
    if args.source != "openf1":
        out.write(f"refused: ingest source {args.source!r} is not implemented; only 'openf1' is declared\n")
        return EXIT_REFUSED
    ingest = _capability("afterlap_core.tracks.ingest.openf1", "ingest_location_session")
    result = ingest(args.session, args.track, _paths(args), driver_number=args.driver)
    _dump(_jsonable(result), out)
    return EXIT_OK


def cmd_compile(args: argparse.Namespace, out: TextIO) -> int:
    compile_track = _capability("afterlap_core.tracks.compile", "compile_track")
    result = compile_track(Path(args.manifest), _paths(args))
    _dump(_jsonable(result), out)
    return EXIT_OK


def cmd_validate(args: argparse.Namespace, out: TextIO) -> int:
    validate_track = _capability("afterlap_core.tracks.validate", "validate_track")
    result = validate_track(args.track, _paths(args))
    _dump(_jsonable(result), out)
    return EXIT_OK


def cmd_ingest_fia(args: argparse.Namespace, out: TextIO) -> int:
    ingest_fia_document = _capability("afterlap_core.tracks.fia_overlay", "ingest_fia_document")
    document: Path | str = args.document if "://" in args.document else Path(args.document)
    result = ingest_fia_document(args.track, args.event, document, _paths(args))
    _dump(_jsonable(result), out)
    return EXIT_OK


def cmd_review_overlay(args: argparse.Namespace, out: TextIO) -> int:
    review_overlay = _capability("afterlap_core.tracks.fia_overlay", "review_overlay")
    result = review_overlay(args.track, args.event, args.reviewer, args.decision, _paths(args))
    _dump(_jsonable(result), out)
    return EXIT_OK


def _jsonable(result: Any) -> Any:
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    if hasattr(result, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m afterlap_core.tracks.cli",
        description="AFTERLAP track pipeline (real circuits, synthetic energy).",
    )
    parser.add_argument("--root", help="Implementation root (default: AFTERLAP_ROOT or the workspace).")
    parser.add_argument("--season", type=int, default=2026, help="Registry season (default 2026).")
    sub = parser.add_subparsers(dest="command", required=True)

    registry = sub.add_parser("registry", help="Inspect the circuit registry.")
    registry_sub = registry.add_subparsers(dest="registry_command", required=True)
    p_list = registry_sub.add_parser("list", help="List every registered circuit.")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_registry_list)
    p_show = registry_sub.add_parser("show", help="Show one registry entry as JSON.")
    p_show.add_argument("track_id")
    p_show.set_defaults(func=cmd_registry_show)

    sources = sub.add_parser("sources", help="Raw source retrieval into the provenance cache.")
    sources_sub = sources.add_subparsers(dest="sources_command", required=True)
    p_fetch = sources_sub.add_parser(
        "fetch", help="Fetch the Formula1.com and FIA URLs declared for a registry entry."
    )
    p_fetch.add_argument("--registry-entry", required=True, metavar="TRACK_ID")
    p_fetch.add_argument("--refresh", action="store_true", help="Fetch again even when a cached copy exists.")
    p_fetch.set_defaults(func=cmd_sources_fetch)

    p_ingest = sub.add_parser("ingest", help="Ingest OpenF1 location telemetry for one session.")
    p_ingest.add_argument("--source", default="openf1")
    p_ingest.add_argument("--session", type=int, required=True)
    p_ingest.add_argument("--track", required=True)
    p_ingest.add_argument("--driver", type=int, default=None)
    p_ingest.set_defaults(func=cmd_ingest)

    p_compile = sub.add_parser("compile", help="Compile a metric track package from a source manifest.")
    p_compile.add_argument("--manifest", required=True)
    p_compile.set_defaults(func=cmd_compile)

    p_validate = sub.add_parser("validate", help="Validate a compiled package and derive its readiness.")
    p_validate.add_argument("--track", required=True)
    p_validate.set_defaults(func=cmd_validate)

    p_fia = sub.add_parser("ingest-fia", help="Queue an FIA event document for two-reviewer transcription.")
    p_fia.add_argument("--track", required=True)
    p_fia.add_argument("--event", required=True)
    p_fia.add_argument("--document", required=True, help="Local path or URL of the FIA PDF.")
    p_fia.set_defaults(func=cmd_ingest_fia)

    p_review = sub.add_parser("review-overlay", help="Record one reviewer's decision on an event overlay.")
    p_review.add_argument("--track", required=True)
    p_review.add_argument("--event", required=True)
    p_review.add_argument("--reviewer", required=True)
    p_review.add_argument("--decision", required=True, choices=("pass", "fail", "unknown"))
    p_review.set_defaults(func=cmd_review_overlay)
    return parser


def main(argv: Sequence[str] | None = None, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args, out))
    except CapabilityUnavailable as exc:
        out.write(f"{exc}\n")
        return EXIT_UNAVAILABLE
    except ManifestRegistryMismatch as exc:
        out.write(f"refused: {exc}\n")
        return EXIT_REFUSED
    except (ValidationError, FileNotFoundError, ValueError, KeyError) as exc:
        out.write(f"refused: {exc}\n")
        return EXIT_REFUSED


__all__ = [
    "EXIT_OK",
    "EXIT_REFUSED",
    "EXIT_UNAVAILABLE",
    "CapabilityUnavailable",
    "build_parser",
    "fetch_entry_sources",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
