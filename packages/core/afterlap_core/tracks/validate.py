"""Independent geometry validation and evidence-derived readiness (A16-3).

``validate_track`` re-derives every geometric quantity from the raw ``x, y, z``
samples in the compiled centreline file and compares them with what the
compiler declared. It never reuses the compiler's own closure, length, yaw or
curvature numbers as evidence: the point of the check is that two independent
computations agree.

The readiness rung is *computed* from the check outcomes (VALIDATION.md,
TRACK_REGISTRY_2026.md) and written back into ``package.json`` with a
recomputed ``package_hash``. A hand-edited status is refused twice: the
``TrackPackage`` validator rejects it on load, and this module only ever writes
the rung the evidence supports.

Ladder as implemented here:

* ``rejected`` -- an integrity failure: the arrays hash does not match, a
  required array holds a non-finite value, ``s`` is not monotonic at the
  declared spacing, yaw disagrees with the tangent, curvature disagrees with the
  yaw derivative, curvature or grade exceed physical bounds, or the declared
  direction contradicts the signed area.
* ``discovered`` -- integrity holds but the package is not yet publishable:
  closure or length disagree with the reference beyond tolerance, no source is
  hash-pinned, or a required check could not be evaluated.
* ``geometry_validated`` -- every geometry check passes.
* ``event_rules_validated`` -- plus a two-reviewer *confirmed* event overlay
  under ``events/``.
* ``condition_calibrated`` -- plus a conditions calibration report at
  ``conditions/calibration.json`` whose ``status`` is ``calibrated`` and which
  names at least one source session. This module does not produce that file;
  the conditions worker does.
* ``simulation_eligible`` -- plus a surveyed or validated corridor with finite
  half-widths in the arrays.

Nothing here can skip a rung.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..paths import Paths, atomic_write_json
from .loader import (
    TrackPackageError,
    centreline_path,
    load_event_overlay,
    package_dir,
    package_path,
)
from .package import (
    CorridorQuality,
    Direction,
    EventOverlay,
    ReadinessStatus,
    TrackPackage,
    ValidationReport,
)

VALIDATOR_VERSION = "a16-3.1"

CLOSURE_TOLERANCE_M = 0.5
"""VALIDATION.md: closure error below 0.5 m after periodic fitting."""

LENGTH_TOLERANCE_FRACTION_DEFAULT = 0.005
"""Brief default (0.5 %) unless the source manifest declares another value."""

CURVATURE_BOUND_1PM = 1.0 / 6.0
"""|kappa| above 1/6 m^-1 (a 6 m radius) is not a racing centreline."""

GRADE_BOUND = 0.25

YAW_TANGENT_TOLERANCE_RAD = 0.05
"""Max |yaw - atan2(dy, dx)| over the lap, central differences on 1 m samples."""

CURVATURE_YAW_TOLERANCE_1PM = 0.005
"""Max |kappa - d(yaw)/ds| over the lap (an error equivalent to a 200 m radius)."""

SPACING_TOLERANCE_M = 1e-6

REQUIRED_ARRAYS = ("s_m", "x_m", "y_m", "z_m", "yaw_rad", "curvature_1pm", "grade_rad")

_INTEGRITY_CHECKS = (
    "arrays_sha256",
    "no_nan",
    "s_monotonic_spacing",
    "yaw_tangent",
    "curvature_yaw",
    "curvature_bounded",
    "grade_bounded",
    "direction",
)
_PUBLICATION_CHECKS = ("closure", "length_declared", "length_official", "sources_hashed")
GEOMETRY_CHECKS = _INTEGRITY_CHECKS + _PUBLICATION_CHECKS

REPORT_FILENAME = "validation_report.json"
CONDITIONS_REPORT_RELATIVE = Path("conditions") / "calibration.json"


@dataclass
class _Evidence:
    """Everything the validator measured, before it is reduced to a status."""

    checks: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    numbers: dict[str, Any] = field(default_factory=dict)

    def record(self, check: str, outcome: str, note: str | None = None) -> None:
        if outcome not in {"pass", "fail", "unknown"}:
            raise ValueError(f"check outcome must be pass|fail|unknown, got {outcome!r}")
        self.checks[check] = outcome
        if note:
            self.notes.append(f"{check}: {note}")


def validate_track(track_id: str, paths: Paths) -> TrackPackage:
    """Validate the compiled package for ``track_id`` and re-freeze it.

    Reads ``artifacts/tracks/<track_id>/package.json`` and ``centreline.npz``,
    runs the independent checks, writes ``validation_report.json`` and rewrites
    ``package.json`` with the evidence-derived validation block and a new
    ``package_hash``. Returns the frozen package.
    """
    package = _load_package_for_validation(track_id, paths)
    directory = package_dir(track_id, paths)
    arrays_file = centreline_path(track_id, paths)
    evidence = _Evidence()
    manifest = _read_manifest(track_id, paths)

    tolerance = _length_tolerance(manifest, evidence)
    official_length_m, official_source = _official_length(package, manifest)
    evidence.numbers["official_length_m"] = official_length_m
    evidence.numbers["official_length_source"] = official_source
    evidence.numbers["length_tolerance_fraction"] = tolerance

    arrays = _load_arrays(arrays_file, package, evidence)
    closure_error_m: float | None = None
    length_error_fraction: float | None = None
    corridor_known = False
    if arrays is not None:
        closure_error_m, length_error_fraction, corridor_known = _run_geometry_checks(
            arrays, package, official_length_m, tolerance, evidence
        )
    else:
        for check in GEOMETRY_CHECKS:
            evidence.checks.setdefault(check, "unknown")

    _check_sources(package, evidence)
    overlay = _confirmed_overlay(track_id, package, paths, evidence)
    conditions_ok = _conditions_calibrated(directory, evidence)
    _check_corridor(package, corridor_known, evidence)

    status = _derive_status(evidence, overlay, conditions_ok, corridor_known)
    evidence.numbers["derived_status"] = status.value

    report = ValidationReport(
        status=status,
        closure_error_m=closure_error_m,
        length_error_fraction=length_error_fraction,
        report_path=REPORT_FILENAME,
        official_length_m=official_length_m,
        checks=dict(sorted(evidence.checks.items())),
        notes=tuple(evidence.notes),
    )
    update: dict[str, Any] = {"validation": report, "package_hash": None}
    if overlay is not None:
        update["event_overlay"] = overlay
    validated = package.model_copy(update=update).with_hash()

    report_payload = {
        "validator_version": VALIDATOR_VERSION,
        "track_id": track_id,
        "status": status.value,
        "checks": report.checks,
        "notes": list(report.notes),
        "numbers": evidence.numbers,
        "tolerances": {
            "closure_m": CLOSURE_TOLERANCE_M,
            "length_fraction": tolerance,
            "curvature_bound_1pm": CURVATURE_BOUND_1PM,
            "grade_bound": GRADE_BOUND,
            "yaw_tangent_rad": YAW_TANGENT_TOLERANCE_RAD,
            "curvature_yaw_1pm": CURVATURE_YAW_TOLERANCE_1PM,
            "spacing_m": SPACING_TOLERANCE_M,
        },
        "package_hash_before": package.package_hash,
        "package_hash_after": validated.package_hash,
        "event_overlay_embedded": None if overlay is None else overlay.event_id,
    }
    atomic_write_json(directory / REPORT_FILENAME, report_payload)
    atomic_write_json(package_path(track_id, paths), validated.to_schema_dict())
    return validated


def _load_package_for_validation(track_id: str, paths: Paths) -> TrackPackage:
    path = package_path(track_id, paths)
    if not path.exists():
        raise TrackPackageError(f"no compiled package for {track_id!r} at {path}")
    package = TrackPackage.model_validate(json.loads(path.read_text(encoding="utf-8")))
    if package.track_id != track_id:
        raise TrackPackageError(f"package at {path} declares track_id {package.track_id!r}, not {track_id!r}")
    if package.package_hash is not None and package.content_hash() != package.package_hash:
        raise TrackPackageError(
            f"package for {track_id!r} failed hash verification before validation; refusing to validate "
            "an edited document"
        )
    return package


def _read_manifest(track_id: str, paths: Paths) -> dict[str, Any]:
    path = paths.configs / "tracks" / track_id / "source.yaml"
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError:  # pragma: no cover - pyyaml is a workspace dependency
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _length_tolerance(manifest: dict[str, Any], evidence: _Evidence) -> float:
    declared = manifest.get("length_tolerance_fraction")
    if isinstance(declared, int | float) and 0.0 < float(declared) < 0.1:
        evidence.notes.append(f"length tolerance {float(declared):.4f} taken from source manifest")
        return float(declared)
    return LENGTH_TOLERANCE_FRACTION_DEFAULT


def _official_length(package: TrackPackage, manifest: dict[str, Any]) -> tuple[float | None, str]:
    block = manifest.get("official_length_m")
    if isinstance(block, dict):
        value = block.get("value")
        if isinstance(value, int | float) and float(value) > 0.0:
            return float(value), f"manifest:{block.get('source_url') or 'unstated'}"
    elif isinstance(block, int | float) and float(block) > 0.0:
        return float(block), "manifest"
    if package.validation.official_length_m is not None:
        return float(package.validation.official_length_m), "package.validation.official_length_m"
    return None, "none"


def _load_arrays(path: Path, package: TrackPackage, evidence: _Evidence) -> dict[str, np.ndarray] | None:
    if not path.exists():
        evidence.record("arrays_sha256", "unknown", f"no centreline file at {path.name}")
        return None
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    evidence.numbers["arrays_sha256_file"] = actual
    if package.geometry.arrays_sha256 is None:
        evidence.record(
            "arrays_sha256", "fail", "package records no arrays_sha256; the arrays are not pinned"
        )
    elif actual != package.geometry.arrays_sha256:
        evidence.record(
            "arrays_sha256",
            "fail",
            f"package records {package.geometry.arrays_sha256[:12]}, file is {actual[:12]}",
        )
    else:
        evidence.record("arrays_sha256", "pass")
    with np.load(path) as data:
        arrays = {name: np.asarray(data[name], dtype=np.float64) for name in data.files}
    missing = [name for name in REQUIRED_ARRAYS if name not in arrays]
    if missing:
        evidence.record("no_nan", "fail", f"required arrays missing: {', '.join(missing)}")
        return None
    lengths = {len(arrays[name]) for name in REQUIRED_ARRAYS}
    if len(lengths) != 1:
        evidence.record("no_nan", "fail", "required arrays do not share one length")
        return None
    return arrays


def _run_geometry_checks(
    arrays: dict[str, np.ndarray],
    package: TrackPackage,
    official_length_m: float | None,
    tolerance: float,
    evidence: _Evidence,
) -> tuple[float | None, float | None, bool]:
    s = arrays["s_m"]
    x, y, z = arrays["x_m"], arrays["y_m"], arrays["z_m"]
    yaw, kappa, grade = arrays["yaw_rad"], arrays["curvature_1pm"], arrays["grade_rad"]
    n = len(s)
    evidence.numbers["point_count"] = n

    non_finite = [name for name in REQUIRED_ARRAYS if not np.all(np.isfinite(arrays[name]))]
    if non_finite:
        evidence.record("no_nan", "fail", f"non-finite values in {', '.join(non_finite)}")
        for check in GEOMETRY_CHECKS:
            if check not in evidence.checks:
                evidence.checks[check] = "unknown"
        return None, None, False
    evidence.record("no_nan", "pass")
    if n < 4:
        evidence.record("s_monotonic_spacing", "fail", f"only {n} samples")
        for check in GEOMETRY_CHECKS:
            evidence.checks.setdefault(check, "unknown")
        return None, None, False

    declared_length = float(arrays["length_m"][0]) if "length_m" in arrays else None
    evidence.numbers["declared_length_m"] = declared_length
    evidence.numbers["nominal_length_m"] = package.nominal_length_m
    if package.geometry.point_count not in (0, n):
        evidence.notes.append(f"package declares {package.geometry.point_count} points, file holds {n}")

    spacing = package.geometry.sample_spacing_m
    ds = np.diff(s)
    spacing_ok = (
        s[0] == 0.0
        and bool(np.all(ds > 0.0))
        and bool(np.all(np.abs(ds - spacing) <= SPACING_TOLERANCE_M))
        and (declared_length is None or s[-1] < declared_length)
    )
    evidence.numbers["spacing_max_deviation_m"] = float(np.max(np.abs(ds - spacing)))
    evidence.record(
        "s_monotonic_spacing",
        "pass" if spacing_ok else "fail",
        None
        if spacing_ok
        else f"s must start at 0, increase by {spacing} m each sample and end before length",
    )

    seg = np.sqrt(np.diff(x) ** 2 + np.diff(y) ** 2 + np.diff(z) ** 2)
    closing = math.sqrt((x[0] - x[-1]) ** 2 + (y[0] - y[-1]) ** 2 + (z[0] - z[-1]) ** 2)
    recomputed_length = float(np.sum(seg) + closing)
    evidence.numbers["recomputed_length_m"] = recomputed_length

    length_error_fraction: float | None = None
    if declared_length is None:
        evidence.record("length_declared", "unknown", "arrays carry no length_m")
    else:
        frac = abs(recomputed_length - declared_length) / declared_length
        evidence.numbers["length_declared_error_fraction"] = frac
        evidence.record(
            "length_declared",
            "pass" if frac <= tolerance else "fail",
            f"recomputed {recomputed_length:.2f} m vs declared {declared_length:.2f} m ({frac:.5f})",
        )
    if official_length_m is None:
        evidence.record("length_official", "unknown", "no official length available (manifest or package)")
    else:
        length_error_fraction = abs(recomputed_length - official_length_m) / official_length_m
        evidence.numbers["length_official_error_fraction"] = length_error_fraction
        evidence.record(
            "length_official",
            "pass" if length_error_fraction <= tolerance else "fail",
            f"recomputed {recomputed_length:.2f} m vs official {official_length_m:.2f} m "
            f"({length_error_fraction:.5f}, tolerance {tolerance})",
        )

    length_for_closure = declared_length if declared_length is not None else recomputed_length
    remaining = length_for_closure - float(s[-1])
    chord = np.array([x[-1] - x[-2], y[-1] - y[-2], z[-1] - z[-2]])
    chord_norm = float(np.linalg.norm(chord))
    if chord_norm > 0.0:
        end = np.array([x[-1], y[-1], z[-1]]) + remaining * chord / chord_norm
    else:
        end = np.array([x[-1], y[-1], z[-1]])
    closure_error_m = float(math.hypot(end[0] - x[0], end[1] - y[0]))
    evidence.numbers["closure_error_m"] = closure_error_m
    evidence.record(
        "closure",
        "pass" if closure_error_m <= CLOSURE_TOLERANCE_M else "fail",
        f"|r(0) - r(L)| = {closure_error_m:.4f} m (tolerance {CLOSURE_TOLERANCE_M} m)",
    )

    dx = np.gradient(x, spacing)
    dy = np.gradient(y, spacing)
    tangent = np.arctan2(dy, dx)
    yaw_dev = np.abs(_wrap_angle(yaw - tangent))
    max_yaw_dev = float(np.max(yaw_dev))
    evidence.numbers["yaw_tangent_max_deviation_rad"] = max_yaw_dev
    evidence.record(
        "yaw_tangent",
        "pass" if max_yaw_dev <= YAW_TANGENT_TOLERANCE_RAD else "fail",
        f"max |yaw - atan2(dy, dx)| = {max_yaw_dev:.4f} rad",
    )

    kappa_from_yaw = np.gradient(np.unwrap(yaw), spacing)
    kappa_dev = float(np.max(np.abs(kappa - kappa_from_yaw)))
    evidence.numbers["curvature_yaw_max_deviation_1pm"] = kappa_dev
    evidence.record(
        "curvature_yaw",
        "pass" if kappa_dev <= CURVATURE_YAW_TOLERANCE_1PM else "fail",
        f"max |kappa - dyaw/ds| = {kappa_dev:.5f} 1/m",
    )

    max_kappa = float(np.max(np.abs(kappa)))
    evidence.numbers["curvature_max_abs_1pm"] = max_kappa
    evidence.record(
        "curvature_bounded",
        "pass" if max_kappa <= CURVATURE_BOUND_1PM else "fail",
        f"max |kappa| = {max_kappa:.5f} 1/m (bound {CURVATURE_BOUND_1PM:.5f})",
    )
    max_grade = float(np.max(np.abs(grade)))
    evidence.numbers["grade_max_abs"] = max_grade
    evidence.record(
        "grade_bounded",
        "pass" if max_grade <= GRADE_BOUND else "fail",
        f"max |grade| = {max_grade:.4f} (bound {GRADE_BOUND})",
    )

    signed_area = 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
    evidence.numbers["signed_area_m2"] = signed_area
    if package.direction is Direction.MIXED:
        evidence.record("direction", "unknown", "declared direction is mixed; signed area cannot confirm it")
    else:
        implied = Direction.COUNTERCLOCKWISE if signed_area > 0.0 else Direction.CLOCKWISE
        ok = implied is package.direction
        evidence.record(
            "direction",
            "pass" if ok else "fail",
            f"signed area {signed_area:.1f} m^2 implies {implied.value}; "
            f"package declares {package.direction.value}",
        )

    widths_finite = (
        "width_left_m" in arrays
        and "width_right_m" in arrays
        and bool(np.all(np.isfinite(arrays["width_left_m"])))
        and bool(np.all(np.isfinite(arrays["width_right_m"])))
    )
    return closure_error_m, length_error_fraction, widths_finite


def _wrap_angle(angle: np.ndarray) -> np.ndarray:
    return (angle + np.pi) % (2.0 * np.pi) - np.pi


def _check_sources(package: TrackPackage, evidence: _Evidence) -> None:
    hashed = [src.source_id for src in package.sources if src.sha256]
    unhashed = [src.source_id for src in package.sources if not src.sha256]
    evidence.numbers["sources_hashed"] = hashed
    evidence.numbers["sources_unhashed"] = unhashed
    if not hashed:
        evidence.record("sources_hashed", "fail", "no source record carries a sha256")
    elif unhashed:
        evidence.record(
            "sources_hashed", "pass", f"unhashed sources kept as context only: {', '.join(unhashed)}"
        )
    else:
        evidence.record("sources_hashed", "pass")


def _confirmed_overlay(
    track_id: str, package: TrackPackage, paths: Paths, evidence: _Evidence
) -> EventOverlay | None:
    """The confirmed overlay the package may claim, or ``None``.

    An overlay already embedded in the package is trusted only if it is still
    confirmed; otherwise the ``events/`` queue is scanned and the latest
    confirmed document (by event id) is embedded.
    """
    candidates: list[EventOverlay] = []
    events_dir = package_dir(track_id, paths) / "events"
    seen: list[str] = []
    if events_dir.exists():
        for path in sorted(events_dir.glob("*.json")):
            if path.name.count(".") != 1:
                continue
            event_id = path.stem
            try:
                overlay = load_event_overlay(track_id, event_id, paths)
            except (ValueError, TrackPackageError) as exc:
                evidence.notes.append(f"event overlay {event_id}: unreadable ({exc})")
                continue
            seen.append(f"{event_id}={overlay.review_status}")
            if overlay.is_confirmed:
                candidates.append(overlay)
    if package.event_overlay is not None and package.event_overlay.is_confirmed:
        candidates.append(package.event_overlay)
    evidence.numbers["event_overlays_seen"] = seen
    if not candidates:
        evidence.record("event_overlay_confirmed", "unknown", "no two-reviewer confirmed event overlay")
        return None
    chosen = max(candidates, key=lambda o: o.event_id)
    evidence.record(
        "event_overlay_confirmed",
        "pass",
        f"{chosen.event_id} confirmed by {', '.join(chosen.reviewers)}",
    )
    return chosen


def _conditions_calibrated(directory: Path, evidence: _Evidence) -> bool:
    path = directory / CONDITIONS_REPORT_RELATIVE
    if not path.exists():
        evidence.record("conditions_calibrated", "unknown", f"no {CONDITIONS_REPORT_RELATIVE.as_posix()}")
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        evidence.record("conditions_calibrated", "fail", f"calibration report unreadable: {exc}")
        return False
    sessions = payload.get("source_sessions") if isinstance(payload, dict) else None
    ok = (
        isinstance(payload, dict)
        and payload.get("status") == "calibrated"
        and isinstance(sessions, list)
        and len(sessions) > 0
    )
    evidence.record(
        "conditions_calibrated",
        "pass" if ok else "unknown",
        None if ok else "calibration report present but not status=calibrated with source_sessions",
    )
    return ok


def _check_corridor(package: TrackPackage, widths_finite: bool, evidence: _Evidence) -> None:
    quality = package.geometry.corridor_quality
    if quality is CorridorQuality.UNKNOWN:
        evidence.record("corridor", "unknown", "corridor quality unknown; lateral claims disabled")
    elif not widths_finite:
        evidence.record(
            "corridor", "fail", f"corridor declared {quality.value} but half-widths are not finite"
        )
    else:
        evidence.record("corridor", "pass", f"{quality.value} corridor with finite half-widths")


def _derive_status(
    evidence: _Evidence, overlay: EventOverlay | None, conditions_ok: bool, widths_finite: bool
) -> ReadinessStatus:
    checks = evidence.checks
    if any(checks.get(c) == "fail" for c in _INTEGRITY_CHECKS):
        evidence.notes.append("status rejected: an integrity check failed")
        return ReadinessStatus.REJECTED
    if checks.get("corridor") == "fail":
        evidence.notes.append("status rejected: corridor quality claimed without finite half-widths")
        return ReadinessStatus.REJECTED
    if any(checks.get(c) != "pass" for c in GEOMETRY_CHECKS):
        pending = [c for c in GEOMETRY_CHECKS if checks.get(c) != "pass"]
        evidence.notes.append(f"status discovered: geometry checks not passed: {', '.join(pending)}")
        return ReadinessStatus.DISCOVERED
    if overlay is None:
        return ReadinessStatus.GEOMETRY_VALIDATED
    if not conditions_ok:
        return ReadinessStatus.EVENT_RULES_VALIDATED
    if checks.get("corridor") != "pass" or not widths_finite:
        return ReadinessStatus.CONDITION_CALIBRATED
    return ReadinessStatus.SIMULATION_ELIGIBLE


__all__ = [
    "CLOSURE_TOLERANCE_M",
    "CONDITIONS_REPORT_RELATIVE",
    "CURVATURE_BOUND_1PM",
    "CURVATURE_YAW_TOLERANCE_1PM",
    "GEOMETRY_CHECKS",
    "GRADE_BOUND",
    "LENGTH_TOLERANCE_FRACTION_DEFAULT",
    "REPORT_FILENAME",
    "VALIDATOR_VERSION",
    "YAW_TANGENT_TOLERANCE_RAD",
    "validate_track",
]
