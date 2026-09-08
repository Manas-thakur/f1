"""FIA event-overlay ingestion and the two-reviewer review queue (A16-3).

``ingest_fia_document`` caches a Power Unit Information decision document
through :class:`RawSourceCache`, extracts its text with ``pypdf`` and parses
*candidate* values into an :class:`EventOverlay` draft with
``review_status="unreviewed"``. Nothing the parser produces is ever treated as
a rule: :func:`overlay_effective_values` returns ``None`` for every numeric
field until two distinct reviewers have confirmed the overlay against the same
hashed document, and the rules engine consumes those ``None`` values as
*unknown*.

What the parser does and does not read from the 2026 documents seen so far
(Miami R04, Monaco R06, Belgium R10, Italy R13):

* Recharge-per-lap row, Power Limited Distance and Rate Limit -- text.
* Detection / activation lines (lap distance, loop labels, TBC flags) -- text.
* Lap-distance windows of the power-reduction exception sectors and the main
  overtaking zones with their speed thresholds -- text, kept as candidates in
  the extraction sidecar.
* The MGU-K power curves -- rendered as a **chart**; only axis ticks and legend
  names reach the text layer. They are reported as unknown, never guessed.
  A tabular curve (``vCar (km/h)  MGUK DC Power (kW)`` header followed by
  two-number rows) is parsed when a document carries one.
* Race laps and straight-mode ranges are not defined by a Power Unit
  Information document and stay unknown.

Every heuristic that relies on text order is written into the sidecar as a
``parser_assumptions`` entry so the reviewers know what to check.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..paths import Paths, atomic_write_json
from .loader import event_overlay_path, load_event_overlay
from .package import EventOverlay, PowerCurveRow, SourceRecord, SRange
from .provenance import CachedSource, RawSourceCache

PARSER_VERSION = "a16-3.1"

FIA_PERMISSION = "FIA public decision document; used for factual event parameters, no artwork reproduced"

RECHARGE_COLUMNS = (
    "race_overtake_not_active",
    "race_overtake_active",
    "qualifying",
    "free_practice",
    "out_laps_other_than_race",
)
"""Column order of the Maximum Recharge per lap row in the 2026 PUI layout."""

NUMERIC_FIELDS = (
    "detection_lines_m",
    "activation_lines_m",
    "straight_mode_ranges",
    "standard_curve",
    "overtake_curve",
    "recharge_allowance_mj",
    "race_laps",
)

_RE_CENTRELINE = re.compile(r"CENTRELINE\s+(\d+(?:\.\d+)?)\s*km", re.IGNORECASE)
_RE_ROUND = re.compile(r"ROUND\s+No\.?\s*(R\d+)", re.IGNORECASE)
_RE_VENUE = re.compile(r"^VENUE\s+(.+)$", re.IGNORECASE | re.MULTILINE)
_RE_FORMAT = re.compile(r"^FORMAT\s+(.+)$", re.IGNORECASE | re.MULTILINE)
_RE_DOCUMENT = re.compile(r"^Document\s+(\d+)\s*$", re.MULTILINE)
_RE_DATE = re.compile(r"^Date\s+(.+)$", re.MULTILINE)
_RE_RECHARGE_ROW = re.compile(r"((?:\d+(?:\.\d+)?\s*MJ\s*){2,})(?:(\d{3,5})\s*m\s+(\d+(?:\.\d+)?)\s*kW/s)?")
_RE_MJ = re.compile(r"(\d+(?:\.\d+)?)\s*MJ")
_RE_LINE_M = re.compile(r"(?<![\d.])(\d{3,5})\s*m(?![A-Za-z])(\s*\(TBC\))?", re.IGNORECASE)
_RE_LOOP = re.compile(r"\(?\b(L\d+(?:/SC\d+)?)\b\)?")
_RE_GAP_S = re.compile(r"(\d+\.\d+)\s*s(?![A-Za-z])")
_RE_WINDOW = re.compile(r"(\[)?(\d{3,5})-(\d{3,5})(\])?")
_RE_KMH = re.compile(r"(\d{2,3})\s*km/h")
_RE_NO_SECTORS = re.compile(r"^-\s+-\s+-", re.MULTILINE)
_RE_CURVE_HEADER = re.compile(r"km/h.*kW|kW.*km/h", re.IGNORECASE)
_RE_TWO_NUMBERS = re.compile(r"^\s*(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*$")
_RE_LEGEND = re.compile(r"^((?:Base|Rev\s*\d+|Alt\s*\d+)(?:\s*-\s*(?:Standard|Overtake))?)\s*$", re.MULTILINE)
_RE_RACE_LAPS = re.compile(r"(?:Race\s+laps|Number\s+of\s+laps)\s*[:=]?\s*(\d{1,3})", re.IGNORECASE)


@dataclass
class ParsedPui:
    """Candidate values read from a Power Unit Information document's text."""

    round_no: str | None = None
    venue: str | None = None
    format: str | None = None
    document_number: str | None = None
    document_date: str | None = None
    centreline_km: float | None = None
    recharge_row_mj: list[float] = field(default_factory=list)
    recharge_by_column_mj: dict[str, float] = field(default_factory=dict)
    power_limited_distance_m: float | None = None
    power_reduction_rate_kw_per_s: float | None = None
    detection_gap_s: float | None = None
    detection_line_m: float | None = None
    activation_line_m: float | None = None
    detection_line_tbc: bool = False
    activation_line_tbc: bool = False
    loop_labels: list[str] = field(default_factory=list)
    lap_distance_windows: list[dict[str, Any]] = field(default_factory=list)
    main_overtaking_zones: list[dict[str, Any]] | None = None
    speed_thresholds_kph: list[float] = field(default_factory=list)
    curve_legend: list[str] = field(default_factory=list)
    curves: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    race_laps: int | None = None
    unknown: dict[str, str] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# text extraction and parsing
# --------------------------------------------------------------------------- #


def extract_pdf_text(data: bytes) -> list[str]:
    """Per-page text via pypdf. Replacement glyphs from the FIA header font become spaces."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        text = text.replace("�", " ").replace("\xa0", " ")
        pages.append(text)
    return pages


def parse_pui_text(text: str) -> ParsedPui:
    """Parse candidate values from the concatenated text of a PUI document."""
    parsed = ParsedPui()
    lines = [ln.rstrip() for ln in text.splitlines()]

    if m := _RE_ROUND.search(text):
        parsed.round_no = m.group(1)
    if m := _RE_VENUE.search(text):
        parsed.venue = m.group(1).strip()
    if m := _RE_FORMAT.search(text):
        parsed.format = m.group(1).strip()
    if m := _RE_DOCUMENT.search(text):
        parsed.document_number = m.group(1)
    if m := _RE_DATE.search(text):
        parsed.document_date = m.group(1).strip()
    if m := _RE_CENTRELINE.search(text):
        parsed.centreline_km = float(m.group(1))

    remainder = _parse_recharge(text, parsed)
    _parse_lines(remainder, parsed)
    _parse_windows(lines, parsed)
    _parse_curves(lines, text, parsed)

    if m := _RE_RACE_LAPS.search(text):
        parsed.race_laps = int(m.group(1))
    else:
        parsed.unknown["race_laps"] = "not stated in a Power Unit Information document"
    parsed.unknown["straight_mode_ranges"] = (
        "not defined by a Power Unit Information document; source is the event circuit map / "
        "competition notes. Main overtaking zones are kept as candidates in the extraction sidecar."
    )
    return parsed


def _parse_recharge(text: str, parsed: ParsedPui) -> str:
    """Read the recharge row; return the text with that row blanked out."""
    m = _RE_RECHARGE_ROW.search(text)
    if m is None:
        parsed.unknown["recharge_allowance_mj"] = "no 'x MJ' row found"
        return text
    values = [float(v) for v in _RE_MJ.findall(m.group(1))]
    parsed.recharge_row_mj = values
    if len(values) == len(RECHARGE_COLUMNS):
        parsed.recharge_by_column_mj = dict(zip(RECHARGE_COLUMNS, values, strict=True))
        parsed.assumptions.append(
            "recharge row columns assumed in 2026 layout order: " + ", ".join(RECHARGE_COLUMNS)
        )
    else:
        parsed.assumptions.append(
            f"recharge row holds {len(values)} values, expected {len(RECHARGE_COLUMNS)}; "
            "column mapping not applied"
        )
    if m.group(2):
        parsed.power_limited_distance_m = float(m.group(2))
    if m.group(3):
        parsed.power_reduction_rate_kw_per_s = float(m.group(3))
    return text[: m.start()] + " " * (m.end() - m.start()) + text[m.end() :]


def _parse_lines(text: str, parsed: ParsedPui) -> None:
    hits = [(float(m.group(1)), bool(m.group(2))) for m in _RE_LINE_M.finditer(text)]
    parsed.loop_labels = [m.group(1) for m in _RE_LOOP.finditer(text)]
    if m := _RE_GAP_S.search(text):
        parsed.detection_gap_s = float(m.group(1))
    if len(hits) == 2:
        (
            (parsed.detection_line_m, parsed.detection_line_tbc),
            (
                parsed.activation_line_m,
                parsed.activation_line_tbc,
            ),
        ) = hits
        parsed.assumptions.append(
            "of the two lap-distance line values, the first in text order is the Detection Line and the "
            "second the Activation Line (label order in the document); reviewers confirm against the page"
        )
    elif len(hits) == 0:
        parsed.unknown["detection_lines_m"] = "no lap-distance line value found"
        parsed.unknown["activation_lines_m"] = "no lap-distance line value found"
    else:
        found = ", ".join(f"{v:g} m" for v, _ in hits)
        parsed.unknown["detection_lines_m"] = f"{len(hits)} line values found, cannot assign: {found}"
        parsed.unknown["activation_lines_m"] = parsed.unknown["detection_lines_m"]


def _parse_windows(lines: list[str], parsed: ParsedPui) -> None:
    window_lines: list[tuple[int, list[dict[str, Any]]]] = []
    for idx, line in enumerate(lines):
        found = [
            {"start_m": float(m.group(2)), "end_m": float(m.group(3)), "qualifying_only": bool(m.group(1))}
            for m in _RE_WINDOW.finditer(line)
        ]
        if found:
            window_lines.append((idx, found))
            parsed.lap_distance_windows.extend(found)

    kmh_lines = [idx for idx, line in enumerate(lines) if _RE_KMH.search(line)]
    parsed.speed_thresholds_kph = [float(v) for line in lines for v in _RE_KMH.findall(line)]
    if kmh_lines:
        # Walk back from the first speed-threshold line over consecutive window lines.
        first = kmh_lines[0]
        zones: list[dict[str, Any]] = []
        cursor = first - 1
        by_index = dict(window_lines)
        while cursor >= 0 and cursor in by_index:
            zones = by_index[cursor] + zones
            cursor -= 1
        if zones and len(zones) == len(parsed.speed_thresholds_kph):
            parsed.main_overtaking_zones = [
                {**zone, "speed_threshold_kph": kph}
                for zone, kph in zip(zones, parsed.speed_thresholds_kph, strict=True)
            ]
            parsed.assumptions.append(
                "main overtaking zones taken as the lap-distance windows immediately preceding the km/h "
                "speed thresholds in text order"
            )
        else:
            parsed.unknown["main_overtaking_zones"] = (
                f"{len(zones)} windows precede {len(parsed.speed_thresholds_kph)} speed thresholds"
            )
    elif _RE_NO_SECTORS.search("\n".join(lines)):
        parsed.main_overtaking_zones = []
        parsed.assumptions.append("a '- - -' row is read as 'no main overtaking zones defined'")
    else:
        parsed.unknown["main_overtaking_zones"] = "neither speed thresholds nor a '- - -' row found"


def _parse_curves(lines: list[str], text: str, parsed: ParsedPui) -> None:
    parsed.curve_legend = sorted({m.group(1).strip() for m in _RE_LEGEND.finditer(text)})
    idx = 0
    while idx < len(lines):
        header = lines[idx]
        if _RE_CURVE_HEADER.search(header):
            name = (
                "standard"
                if "standard" in header.lower()
                else "overtake"
                if "overtake" in header.lower()
                else None
            )
            rows: list[tuple[float, float]] = []
            cursor = idx + 1
            while cursor < len(lines) and (m := _RE_TWO_NUMBERS.match(lines[cursor])):
                rows.append((float(m.group(1)), float(m.group(2))))
                cursor += 1
            if name is not None and len(rows) >= 2:
                parsed.curves[name] = rows
            idx = cursor
            continue
        idx += 1
    for name in ("standard", "overtake"):
        if name not in parsed.curves:
            parsed.unknown[f"{name}_curve"] = (
                "power curve is rendered as a chart; only axis ticks and legend names "
                f"({', '.join(parsed.curve_legend) or 'none'}) reach the text layer"
            )


# --------------------------------------------------------------------------- #
# overlay construction
# --------------------------------------------------------------------------- #


def draft_overlay(event_id: str, parsed: ParsedPui, document: SourceRecord) -> EventOverlay:
    """An unreviewed overlay from parsed candidates. Unparsed fields are listed, not zeroed."""
    unknown: dict[str, str] = dict(parsed.unknown)
    detection = () if parsed.detection_line_m is None else (parsed.detection_line_m,)
    activation = () if parsed.activation_line_m is None else (parsed.activation_line_m,)
    if parsed.detection_line_tbc:
        unknown["detection_lines_m"] = "document marks the detection line TBC"
    if parsed.activation_line_tbc:
        unknown["activation_lines_m"] = "document marks the activation line TBC"

    recharge: float | None = None
    if parsed.recharge_by_column_mj:
        recharge = parsed.recharge_by_column_mj[RECHARGE_COLUMNS[0]]
    elif parsed.recharge_row_mj:
        recharge = parsed.recharge_row_mj[0]
        unknown["recharge_allowance_mj"] = "column mapping unresolved; first value taken as candidate"

    standard = tuple(PowerCurveRow(speed_kph=v, power_kw=p) for v, p in parsed.curves.get("standard", []))
    overtake = tuple(PowerCurveRow(speed_kph=v, power_kw=p) for v, p in parsed.curves.get("overtake", []))

    payload = {
        "document_sha256": document.sha256,
        "detection_lines_m": detection,
        "activation_lines_m": activation,
        "recharge_allowance_mj": recharge,
        "standard_curve": [(r.speed_kph, r.power_kw) for r in standard],
        "overtake_curve": [(r.speed_kph, r.power_kw) for r in overtake],
        "race_laps": parsed.race_laps,
    }
    ruleset_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=list).encode()).hexdigest()
    return EventOverlay(
        event_id=event_id,
        ruleset_hash=ruleset_hash,
        fia_documents=(document,),
        detection_lines_m=detection,
        activation_lines_m=activation,
        straight_mode_ranges=(),
        standard_curve=standard,
        overtake_curve=overtake,
        recharge_allowance_mj=recharge,
        race_laps=parsed.race_laps,
        review_status="unreviewed",
        reviewers=(),
        unknown_fields=tuple(f"{k}: {v}" for k, v in sorted(unknown.items())),
    )


def _cache_document(document: Path | str, event_id: str, cache: RawSourceCache) -> CachedSource:
    title = f"{event_id} Power Unit Information (FIA decision document)"
    source_id = f"fia-pui-{event_id}"
    if isinstance(document, str) and document.lower().startswith(("http://", "https://")):
        return cache.fetch(
            document,
            source="fia",
            source_id=source_id,
            title=title,
            permission=FIA_PERMISSION,
            priority=1,
        )
    path = Path(document)
    if not path.exists():
        raise FileNotFoundError(f"FIA document {path} does not exist")
    return cache.put(
        path.read_bytes(),
        source="fia",
        source_id=source_id,
        title=title,
        url=path.resolve().as_uri(),
        permission=FIA_PERMISSION,
        priority=1,
        content_type="application/pdf",
        filename="document.pdf",
    )


def ingest_fia_document(track_id: str, event_id: str, document: Path | str, paths: Paths) -> EventOverlay:
    """Cache, extract, parse and queue a Power Unit Information document as a draft overlay.

    Writes ``events/<event_id>.json`` (the :class:`EventOverlay`, unreviewed) and
    ``events/<event_id>.extraction.json`` (page text, parsed candidates, parser
    assumptions) so reviewers can check every number against the hashed
    document. A previously queued overlay built from a different document is
    moved aside as ``<event_id>.superseded-<sha12>.json``; a revised document
    always restarts review.
    """
    cache = RawSourceCache(paths=paths)
    cached = _cache_document(document, event_id, cache)
    data = cached.read_bytes()
    pages = extract_pdf_text(data)
    parsed = parse_pui_text("\n".join(pages))
    record = cached.record.model_copy(
        update={"locator": f"pages 1-{len(pages)}", "document_revision": parsed.document_number}
    )
    overlay = draft_overlay(event_id, parsed, record)

    target = event_overlay_path(track_id, event_id, paths)
    superseded: str | None = None
    if target.exists():
        previous = EventOverlay.model_validate(json.loads(target.read_text(encoding="utf-8")))
        previous_sha = previous.fia_documents[0].sha256 if previous.fia_documents else None
        if previous_sha != record.sha256:
            aside = target.with_name(f"{event_id}.superseded-{(previous_sha or 'nohash')[:12]}.json")
            target.replace(aside)
            superseded = aside.name
    overlay = overlay.with_hash()
    atomic_write_json(target, overlay.model_dump(mode="json"))
    atomic_write_json(
        target.with_name(f"{event_id}.extraction.json"),
        {
            "parser_version": PARSER_VERSION,
            "track_id": track_id,
            "event_id": event_id,
            "document": record.model_dump(mode="json"),
            "content_type": cached.content_type,
            "bytes": len(data),
            "page_count": len(pages),
            "page_text": pages,
            "parsed": asdict(parsed),
            "superseded_overlay": superseded,
            "review_status": overlay.review_status,
            "note": "DRAFT. Every value is a parser candidate until two distinct reviewers confirm it.",
        },
    )
    return overlay


# --------------------------------------------------------------------------- #
# review queue
# --------------------------------------------------------------------------- #


def review_overlay(track_id: str, event_id: str, reviewer: str, decision: str, paths: Paths) -> EventOverlay:
    """Record one reviewer's decision on the queued overlay.

    ``confirm`` appends the reviewer; the status becomes ``one_reviewer`` with one
    distinct name and ``confirmed`` only with two distinct names. The same name
    twice does not advance the status. ``reject`` recalls the overlay; a recalled
    overlay accepts no further review and must be re-ingested.
    """
    name = reviewer.strip()
    if not name:
        raise ValueError("reviewer name must not be empty")
    if decision not in {"confirm", "reject"}:
        raise ValueError(f"decision must be 'confirm' or 'reject', got {decision!r}")
    overlay = load_event_overlay(track_id, event_id, paths)
    if overlay.review_status == "recalled":
        raise ValueError(f"event overlay {event_id!r} is recalled; re-ingest the document to review it again")

    reviewers = overlay.reviewers if name in overlay.reviewers else (*overlay.reviewers, name)
    if decision == "reject":
        status = "recalled"
    else:
        distinct = len(set(reviewers))
        status = "confirmed" if distinct >= 2 else "one_reviewer"
    updated = overlay.model_copy(update={"reviewers": reviewers, "review_status": status})

    target = event_overlay_path(track_id, event_id, paths)
    updated = updated.with_hash()
    atomic_write_json(target, updated.model_dump(mode="json"))
    log = target.with_name(f"{event_id}.reviews.jsonl")
    entry = {
        "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "reviewer": name,
        "decision": decision,
        "document_sha256": overlay.fia_documents[0].sha256 if overlay.fia_documents else None,
        "ruleset_hash": overlay.ruleset_hash,
        "status_after": status,
        "no_change": reviewers == overlay.reviewers and status == overlay.review_status,
    }
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return updated


def overlay_effective_values(overlay: EventOverlay) -> dict[str, Any]:
    """The values the rules engine may use. Everything numeric is ``None`` unless confirmed.

    Fields the reviewers listed in ``unknown_fields`` stay ``None`` even on a
    confirmed overlay: unknown is never a permission.
    """
    values: dict[str, Any] = {
        "event_id": overlay.event_id,
        "review_status": overlay.review_status,
        "confirmed": overlay.is_confirmed,
    }
    unknown_names = {entry.split(":", 1)[0].strip() for entry in overlay.unknown_fields}
    for name in NUMERIC_FIELDS:
        if not overlay.is_confirmed or name in unknown_names:
            values[name] = None
            continue
        raw = getattr(overlay, name)
        # A confirmed empty tuple is knowledge ("none defined"), so it stays a list.
        values[name] = [_plain(item) for item in raw] if isinstance(raw, tuple) else raw
    return values


def _plain(item: Any) -> Any:
    if isinstance(item, SRange):
        return (item.start_s_m, item.end_s_m)
    if isinstance(item, PowerCurveRow):
        return (item.speed_kph, item.power_kw)
    return item


__all__ = [
    "FIA_PERMISSION",
    "NUMERIC_FIELDS",
    "PARSER_VERSION",
    "RECHARGE_COLUMNS",
    "ParsedPui",
    "draft_overlay",
    "extract_pdf_text",
    "ingest_fia_document",
    "overlay_effective_values",
    "parse_pui_text",
    "review_overlay",
]
