"""Metric centreline compiler for OpenF1 location telemetry (A16-2).

Implements TRACK_DATA_PIPELINE.md "Geometry compilation" steps 1-6 and 9 for a
priority-3 source. The output is the *median driven line of one driver*, not a
surveyed centreline: the corridor is unknown, no ``mu`` is claimed and the
package is written at ``discovered``; the independent validator promotes it.

Pipeline, per manifest session:

1. read the clean laps the ingest step persisted (offline; no network here);
2. infer the coordinate scale from the raw polyline length against the official
   length and record the evidence (OpenF1 does not document its units);
3. per lap: order by time, remove duplicates and isolated jumps with thresholds
   derived from cadence and a physical speed ceiling, reject isolated elevation
   spikes against the declared road-gradient ceiling, interpolate the
   timing-line crossing at the lap boundary time, fit a periodic cubic B-spline
   with smoothing chosen against held-out residual and curvature stability;
4. register every lap onto a reference lap by arc length and take the median
   lateral offset and elevation per bin; fit the final periodic spline, and fit
   the elevation channel again with its own bandwidth chosen on held-out
   *vertical* residual;
5. resample at 1 m by arc length; yaw, horizontal curvature and grade come from
   spline derivatives, never from raw finite differences;
6. set ``s = 0`` at the median timing-line crossing without changing the length;
   direction from the signed area of progression; closure error;
7. check the smoothed grade against the declared ceiling. An elevation profile
   that still breaks it is declared *unavailable* -- never zeroed, never
   published as geometry -- because grade enters the engine as a gravitational
   term and an implausible grade is fake energy demand.

Everything numeric lands in ``compile_report.json`` next to the package.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from scipy.interpolate import BSpline
from scipy.sparse import csr_matrix, hstack, identity, lil_matrix
from scipy.sparse.linalg import spsolve
from scipy.spatial import cKDTree

from ..paths import Paths
from .ingest.openf1 import IngestResult, LapRecord, load_ingest_summary, parse_openf1_time
from .package import (
    CANONICAL_SPACING_M,
    CompiledCentreline,
    CorridorQuality,
    Direction,
    GeometryDescriptor,
    GeometryProvenance,
    ReadinessStatus,
    SourceRecord,
    SRange,
    TrackFeatures,
    TrackPackage,
    ValidationReport,
)
from .provenance import RawSourceCache

LOCAL_CRS = "openf1-local-metric"
"""Raw OpenF1 integers scaled by the inferred factor and translated to the reference-lap centroid."""

SPEED_CEILING_MPS = 110.0
"""Physical ceiling for jump rejection: ~396 km/h, above any recorded F1 speed (372 km/h)."""

ROAD_GRADE_CEILING = 0.25
"""Declared physical bound on the longitudinal gradient of a racing surface.

The steepest gradients on the calendar are Spa's Raidillon (about 18 %) and the
climb to Austin's turn 1 (about 12 %); no Grand Prix circuit sustains 25 %. This
is a declaration about roads, not a threshold tuned until a circuit passes, and
it is the same bound the independent validator applies (``validate.GRADE_BOUND``).
Grade enters the engine's force balance as a gravitational term, so an
implausible grade is fake energy demand: the compiler will not publish one.
"""

VERTICAL_SPEED_CEILING_MPS = SPEED_CEILING_MPS * ROAD_GRADE_CEILING
"""Derived, not chosen: below the speed ceiling on a road within the grade ceiling a car cannot
change elevation faster than 110 x 0.25 = 27.5 m/s, whatever the sampling cadence."""

SCALE_CANDIDATES: dict[str, float] = {"m": 1.0, "dm": 0.1, "cm": 0.01, "mm": 0.001}
"""Decimal unit hypotheses for the undocumented OpenF1 coordinate frame."""

SCALE_MAX_DEVIATION = 0.08
"""A hypothesis is accepted only if raw-length x scale is within this fraction of the official length."""

SMOOTHING_BANDWIDTH_CANDIDATES_M: tuple[float, ...] = (
    5.0,
    7.5,
    10.0,
    15.0,
    20.0,
    30.0,
    45.0,
    60.0,
    90.0,
    120.0,
    180.0,
)
"""Equivalent-kernel bandwidths tried for the penalised periodic spline (metres along the lap)."""

ELEVATION_BANDWIDTH_CANDIDATES_M: tuple[float, ...] = (*SMOOTHING_BANDWIDTH_CANDIDATES_M, 240.0, 320.0)
"""Bandwidths tried for the elevation channel.

The lateral scatter of a racing line and the elevation profile of a road are
different signals: OpenF1 publishes z as an integer at the same quantum as x and
y, but elevation varies over hundreds of metres, so the plausible bandwidth range
extends further than the horizontal one. The held-out *vertical* residual still
bounds the choice from above -- over-smoothing Raidillon costs vertical accuracy
exactly as over-smoothing a chicane costs lateral accuracy.
"""

KNOT_SPACING_M = 2.5
"""Fixed knot spacing of the penalised spline; smoothness comes from the penalty, not from dropping knots."""

REGISTRATION_BIN_M = 5.0
HOLDOUT_FOLDS = 5


class CompileError(RuntimeError):
    """The compiler refused to produce a package; the reason is named."""


@dataclass(frozen=True, slots=True)
class OfficialLength:
    value_m: float
    source_url: str
    retrieved_at: str
    title: str = "Official circuit length"
    sha256: str | None = None
    permission: str = "reference-only; review terms before redistribution"


@dataclass(frozen=True, slots=True)
class ManifestSession:
    session_key: int
    year: int | None = None
    session_name: str | None = None
    driver_number: int | None = None


@dataclass(frozen=True, slots=True)
class TrackManifest:
    """``configs/tracks/<track_id>/source.yaml`` as written by the registry worker (A16-1)."""

    track_id: str
    display_name: str
    official_length: OfficialLength
    sessions: tuple[ManifestSession, ...]
    direction: str | None = None
    fia_documents: tuple[dict[str, Any], ...] = ()
    permissions: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None


def load_manifest(path: Path) -> TrackManifest:
    if not path.exists():
        raise CompileError(f"track manifest not found at {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        length = raw["official_length_m"]
        if isinstance(length, int | float):
            raise CompileError(
                "official_length_m must be a mapping {value, source_url, retrieved_at}; "
                "a bare number has no provenance"
            )
        official = OfficialLength(
            value_m=float(length["value"]),
            source_url=str(length["source_url"]),
            retrieved_at=str(length["retrieved_at"]),
            title=str(length.get("title", "Official circuit length")),
            sha256=length.get("sha256"),
            permission=str(length.get("permission", "reference-only; review terms before redistribution")),
        )
        sessions = tuple(
            ManifestSession(
                session_key=int(s["session_key"]),
                year=s.get("year"),
                session_name=s.get("session_name"),
                driver_number=s.get("driver_number"),
            )
            for s in (raw.get("openf1") or {}).get("sessions", [])
        )
        manifest = TrackManifest(
            track_id=str(raw["track_id"]),
            display_name=str(raw["display_name"]),
            official_length=official,
            sessions=sessions,
            direction=raw.get("direction"),
            fia_documents=tuple(raw.get("fia_documents") or ()),
            permissions=dict(raw.get("permissions") or {}),
            path=path,
        )
    except KeyError as exc:
        raise CompileError(f"track manifest {path} lacks required field {exc}") from exc
    if official.value_m <= 0.0:
        raise CompileError("official_length_m.value must be positive")
    if not manifest.sessions:
        raise CompileError(f"track manifest {path} lists no openf1.sessions; nothing to compile")
    return manifest


@dataclass(frozen=True, slots=True)
class ScaleInference:
    chosen_unit: str
    scale_m_per_unit: float
    raw_polyline_length_units: float
    implied_scale: float
    deviation_fraction: float
    accepted: bool
    evidence: str


def infer_scale(raw_polyline_length_units: float, official_length_m: float) -> ScaleInference:
    """Pick the decimal unit whose scaled polyline length is nearest the official length.

    The raw polyline is slightly *longer* than the true path because positional
    noise adds zig-zag, so the implied scale sits a little below the true unit;
    a hypothesis within :data:`SCALE_MAX_DEVIATION` is accepted, nothing is assumed.
    """
    if raw_polyline_length_units <= 0.0:
        raise CompileError("cannot infer a coordinate scale from a zero-length polyline")
    implied = official_length_m / raw_polyline_length_units
    best_unit, best_scale = min(SCALE_CANDIDATES.items(), key=lambda kv: abs(math.log(implied / kv[1])))
    deviation = abs(raw_polyline_length_units * best_scale - official_length_m) / official_length_m
    accepted = deviation <= SCALE_MAX_DEVIATION
    evidence = (
        f"raw polyline length {raw_polyline_length_units:.1f} units vs official {official_length_m:.1f} m "
        f"implies {implied:.5f} m/unit; nearest decimal hypothesis is 1 {best_unit} = {best_scale} m "
        f"(scaled length off by {deviation * 100:.2f} %, limit {SCALE_MAX_DEVIATION * 100:.0f} %)"
    )
    return ScaleInference(
        best_unit, best_scale, raw_polyline_length_units, implied, deviation, accepted, evidence
    )


def polyline_length(xy: np.ndarray) -> float:
    return float(np.sum(np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1]))))


@dataclass(frozen=True, slots=True)
class CleaningReport:
    samples_in: int
    samples_out: int
    exact_duplicates: int
    time_duplicates: int
    jumps: int
    median_dt_s: float
    duplicate_dt_threshold_s: float
    speed_ceiling_mps: float


def clean_samples(
    t_s: np.ndarray, xyz_m: np.ndarray, *, speed_ceiling_mps: float = SPEED_CEILING_MPS
) -> tuple[np.ndarray, np.ndarray, CleaningReport]:
    """Order by time, drop duplicates and isolated jumps.

    Thresholds are derived, not chosen by eye: a *time duplicate* is a sample
    closer than a quarter of the median cadence to its predecessor; a *jump* is a
    sample whose implied speed both from the previous and to the next kept sample
    exceeds the physical ceiling, i.e. a displacement larger than
    ``speed_ceiling * dt`` on both sides.
    """
    order = np.argsort(t_s, kind="stable")
    t = np.asarray(t_s, dtype=np.float64)[order]
    p = np.asarray(xyz_m, dtype=np.float64)[order]
    n_in = len(t)
    if n_in < 8:
        raise CompileError(f"a lap needs at least 8 samples; got {n_in}")

    dt = np.diff(t)
    positive = dt[dt > 0.0]
    median_dt = float(np.median(positive)) if positive.size else 0.0
    dup_dt = 0.25 * median_dt

    keep = np.ones(n_in, dtype=bool)
    exact = 0
    timed = 0
    last = 0
    for i in range(1, n_in):
        if np.array_equal(p[i], p[last]):
            keep[i] = False
            exact += 1
            continue
        if t[i] - t[last] <= dup_dt:
            keep[i] = False
            timed += 1
            continue
        last = i
    t, p = t[keep], p[keep]

    jumps = 0
    changed = True
    while changed and len(t) > 8:
        changed = False
        keep = np.ones(len(t), dtype=bool)
        for i in range(1, len(t) - 1):
            d_prev = float(np.hypot(*(p[i, :2] - p[i - 1, :2])))
            d_next = float(np.hypot(*(p[i + 1, :2] - p[i, :2])))
            too_fast_in = d_prev > speed_ceiling_mps * (t[i] - t[i - 1])
            too_fast_out = d_next > speed_ceiling_mps * (t[i + 1] - t[i])
            if too_fast_in and too_fast_out:
                keep[i] = False
                jumps += 1
                changed = True
        t, p = t[keep], p[keep]

    report = CleaningReport(
        samples_in=n_in,
        samples_out=len(t),
        exact_duplicates=exact,
        time_duplicates=timed,
        jumps=jumps,
        median_dt_s=median_dt,
        duplicate_dt_threshold_s=dup_dt,
        speed_ceiling_mps=speed_ceiling_mps,
    )
    return t, p, report


@dataclass(frozen=True, slots=True)
class ElevationCleaningReport:
    """The z channel of one lap before and after outlier rejection."""

    samples: int
    rejected_spikes: int
    rejected_fraction: float
    steep_segments_retained: int
    passes: int
    rejection_cap_reached: bool
    max_abs_segment_grade_before: float
    max_abs_segment_grade_after: float
    max_abs_vertical_speed_before_mps: float
    max_abs_vertical_speed_after_mps: float
    grade_ceiling: float
    vertical_speed_ceiling_mps: float
    z_quantum_m: float
    rule: str


def _z_budget(
    xyz: np.ndarray, grade_ceiling: float, z_quantum_m: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-segment elevation change, horizontal displacement and the plausible ``|dz|`` budget."""
    dz = np.diff(xyz[:, 2])
    horizontal = np.hypot(np.diff(xyz[:, 0]), np.diff(xyz[:, 1]))
    return dz, horizontal, grade_ceiling * horizontal + z_quantum_m


def _fill_rejected_z(xyz: np.ndarray, trusted: np.ndarray) -> np.ndarray:
    """z at rejected samples, linearly interpolated in horizontal arc length between trusted ones."""
    if bool(trusted.all()):
        return np.asarray(xyz[:, 2], dtype=np.float64)
    if int(trusted.sum()) < 2:
        raise CompileError("every elevation sample of a lap was rejected; there is no z channel left")
    seg = np.hypot(np.diff(xyz[:, 0]), np.diff(xyz[:, 1]))
    s = np.concatenate(([0.0], np.cumsum(seg)))
    z = np.array(xyz[:, 2], dtype=np.float64, copy=True)
    z[~trusted] = np.interp(s[~trusted], s[trusted], xyz[trusted, 2])
    return z


def reject_z_outliers(
    t_s: np.ndarray,
    xyz_m: np.ndarray,
    *,
    z_quantum_m: float,
    grade_ceiling: float = ROAD_GRADE_CEILING,
    max_passes: int = 4,
    max_rejected_fraction: float = 0.05,
) -> tuple[np.ndarray, ElevationCleaningReport]:
    """Remove isolated elevation spikes from one lap's z channel.

    The threshold is physical, not tuned to a circuit. Between two consecutive
    samples the surface can change elevation by at most ``grade_ceiling`` times
    the horizontal distance covered, plus one quantisation step of the source's
    own integer coordinates -- equivalently ``|dz/dt| <= grade_ceiling * v``, the
    vertical-speed limit at whatever cadence the feed happens to deliver, whose
    worst case is :data:`VERTICAL_SPEED_CEILING_MPS`. A sample is rejected only
    when it breaks that budget on *both* sides *with opposite signs*: the road
    would have to rise and fall again inside one sampling interval, which a
    static surface cannot do. A one-sided or same-sign excess is a candidate
    genuine slope, so it is counted in ``steep_segments_retained`` and kept; the
    post-smoothing plausibility check (:func:`assess_elevation`), not this
    function, decides whether the channel may be published.

    A rejected sample keeps its x and y; only its z is replaced, by linear
    interpolation in horizontal arc length between the nearest trusted samples --
    the same continuity assumption the spline makes everywhere else -- and the
    count reaches ``compile_report.json``. Nothing is zeroed: a zero grade is a
    claim about the road, an interpolated one is a labelled estimate.

    *Isolated* means sparse. If rejection would remove more than
    ``max_rejected_fraction`` of the lap's samples then the channel is not
    repairable by outlier rejection at all: the loop stops,
    ``rejection_cap_reached`` is set and the plausibility check downstream
    declares the elevation channel unavailable. The first and last sample of the
    window have no two-sided neighbourhood and are never tested; the ingest
    window carries margin samples on both sides of the lap, so the lap's own
    timing-line neighbourhood is interior.
    """
    xyz = np.array(xyz_m, dtype=np.float64, copy=True)
    t = np.asarray(t_s, dtype=np.float64)
    n = len(xyz)
    dz0, horizontal0, _ = _z_budget(xyz, grade_ceiling, z_quantum_m)
    grade_before = float(np.max(np.abs(dz0) / np.maximum(horizontal0, z_quantum_m)))
    vertical_before = float(np.max(np.abs(dz0 / np.maximum(np.diff(t), 1e-9))))
    trusted = np.ones(n, dtype=bool)
    cap = max(1, math.floor(max_rejected_fraction * n))
    rejected = 0
    passes = 0
    capped = False
    interior = np.arange(1, n - 1)
    for _ in range(max_passes):
        dz, _, budget = _z_budget(xyz, grade_ceiling, z_quantum_m)
        over = np.abs(dz) > budget
        spike = np.zeros(n, dtype=bool)
        spike[interior] = (
            over[interior - 1] & over[interior] & (np.sign(dz[interior - 1]) != np.sign(dz[interior]))
        )
        spike &= trusted
        found = int(spike.sum())
        if found == 0:
            break
        if rejected + found > cap:
            capped = True
            break
        passes += 1
        rejected += found
        trusted &= ~spike
        xyz[:, 2] = _fill_rejected_z(xyz, trusted)
    dz1, horizontal1, budget1 = _z_budget(xyz, grade_ceiling, z_quantum_m)
    report = ElevationCleaningReport(
        samples=n,
        rejected_spikes=rejected,
        rejected_fraction=rejected / n,
        steep_segments_retained=int(np.sum(np.abs(dz1) > budget1)),
        passes=passes,
        rejection_cap_reached=capped,
        max_abs_segment_grade_before=grade_before,
        max_abs_segment_grade_after=float(np.max(np.abs(dz1) / np.maximum(horizontal1, z_quantum_m))),
        max_abs_vertical_speed_before_mps=vertical_before,
        max_abs_vertical_speed_after_mps=float(np.max(np.abs(dz1 / np.maximum(np.diff(t), 1e-9)))),
        grade_ceiling=grade_ceiling,
        vertical_speed_ceiling_mps=grade_ceiling * SPEED_CEILING_MPS,
        z_quantum_m=z_quantum_m,
        rule=(
            "reject sample i when |dz| exceeds grade_ceiling * horizontal displacement + one z quantum on "
            "both sides with opposite signs (an elevation excursion that reverses inside one sampling "
            "interval); its z is then linearly interpolated in horizontal arc length from trusted "
            f"neighbours. Cap: {max_rejected_fraction:.0%} of the lap's samples, {max_passes} passes."
        ),
    )
    return xyz, report


def _loop_parameter(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Normalised cumulative chord parameter ``u in [0, 1)`` around the closed loop.

    Exact repeats are dropped so the parameter is strictly increasing. The closing
    chord (last point back to the first) is included in the total.
    """
    pts = np.asarray(points, dtype=np.float64)
    seg = np.linalg.norm(np.diff(pts[:, :2], axis=0), axis=1)
    keep = np.concatenate(([True], seg > 0.0))
    pts = pts[keep]
    seg = np.linalg.norm(np.diff(pts[:, :2], axis=0), axis=1)
    closing = float(np.hypot(*(pts[0, :2] - pts[-1, :2])))
    total = float(np.sum(seg)) + closing
    if total <= 0.0:
        raise CompileError("all points coincide; no loop to fit")
    u = np.concatenate(([0.0], np.cumsum(seg))) / total
    return pts, u, total


class PeriodicSpline:
    """Periodic cubic B-spline on ``u in [0, 1)`` with 3-D coefficients, evaluated with derivatives."""

    __slots__ = ("bandwidth_m", "knot_spacing_m", "spline")

    def __init__(self, spline: BSpline, bandwidth_m: float, knot_spacing_m: float) -> None:
        self.spline = spline
        self.bandwidth_m = bandwidth_m
        self.knot_spacing_m = knot_spacing_m

    def __call__(self, u: np.ndarray, der: int = 0) -> np.ndarray:
        return np.asarray(self.spline(np.mod(u, 1.0), nu=der), dtype=np.float64)


def fit_periodic_spline(
    points: np.ndarray, bandwidth_m: float, *, knot_spacing_m: float = KNOT_SPACING_M
) -> Any:
    """Penalised periodic cubic B-spline (P-spline) through a closed loop.

    Knots sit every ``knot_spacing_m`` metres of chord length regardless of the
    smoothing, and smoothness comes from a circular second-difference penalty on
    the coefficients. The penalty weight is expressed as an equivalent-kernel
    bandwidth ``h`` in metres (Silverman's approximation for the Reinsch
    smoothing spline, ``lambda = rho h^4`` with ``rho`` the point density), so a
    reader can judge what features survive. Unlike a knot-dropping smoothing
    spline, a heavily smoothed fit of a circular arc keeps constant curvature.
    """
    pts, u, total = _loop_parameter(points)
    n = len(pts)
    if n < 8:
        raise CompileError("too few distinct points for a periodic cubic spline")
    k = 3
    m = max(8, round(total / knot_spacing_m))
    delta_s = total / m
    t_ext = np.arange(-k, m + k + 1, dtype=np.float64) / m
    b_ext = BSpline.design_matrix(u, t_ext, k).tocsc()
    wrap = hstack([b_ext[:, m : m + k], csr_matrix((n, m - k))], format="csr")
    b_per = (b_ext[:, :m] + wrap).tocsr()
    d2 = lil_matrix((m, m))
    for i in range(m):
        d2[i, i] = 1.0
        d2[i, (i + 1) % m] = -2.0
        d2[i, (i + 2) % m] = 1.0
    d2 = d2.tocsr()
    rho = n / total
    lam = rho * bandwidth_m**4 / delta_s**3
    gram = (b_per.T @ b_per) + lam * (d2.T @ d2) + 1e-12 * identity(m)
    rhs = b_per.T @ pts
    coef = np.asarray(spsolve(gram.tocsc(), rhs))
    if coef.ndim == 1:
        coef = coef[:, None]
    c_ext = coef[np.arange(m + k) % m]
    return PeriodicSpline(BSpline(t_ext, c_ext, k, extrapolate="periodic"), bandwidth_m, delta_s)


def evaluate_spline(tck: Any, u: np.ndarray, der: int = 0) -> np.ndarray:
    return np.asarray(tck(np.asarray(u, dtype=np.float64), der), dtype=np.float64)


@dataclass(frozen=True, slots=True)
class ResampledLine:
    s_m: np.ndarray
    xyz_m: np.ndarray
    yaw_rad: np.ndarray
    curvature_1pm: np.ndarray
    grade_rad: np.ndarray
    length_3d_m: float
    length_2d_m: float


def _combined(tck: Any, z_tck: Any, u: np.ndarray, der: int = 0) -> np.ndarray:
    """Curve values with x, y from ``tck`` and z from ``z_tck`` when elevation has its own fit."""
    values = evaluate_spline(tck, u, der)
    if z_tck is None:
        return values
    out = np.array(values, dtype=np.float64, copy=True)
    out[:, 2] = evaluate_spline(z_tck, u, der)[:, 2]
    return out


def _dense_arclength(tck: Any, n_dense: int, z_tck: Any = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    u = np.linspace(0.0, 1.0, n_dense + 1)
    pts = _combined(tck, z_tck, u)
    seg3 = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    seg2 = np.linalg.norm(np.diff(pts[:, :2], axis=0), axis=1)
    return u, np.concatenate(([0.0], np.cumsum(seg3))), np.concatenate(([0.0], np.cumsum(seg2)))


def resample_by_arclength(
    tck: Any,
    *,
    z_tck: Any = None,
    spacing_m: float = CANONICAL_SPACING_M,
    s_offset_m: float = 0.0,
    dense_per_m: float = 10.0,
) -> ResampledLine:
    """Evaluate the spline on an equal-arc grid starting ``s_offset_m`` along the parameter origin.

    Arc length is the 3-D path length. Yaw, horizontal curvature and grade come
    from analytic spline derivatives: ``kappa = (x'y'' - y'x'') / (x'^2+y'^2)^1.5``,
    ``grade = atan(z' / sqrt(x'^2+y'^2))``.

    ``z_tck`` supplies the elevation channel from its own fit -- its own smoothing
    bandwidth -- while x, y, yaw and curvature stay with ``tck``. Both splines must
    be fitted to the same point set, so they share the chord parameter ``u`` and
    the same knots; that is checked, not assumed.
    """
    if z_tck is not None and not np.array_equal(
        np.asarray(z_tck.spline.t, dtype=np.float64), np.asarray(tck.spline.t, dtype=np.float64)
    ):
        raise CompileError(
            "the elevation spline does not share the horizontal spline's knots; both must be fitted "
            "to the same aggregated points"
        )
    _, arc3, _ = _dense_arclength(tck, 4000, z_tck)
    rough = float(arc3[-1])
    n_dense = int(max(4000, dense_per_m * rough))
    u_dense, arc3, arc2 = _dense_arclength(tck, n_dense, z_tck)
    length = float(arc3[-1])
    length_2d = float(arc2[-1])
    n = math.floor(length / spacing_m - 1e-9) + 1
    s_grid = np.arange(n, dtype=np.float64) * spacing_m
    s_abs = np.mod(s_grid + s_offset_m, length)
    u_grid = np.interp(s_abs, arc3, u_dense)
    d0 = _combined(tck, z_tck, u_grid)
    d1 = _combined(tck, z_tck, u_grid, der=1)
    d2 = evaluate_spline(tck, u_grid, der=2)
    xp, yp, zp = d1[:, 0], d1[:, 1], d1[:, 2]
    xpp, ypp = d2[:, 0], d2[:, 1]
    horiz = np.hypot(xp, yp)
    yaw = np.arctan2(yp, xp)
    curvature = (xp * ypp - yp * xpp) / np.maximum(horiz, 1e-12) ** 3
    grade = np.arctan2(zp, np.maximum(horiz, 1e-12))
    return ResampledLine(s_grid, d0, yaw, curvature, grade, length, length_2d)


def raw_finite_difference_curvature(xy: np.ndarray) -> np.ndarray:
    """Three-point circumscribed-circle curvature of consecutive raw samples (for comparison only)."""
    a, b, c = xy[:-2], xy[1:-1], xy[2:]
    ab = b - a
    bc = c - b
    ca = a - c
    cross = ab[:, 0] * bc[:, 1] - ab[:, 1] * bc[:, 0]
    la = np.linalg.norm(ab, axis=1)
    lb = np.linalg.norm(bc, axis=1)
    lc = np.linalg.norm(ca, axis=1)
    denom = la * lb * lc
    with np.errstate(divide="ignore", invalid="ignore"):
        kappa = np.where(denom > 0.0, 2.0 * cross / denom, 0.0)
    return np.asarray(kappa, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class SmoothingCandidate:
    bandwidth_m: float
    holdout_rms_fold_se_m: float
    holdout_rms_m: float
    holdout_p95_m: float
    curvature_stability_rms_1pm: float
    max_abs_curvature_1pm: float


@dataclass(frozen=True, slots=True)
class SmoothingSelection:
    chosen_bandwidth_m: float
    knot_spacing_m: float
    rule: str
    candidates: tuple[SmoothingCandidate, ...]


def _nearest_distance(curve_xy: np.ndarray, points_xy: np.ndarray) -> np.ndarray:
    tree = cKDTree(curve_xy)
    dist, _ = tree.query(points_xy)
    return np.asarray(dist, dtype=np.float64)


def choose_smoothing(
    points: np.ndarray,
    candidates_m: tuple[float, ...] = SMOOTHING_BANDWIDTH_CANDIDATES_M,
    *,
    folds: int = HOLDOUT_FOLDS,
) -> SmoothingSelection:
    """Interleaved k-fold hold-out over smoothing bandwidths.

    For each bandwidth, ``folds`` fits leave out every ``folds``-th point; the
    held-out residual is the horizontal distance from those points to the fitted
    curve, and curvature stability is the RMS difference between each fold's
    curvature and the full fit's curvature on the same 1 m grid. Selection uses
    the one-standard-error rule from cross-validation practice: the smoothest
    bandwidth whose mean fold RMS is within one standard error of the minimum.
    Genuine features (chicanes) raise the held-out residual of an over-smoothed
    fit and so bound the bandwidth from above; noise alone does not. Both
    metrics are recorded for every candidate.
    """
    n = len(points)
    results: list[SmoothingCandidate] = []
    knot_spacing = 0.0
    for bandwidth in candidates_m:
        full = fit_periodic_spline(points, bandwidth)
        knot_spacing = float(full.knot_spacing_m)
        full_line = resample_by_arclength(full, dense_per_m=4.0)
        holdout: list[np.ndarray] = []
        stability: list[float] = []
        for k in range(folds):
            mask = np.ones(n, dtype=bool)
            mask[k::folds] = False
            if mask.sum() < 8:
                continue
            tck = fit_periodic_spline(points[mask], bandwidth)
            line = resample_by_arclength(tck, dense_per_m=4.0)
            holdout.append(_nearest_distance(line.xyz_m[:, :2], points[~mask, :2]))
            m = min(len(line.curvature_1pm), len(full_line.curvature_1pm))
            tree = cKDTree(full_line.xyz_m[:, :2])
            _, idx = tree.query(line.xyz_m[:m, :2])
            diff = line.curvature_1pm[:m] - full_line.curvature_1pm[idx]
            stability.append(float(np.sqrt(np.mean(diff**2))))
        if not holdout:
            raise CompileError("not enough points for hold-out smoothing selection")
        all_res = np.concatenate(holdout)
        fold_rms = np.array([np.sqrt(np.mean(h**2)) for h in holdout])
        se = float(np.std(fold_rms, ddof=1) / np.sqrt(len(fold_rms))) if len(fold_rms) > 1 else 0.0
        results.append(
            SmoothingCandidate(
                bandwidth_m=bandwidth,
                holdout_rms_fold_se_m=se,
                holdout_rms_m=float(np.sqrt(np.mean(all_res**2))),
                holdout_p95_m=float(np.percentile(all_res, 95)),
                curvature_stability_rms_1pm=float(np.mean(stability)),
                max_abs_curvature_1pm=float(np.max(np.abs(full_line.curvature_1pm))),
            )
        )
    best = min(results, key=lambda r: r.holdout_rms_m)
    threshold = best.holdout_rms_m + best.holdout_rms_fold_se_m
    eligible = [r for r in results if r.holdout_rms_m <= threshold]
    chosen = max(eligible, key=lambda r: r.bandwidth_m)
    return SmoothingSelection(
        chosen_bandwidth_m=chosen.bandwidth_m,
        knot_spacing_m=knot_spacing,
        rule="one-standard-error rule: largest bandwidth with hold-out RMS <= min + SE(min) across folds",
        candidates=tuple(results),
    )


def project_onto_line(
    line: ResampledLine, points_xy: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Nearest arc length, signed lateral offset (+left) and distance for each point.

    Nearest 1 m sample via KD-tree, refined by projecting onto the two adjacent
    segments of the periodic polyline.
    """
    xy = line.xyz_m[:, :2]
    n = len(xy)
    pts = np.asarray(points_xy, dtype=np.float64)
    _, idx = cKDTree(xy).query(pts)
    best_d = np.full(len(pts), np.inf)
    best_s = np.zeros(len(pts))
    best_lat = np.zeros(len(pts))
    for a_idx in (idx - 1, idx):
        a = np.mod(a_idx, n)
        b = np.mod(a + 1, n)
        pa, pb = xy[a], xy[b]
        seg = pb - pa
        seg_len2 = np.einsum("ij,ij->i", seg, seg)
        rel = pts - pa
        t = np.where(seg_len2 > 0.0, np.einsum("ij,ij->i", rel, seg) / np.maximum(seg_len2, 1e-300), 0.0)
        t = np.clip(t, 0.0, 1.0)
        q = pa + t[:, None] * seg
        d = np.hypot(*(pts - q).T)
        seg_len = np.sqrt(seg_len2)
        cross = np.where(
            seg_len > 0.0, (seg[:, 0] * rel[:, 1] - seg[:, 1] * rel[:, 0]) / np.maximum(seg_len, 1e-300), 0.0
        )
        s_val = np.mod(line.s_m[a] + t * seg_len, line.length_3d_m)
        better = d < best_d
        best_d = np.where(better, d, best_d)
        best_s = np.where(better, s_val, best_s)
        best_lat = np.where(better, cross, best_lat)
    return best_s, best_lat, best_d


def loop_direction(xy: np.ndarray) -> Direction:
    """Signed shoelace area of progression: positive is counterclockwise in a right-handed frame.

    A figure-eight has near-zero net turning; below a quarter of a full loop's
    equivalent area sign strength it is reported as ``mixed``.
    """
    x, y = xy[:, 0], xy[:, 1]
    area2 = float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    yaw = np.arctan2(np.diff(np.concatenate((y, y[:1]))), np.diff(np.concatenate((x, x[:1]))))
    turning = float(np.sum(np.angle(np.exp(1j * np.diff(yaw)))))
    if abs(turning) < math.pi:
        return Direction.MIXED
    return Direction.COUNTERCLOCKWISE if area2 > 0.0 else Direction.CLOCKWISE


@dataclass(frozen=True, slots=True)
class LapGeometry:
    lap_number: int
    t_s: np.ndarray
    xyz_m: np.ndarray
    start_xyz_m: np.ndarray
    end_xyz_m: np.ndarray
    sector_xy_m: tuple[np.ndarray | None, np.ndarray | None]
    cleaning: CleaningReport
    elevation_cleaning: ElevationCleaningReport
    spline_length_m: float
    smoothing: SmoothingSelection
    raw_polyline_length_m: float


def _interp_at(t_s: np.ndarray, xyz: np.ndarray, t_query: float) -> np.ndarray | None:
    if t_query < t_s[0] or t_query > t_s[-1]:
        return None
    return np.array([np.interp(t_query, t_s, xyz[:, k]) for k in range(3)])


def _lap_raw(lap: LapRecord, cache: RawSourceCache) -> tuple[np.ndarray, np.ndarray]:
    cached = cache.get("openf1", lap.location_sha256)
    payload = json.loads(cached.read_bytes().decode("utf-8"))
    t0 = parse_openf1_time(lap.date_start)
    rows = [r for r in payload if all(r.get(k) is not None for k in ("x", "y", "z"))]
    if len(rows) < 8:
        raise CompileError(f"lap {lap.lap_number} has only {len(rows)} usable location samples")
    t = np.array([(parse_openf1_time(str(r["date"])) - t0).total_seconds() for r in rows], dtype=np.float64)
    xyz = np.array([[float(r["x"]), float(r["y"]), float(r["z"])] for r in rows], dtype=np.float64)
    return t, xyz


def process_lap(
    lap: LapRecord,
    t_raw: np.ndarray,
    xyz_raw_units: np.ndarray,
    *,
    scale: float,
    origin_units: np.ndarray,
    z_quantum_m: float | None = None,
    grade_ceiling: float = ROAD_GRADE_CEILING,
) -> LapGeometry:
    """Clean one lap and fit it.

    ``z_quantum_m`` defaults to one raw coordinate unit expressed in metres --
    the source publishes integers -- so the elevation plausibility budget allows
    a single quantisation step per sampling interval on top of the gradient
    ceiling.
    """
    xyz_all = (xyz_raw_units - origin_units) * scale
    t_all, xyz_all, cleaning = clean_samples(t_raw, xyz_all)
    xyz_all, elevation_cleaning = reject_z_outliers(
        t_all,
        xyz_all,
        z_quantum_m=abs(scale) if z_quantum_m is None else z_quantum_m,
        grade_ceiling=grade_ceiling,
    )
    start = _interp_at(t_all, xyz_all, 0.0)
    end = _interp_at(t_all, xyz_all, lap.lap_duration_s)
    if start is None or end is None:
        raise CompileError(
            f"lap {lap.lap_number}: location window does not bracket the lap boundary times "
            f"(samples span {t_all[0]:.2f}..{t_all[-1]:.2f} s, lap is 0..{lap.lap_duration_s:.2f} s)"
        )
    gap = float(np.hypot(*(end[:2] - start[:2])))
    gap_limit = SPEED_CEILING_MPS * cleaning.median_dt_s
    if gap > gap_limit:
        raise CompileError(
            f"lap {lap.lap_number} does not close: the timing-line crossings at t=0 and t=lap_duration are "
            f"{gap:.1f} m apart, more than one sample interval at the speed ceiling ({gap_limit:.1f} m)"
        )
    inside = (t_all >= 0.0) & (t_all < lap.lap_duration_s)
    t_lap = np.concatenate(([0.0], t_all[inside]))
    xyz_lap = np.vstack([start, xyz_all[inside]])
    s1, s2, _ = lap.sector_durations_s
    sector_xy: tuple[np.ndarray | None, np.ndarray | None] = (None, None)
    if s1 is not None and s2 is not None:
        p1 = _interp_at(t_all, xyz_all, s1)
        p2 = _interp_at(t_all, xyz_all, s1 + s2)
        sector_xy = (None if p1 is None else p1[:2], None if p2 is None else p2[:2])
    smoothing = choose_smoothing(xyz_lap)
    tck = fit_periodic_spline(xyz_lap, smoothing.chosen_bandwidth_m)
    length = resample_by_arclength(tck, dense_per_m=4.0).length_3d_m
    return LapGeometry(
        lap_number=lap.lap_number,
        t_s=t_lap,
        xyz_m=xyz_lap,
        start_xyz_m=start,
        end_xyz_m=end,
        sector_xy_m=sector_xy,
        cleaning=cleaning,
        elevation_cleaning=elevation_cleaning,
        spline_length_m=length,
        smoothing=smoothing,
        raw_polyline_length_m=polyline_length(np.vstack([xyz_lap[:, :2], xyz_lap[:1, :2]])),
    )


@dataclass(frozen=True, slots=True)
class RegistrationReport:
    reference_lap: int
    bin_m: float
    bins: int
    empty_bins_interpolated: int
    per_lap_lateral_rms_m: dict[int, float]
    per_lap_lateral_p95_m: dict[int, float]


def register_and_aggregate(laps: list[LapGeometry]) -> tuple[np.ndarray, RegistrationReport]:
    """Median lateral offset and elevation of every lap relative to a reference lap, per arc bin."""
    lengths = np.array([lap.spline_length_m for lap in laps])
    ref_idx = int(np.argsort(lengths)[len(lengths) // 2])
    ref = laps[ref_idx]
    ref_tck = fit_periodic_spline(ref.xyz_m, ref.smoothing.chosen_bandwidth_m)
    ref_line = resample_by_arclength(ref_tck)
    length_m = ref_line.length_3d_m
    n_bins = max(8, round(length_m / REGISTRATION_BIN_M))
    edges = np.linspace(0.0, length_m, n_bins + 1)
    lat_bins: list[list[float]] = [[] for _ in range(n_bins)]
    z_bins: list[list[float]] = [[] for _ in range(n_bins)]
    lat_rms: dict[int, float] = {}
    lat_p95: dict[int, float] = {}
    for lap in laps:
        s, lat, _ = project_onto_line(ref_line, lap.xyz_m[:, :2])
        z_ref = np.interp(s, ref_line.s_m, ref_line.xyz_m[:, 2])
        dz = lap.xyz_m[:, 2] - z_ref
        idx = np.clip(np.searchsorted(edges, s, side="right") - 1, 0, n_bins - 1)
        for i, l_val, dz_val in zip(idx, lat, dz, strict=True):
            lat_bins[i].append(float(l_val))
            z_bins[i].append(float(dz_val))
        lat_rms[lap.lap_number] = float(np.sqrt(np.mean(lat**2)))
        lat_p95[lap.lap_number] = float(np.percentile(np.abs(lat), 95))
    centres = 0.5 * (edges[:-1] + edges[1:])
    med_lat = np.array([np.median(b) if b else np.nan for b in lat_bins])
    med_dz = np.array([np.median(b) if b else np.nan for b in z_bins])
    empty = int(np.sum(np.isnan(med_lat)))
    med_lat = _periodic_fill(centres, med_lat, length_m)
    med_dz = _periodic_fill(centres, med_dz, length_m)
    base = np.column_stack(
        [np.interp(centres, ref_line.s_m, ref_line.xyz_m[:, k], period=length_m) for k in range(3)]
    )
    cos_yaw = np.interp(centres, ref_line.s_m, np.cos(ref_line.yaw_rad), period=length_m)
    sin_yaw = np.interp(centres, ref_line.s_m, np.sin(ref_line.yaw_rad), period=length_m)
    norm = np.maximum(np.hypot(cos_yaw, sin_yaw), 1e-12)
    normal = np.column_stack([-sin_yaw / norm, cos_yaw / norm])
    points = base.copy()
    points[:, :2] += normal * med_lat[:, None]
    points[:, 2] += med_dz
    report = RegistrationReport(
        reference_lap=ref.lap_number,
        bin_m=REGISTRATION_BIN_M,
        bins=n_bins,
        empty_bins_interpolated=empty,
        per_lap_lateral_rms_m=lat_rms,
        per_lap_lateral_p95_m=lat_p95,
    )
    return points, report


def _periodic_fill(x: np.ndarray, y: np.ndarray, period: float) -> np.ndarray:
    good = ~np.isnan(y)
    if good.all():
        return y
    if not good.any():
        raise CompileError("no registered points in any bin")
    return np.interp(x, x[good], y[good], period=period)


def choose_smoothing_across_laps(
    laps: list[LapGeometry],
    candidates_m: tuple[float, ...] = SMOOTHING_BANDWIDTH_CANDIDATES_M,
    *,
    folds: int = HOLDOUT_FOLDS,
) -> SmoothingSelection:
    """Leave-laps-out selection of the bandwidth for the aggregated line.

    Hold-out on the aggregated median points alone under-smooths for
    derivatives: their noise is small, so the position-optimal bandwidth is
    narrow while curvature still needs a wider one. Here each fold aggregates
    the *training* laps, fits a candidate bandwidth and measures the residual of
    the *held-out laps' raw samples* -- the noise the line is actually meant to
    describe. The one-standard-error rule then takes the smoothest bandwidth the
    data cannot distinguish from the best, and a genuine feature (a chicane)
    still bounds it because over-smoothing raises the held-out residual.
    """
    n_laps = len(laps)
    if n_laps < 2:
        aggregated, _ = register_and_aggregate(laps)
        return choose_smoothing(aggregated, candidates_m, folds=folds)
    k_folds = min(folds, n_laps)
    all_points, _ = register_and_aggregate(laps)
    results: list[SmoothingCandidate] = []
    knot_spacing = 0.0
    for bandwidth in candidates_m:
        full = fit_periodic_spline(all_points, bandwidth)
        knot_spacing = float(full.knot_spacing_m)
        full_line = resample_by_arclength(full, dense_per_m=4.0)
        holdout: list[np.ndarray] = []
        stability: list[float] = []
        for k in range(k_folds):
            train = [lap for i, lap in enumerate(laps) if i % k_folds != k]
            test = [lap for i, lap in enumerate(laps) if i % k_folds == k]
            points, _ = register_and_aggregate(train)
            line = resample_by_arclength(fit_periodic_spline(points, bandwidth), dense_per_m=4.0)
            test_xy = np.vstack([lap.xyz_m[:, :2] for lap in test])
            holdout.append(_nearest_distance(line.xyz_m[:, :2], test_xy))
            m = min(len(line.curvature_1pm), len(full_line.curvature_1pm))
            tree = cKDTree(full_line.xyz_m[:, :2])
            _, idx = tree.query(line.xyz_m[:m, :2])
            diff = line.curvature_1pm[:m] - full_line.curvature_1pm[idx]
            stability.append(float(np.sqrt(np.mean(diff**2))))
        all_res = np.concatenate(holdout)
        fold_rms = np.array([np.sqrt(np.mean(h**2)) for h in holdout])
        se = float(np.std(fold_rms, ddof=1) / np.sqrt(len(fold_rms))) if len(fold_rms) > 1 else 0.0
        results.append(
            SmoothingCandidate(
                bandwidth_m=bandwidth,
                holdout_rms_fold_se_m=se,
                holdout_rms_m=float(np.sqrt(np.mean(all_res**2))),
                holdout_p95_m=float(np.percentile(all_res, 95)),
                curvature_stability_rms_1pm=float(np.mean(stability)),
                max_abs_curvature_1pm=float(np.max(np.abs(full_line.curvature_1pm))),
            )
        )
    best = min(results, key=lambda r: r.holdout_rms_m)
    threshold = best.holdout_rms_m + best.holdout_rms_fold_se_m
    chosen = max((r for r in results if r.holdout_rms_m <= threshold), key=lambda r: r.bandwidth_m)
    return SmoothingSelection(
        chosen_bandwidth_m=chosen.bandwidth_m,
        knot_spacing_m=knot_spacing,
        rule=(
            f"leave-laps-out over {k_folds} folds of {n_laps} laps; one-standard-error rule: "
            "largest bandwidth with held-out raw-sample RMS <= min + SE(min)"
        ),
        candidates=tuple(results),
    )


@dataclass(frozen=True, slots=True)
class ElevationCandidate:
    bandwidth_m: float
    holdout_vertical_rms_m: float
    holdout_vertical_p95_m: float
    holdout_vertical_fold_se_m: float
    max_abs_grade_rad: float
    p99_abs_grade_rad: float


@dataclass(frozen=True, slots=True)
class ElevationSelection:
    chosen_bandwidth_m: float
    rule: str
    candidates: tuple[ElevationCandidate, ...]


def _elevation_holdout_pairs(
    laps: list[LapGeometry], aggregated: np.ndarray, folds: int
) -> tuple[list[tuple[np.ndarray, np.ndarray]], str]:
    """``(training points, held-out xyz)`` pairs for the vertical hold-out, built once."""
    n_laps = len(laps)
    if n_laps >= 2:
        k_folds = min(folds, n_laps)
        pairs: list[tuple[np.ndarray, np.ndarray]] = []
        for k in range(k_folds):
            train = [lap for i, lap in enumerate(laps) if i % k_folds != k]
            test = [lap for i, lap in enumerate(laps) if i % k_folds == k]
            points, _ = register_and_aggregate(train)
            pairs.append((points, np.vstack([lap.xyz_m for lap in test])))
        return pairs, f"leave-laps-out over {k_folds} folds of {n_laps} laps"
    pairs = []
    for k in range(folds):
        mask = np.ones(len(aggregated), dtype=bool)
        mask[k::folds] = False
        if mask.sum() < 8:
            continue
        pairs.append((aggregated[mask], aggregated[~mask]))
    if not pairs:
        raise CompileError("not enough points for an elevation hold-out")
    return pairs, f"interleaved {folds}-fold hold-out on the aggregated points (a single lap)"


def choose_elevation_smoothing(
    laps: list[LapGeometry],
    aggregated: np.ndarray,
    xy_tck: Any,
    candidates_m: tuple[float, ...] = ELEVATION_BANDWIDTH_CANDIDATES_M,
    *,
    folds: int = HOLDOUT_FOLDS,
) -> ElevationSelection:
    """Choose the elevation channel's bandwidth on *vertical* evidence.

    Reusing the horizontal bandwidth is part of how a single bad z sample reached
    ``grade_rad``: that bandwidth is selected to describe the lateral scatter of a
    racing line, a different signal from a road's elevation profile. Here each
    fold aggregates the training laps, fits a candidate bandwidth and measures the
    vertical residual of the held-out laps' z samples at their projected arc
    length; the one-standard-error rule then takes the smoothest bandwidth the
    data cannot distinguish from the best. The selection never looks at the
    resulting grade, so it cannot be tuned to satisfy the plausibility bound; the
    grade each candidate implies is recorded so a reader can see the consequence.
    """
    pairs, rule = _elevation_holdout_pairs(laps, aggregated, folds)
    results: list[ElevationCandidate] = []
    for bandwidth in candidates_m:
        full = fit_periodic_spline(aggregated, bandwidth)
        grade = np.abs(resample_by_arclength(xy_tck, z_tck=full, dense_per_m=4.0).grade_rad)
        residuals: list[np.ndarray] = []
        for train_points, test_xyz in pairs:
            fold = resample_by_arclength(fit_periodic_spline(train_points, bandwidth), dense_per_m=4.0)
            s, _, _ = project_onto_line(fold, test_xyz[:, :2])
            z_fit = np.interp(s, fold.s_m, fold.xyz_m[:, 2], period=fold.length_3d_m)
            residuals.append(test_xyz[:, 2] - z_fit)
        all_res = np.concatenate(residuals)
        fold_rms = np.array([np.sqrt(np.mean(r**2)) for r in residuals])
        se = float(np.std(fold_rms, ddof=1) / np.sqrt(len(fold_rms))) if len(fold_rms) > 1 else 0.0
        results.append(
            ElevationCandidate(
                bandwidth_m=bandwidth,
                holdout_vertical_rms_m=float(np.sqrt(np.mean(all_res**2))),
                holdout_vertical_p95_m=float(np.percentile(np.abs(all_res), 95)),
                holdout_vertical_fold_se_m=se,
                max_abs_grade_rad=float(np.max(grade)),
                p99_abs_grade_rad=float(np.percentile(grade, 99)),
            )
        )
    best = min(results, key=lambda r: r.holdout_vertical_rms_m)
    threshold = best.holdout_vertical_rms_m + best.holdout_vertical_fold_se_m
    chosen = max((r for r in results if r.holdout_vertical_rms_m <= threshold), key=lambda r: r.bandwidth_m)
    return ElevationSelection(
        chosen_bandwidth_m=chosen.bandwidth_m,
        rule=(
            f"{rule}; one-standard-error rule on the held-out vertical residual (largest bandwidth with "
            "RMS <= min + SE(min)); the resulting grade is not an input to the choice"
        ),
        candidates=tuple(results),
    )


@dataclass(frozen=True, slots=True)
class ElevationChannel:
    """Whether the compiled elevation profile may be published, and the evidence for it."""

    available: bool
    reason: str | None
    grade_ceiling: float
    max_abs_grade_rad: float
    p99_abs_grade_rad: float
    z_span_m: float
    bandwidth_m: float
    selection_rule: str
    rejected_z_samples: int
    raw_z_samples: int
    rejected_z_fraction: float
    steep_segments_retained: int
    rejection_cap_reached: bool
    nan_emission_blocked_by: str | None = None


def assess_elevation(
    line: ResampledLine,
    laps: list[LapGeometry],
    selection: ElevationSelection,
    *,
    grade_ceiling: float = ROAD_GRADE_CEILING,
) -> ElevationChannel:
    """Decide whether the smoothed elevation profile is publishable.

    Grade enters the engine's force balance as a gravitational term, so an
    implausible grade is fake energy demand. If any 1 m sample still exceeds the
    declared ceiling after z-outlier rejection and elevation-specific smoothing,
    the profile is not a measurement of a road: the channel is declared
    unavailable, and it is neither published as geometry nor replaced by zeros.
    """
    grade = np.abs(line.grade_rad)
    max_grade = float(np.max(grade))
    rejected = sum(lap.elevation_cleaning.rejected_spikes for lap in laps)
    raw_samples = sum(lap.elevation_cleaning.samples for lap in laps)
    capped = any(lap.elevation_cleaning.rejection_cap_reached for lap in laps)
    available = max_grade <= grade_ceiling
    reason: str | None = None
    if not available:
        reason = (
            f"max |grade| {max_grade:.4f} exceeds the declared ceiling {grade_ceiling} after rejecting "
            f"{rejected} of {raw_samples} raw z samples as isolated spikes and choosing the elevation "
            f"bandwidth ({selection.chosen_bandwidth_m:g} m) on held-out vertical residual"
        )
        if capped:
            reason += (
                "; the rejection cap was reached, so the z channel is not repairable by outlier "
                "rejection at all"
            )
    return ElevationChannel(
        available=available,
        reason=reason,
        grade_ceiling=grade_ceiling,
        max_abs_grade_rad=max_grade,
        p99_abs_grade_rad=float(np.percentile(grade, 99)),
        z_span_m=float(np.max(line.xyz_m[:, 2]) - np.min(line.xyz_m[:, 2])),
        bandwidth_m=selection.chosen_bandwidth_m,
        selection_rule=selection.rule,
        rejected_z_samples=rejected,
        raw_z_samples=raw_samples,
        rejected_z_fraction=rejected / raw_samples if raw_samples else 0.0,
        steep_segments_retained=sum(lap.elevation_cleaning.steep_segments_retained for lap in laps),
        rejection_cap_reached=capped,
    )


def build_centreline(
    line: ResampledLine, elevation: ElevationChannel
) -> tuple[CompiledCentreline, str | None]:
    """Compiled arrays; an unavailable elevation channel is ``nan``, never zeros.

    ``CompiledCentreline`` currently refuses a non-finite value in any required
    array, so the null elevation channel cannot be stored yet -- the handoff asks
    the coordinator for a channel-availability seam. Until that exists the
    measured (and implausible) z and grade are kept *unaltered*, together with the
    flag and the notes that name them, so the independent validator's
    ``grade_bounded`` check fails and the circuit stays at a status the validator
    refuses. Neither branch ships a fabricated profile.
    """
    common: dict[str, Any] = {
        "s_m": line.s_m,
        "x_m": line.xyz_m[:, 0],
        "y_m": line.xyz_m[:, 1],
        "yaw_rad": line.yaw_rad,
        "curvature_1pm": line.curvature_1pm,
        "length_m": line.length_3d_m,
    }
    measured: dict[str, Any] = {"z_m": line.xyz_m[:, 2], "grade_rad": line.grade_rad}
    if elevation.available:
        return CompiledCentreline(**common, **measured), None
    unknown = np.full(len(line.s_m), np.nan, dtype=np.float64)
    try:
        return CompiledCentreline(**common, z_m=unknown, grade_rad=unknown), None
    except ValueError as exc:
        return CompiledCentreline(**common, **measured), (
            f"CompiledCentreline refuses a null elevation channel: {exc}"
        )


def _iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_ready(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_json_ready(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def compile_track(manifest_path: Path, paths: Paths) -> TrackPackage:
    """Compile ``configs/tracks/<track_id>/source.yaml`` into ``artifacts/tracks/<track_id>/``.

    Offline: every OpenF1 payload must already be in the raw cache (see
    :func:`~afterlap_core.tracks.ingest.openf1.ingest_location_session`).
    """
    manifest = load_manifest(Path(manifest_path))
    cache = RawSourceCache(paths=paths)
    official = manifest.official_length.value_m

    summaries: list[IngestResult] = []
    for session in manifest.sessions:
        summary = load_ingest_summary(manifest.track_id, session.session_key, paths)
        if session.driver_number is not None and summary.driver_number != session.driver_number:
            raise CompileError(
                f"manifest asks for driver {session.driver_number} in session {session.session_key} but the "
                f"ingest summary holds driver {summary.driver_number}; re-run ingest with that driver"
            )
        summaries.append(summary)

    raw_laps: list[tuple[LapRecord, np.ndarray, np.ndarray]] = []
    for summary in summaries:
        for lap_record in summary.laps:
            t, xyz = _lap_raw(lap_record, cache)
            raw_laps.append((lap_record, t, xyz))
    if not raw_laps:
        raise CompileError("no laps available across the manifest sessions")

    per_lap_raw_lengths: list[float] = []
    for record, t, xyz in raw_laps:
        order = np.argsort(t)
        inside = (t[order] >= 0.0) & (t[order] < record.lap_duration_s)
        xy = xyz[order][inside, :2]
        per_lap_raw_lengths.append(polyline_length(xy) + float(np.hypot(*(xy[0] - xy[-1]))))
    scale = infer_scale(float(np.median(per_lap_raw_lengths)), official)
    if not scale.accepted:
        raise CompileError(f"coordinate scale could not be inferred: {scale.evidence}")

    origin_units = np.median(raw_laps[0][2], axis=0)
    laps: list[LapGeometry] = []
    lap_failures: dict[int, str] = {}
    for record, t, xyz in raw_laps:
        try:
            laps.append(process_lap(record, t, xyz, scale=scale.scale_m_per_unit, origin_units=origin_units))
        except CompileError as exc:
            lap_failures[record.lap_number] = str(exc)
    if not laps:
        raise CompileError(f"every lap failed processing: {lap_failures}")

    aggregated, registration = register_and_aggregate(laps)
    final_smoothing = choose_smoothing_across_laps(laps)
    tck = fit_periodic_spline(aggregated, final_smoothing.chosen_bandwidth_m)
    elevation_smoothing = choose_elevation_smoothing(laps, aggregated, tck)
    z_tck = fit_periodic_spline(aggregated, elevation_smoothing.chosen_bandwidth_m)
    unaligned = resample_by_arclength(tck, z_tck=z_tck)

    crossings = np.vstack([lap.start_xyz_m for lap in laps] + [lap.end_xyz_m for lap in laps])
    timing_xy = np.median(crossings[:, :2], axis=0)
    s0, _, timing_dist = project_onto_line(unaligned, timing_xy[None, :])
    crossing_scatter = float(np.sqrt(np.mean(np.sum((crossings[:, :2] - timing_xy) ** 2, axis=1))))
    line = resample_by_arclength(tck, z_tck=z_tck, s_offset_m=float(s0[0]))
    if abs(line.length_3d_m - unaligned.length_3d_m) > 1e-6:
        raise CompileError("timing-line alignment changed the total length; this is a bug")

    elevation = assess_elevation(line, laps, elevation_smoothing)
    centreline, nan_blocked = build_centreline(line, elevation)
    elevation = replace(elevation, nan_emission_blocked_by=nan_blocked)
    direction = loop_direction(line.xyz_m[:, :2])

    residuals: dict[int, dict[str, float]] = {}
    for lap in laps:
        _, lat, dist = project_onto_line(line, lap.xyz_m[:, :2])
        residuals[lap.lap_number] = {
            "lateral_rms_m": float(np.sqrt(np.mean(lat**2))),
            "lateral_p50_m": float(np.percentile(np.abs(lat), 50)),
            "lateral_p95_m": float(np.percentile(np.abs(lat), 95)),
            "lateral_max_m": float(np.max(dist)),
            "start_to_end_crossing_gap_m": float(np.hypot(*(lap.start_xyz_m[:2] - lap.end_xyz_m[:2]))),
        }

    sector_s: list[list[float]] = [[], []]
    for lap in laps:
        for k, p in enumerate(lap.sector_xy_m):
            if p is not None:
                s_val, _, _ = project_onto_line(line, p[None, :])
                sector_s[k].append(float(s_val[0]))
    sectors: tuple[SRange, ...] = ()
    if sector_s[0] and sector_s[1]:
        b1 = float(np.median(sector_s[0]))
        b2 = float(np.median(sector_s[1]))
        if 0.0 < b1 < b2 < line.length_3d_m:
            sectors = (
                SRange(start_s_m=0.0, end_s_m=b1),
                SRange(start_s_m=b1, end_s_m=b2),
                SRange(start_s_m=b2, end_s_m=line.length_3d_m),
            )

    raw_kappa = np.concatenate([raw_finite_difference_curvature(lap.xyz_m[:, :2]) for lap in laps])

    length_error = abs(line.length_3d_m - official) / official
    closure = centreline.closure_error_m
    flags: list[str] = []
    if length_error > 0.02:
        flags.append("length_error_exceeds_2pct")
    if length_error > max(0.001, 5.0 / official):
        flags.append("length_outside_validation_tolerance")
    if closure > 0.5:
        flags.append("closure_error_exceeds_0.5m")
    if manifest.direction and manifest.direction != direction.value:
        flags.append("direction_disagrees_with_manifest")
    if scale.deviation_fraction > 0.03:
        flags.append("scale_inference_weak")
    if lap_failures:
        flags.append("some_laps_failed_processing")
    if not elevation.available:
        flags.append("elevation_channel_unavailable")
    if elevation.nan_emission_blocked_by is not None:
        flags.append("elevation_null_channel_not_storable")
    if elevation.rejected_z_samples:
        flags.append("z_outliers_rejected")

    out_dir = paths.artifacts / "tracks" / manifest.track_id
    out_dir.mkdir(parents=True, exist_ok=True)
    arrays_sha = centreline.to_npz(out_dir / "centreline.npz")

    length_source = SourceRecord(
        source_id=f"official-length-{manifest.track_id}",
        title=manifest.official_length.title,
        url=manifest.official_length.source_url,
        retrieved_at=manifest.official_length.retrieved_at,
        sha256=manifest.official_length.sha256,
        permission=manifest.official_length.permission,
        priority=5,
        locator=f"circuit length {official:g} m",
    )
    sources: list[SourceRecord] = [length_source]
    seen: set[str] = set()
    for summary in summaries:
        for src in summary.sources:
            key = src.sha256 or src.url
            if key not in seen:
                seen.add(key)
                sources.append(src)

    notes: list[str] = [
        "compiled from OpenF1 location telemetry; awaiting the independent geometry validator",
        "geometry is the median driven line of one driver, not a surveyed centreline",
        "corridor unknown; elevation scale assumed equal to x/y and unvalidated",
    ]
    if elevation.available:
        notes.append(
            f"elevation channel accepted: max |grade| {elevation.max_abs_grade_rad:.4f} within the declared "
            f"ceiling {elevation.grade_ceiling}; {elevation.rejected_z_samples} of {elevation.raw_z_samples} "
            f"raw z samples rejected as isolated spikes; elevation bandwidth "
            f"{elevation.bandwidth_m:g} m chosen on held-out vertical residual"
        )
    else:
        notes.append(f"elevation rejected: {elevation.reason}")
        if elevation.nan_emission_blocked_by is not None:
            notes.append(
                "the null elevation channel could not be stored: "
                f"{elevation.nan_emission_blocked_by}. z and grade in the arrays are the measured, "
                "out-of-bounds values; they are not a road profile and must not be read as one. The "
                "geometry checks fail on them by design"
            )

    package = TrackPackage(
        track_id=manifest.track_id,
        display_name=manifest.display_name,
        direction=direction,
        nominal_length_m=official,
        geometry=GeometryDescriptor(
            sample_spacing_m=CANONICAL_SPACING_M,
            point_count=centreline.point_count,
            crs=LOCAL_CRS,
            arrays_path="centreline.npz",
            corridor_quality=CorridorQuality.UNKNOWN,
            provenance=GeometryProvenance.OPENF1_LOCATION_TELEMETRY,
            arrays_sha256=arrays_sha,
        ),
        features=TrackFeatures(start_finish_s_m=0.0, sectors=sectors, corners=(), pit_lane_excluded=True),
        event_overlay=None,
        sources=tuple(sources),
        validation=ValidationReport(
            status=ReadinessStatus.DISCOVERED,
            closure_error_m=closure,
            length_error_fraction=length_error,
            report_path="compile_report.json",
            official_length_m=official,
            checks={},
            notes=tuple(notes),
        ),
    ).with_hash()

    report = {
        "compiler": "afterlap_core.tracks.compile",
        "compiled_at": _iso_now(),
        "track_id": manifest.track_id,
        "manifest_path": str(manifest.path),
        "package_hash": package.package_hash,
        "arrays_sha256": arrays_sha,
        "official_length_m": official,
        "official_length_source": length_source.model_dump(mode="json"),
        "sessions": [
            {
                "session_key": s.session_key,
                "driver_number": s.driver_number,
                "session": s.session,
                "laps_used": [lap.lap_number for lap in s.laps],
                "rejected": s.rejected,
                "median_lap_duration_s": s.median_lap_duration_s,
                "clean_laps_by_driver": s.clean_laps_by_driver,
            }
            for s in summaries
        ],
        "frame": {
            "crs": LOCAL_CRS,
            "transform": "local = scale_m_per_unit * (raw - origin_units); "
            "axes as published by OpenF1 (handedness unverified)",
            "origin_units": origin_units.tolist(),
            "scale": asdict(scale),
            "per_lap_raw_polyline_length_units": per_lap_raw_lengths,
        },
        "laps": [
            {
                "lap_number": lap.lap_number,
                "cleaning": asdict(lap.cleaning),
                "elevation_cleaning": asdict(lap.elevation_cleaning),
                "raw_polyline_length_m": lap.raw_polyline_length_m,
                "spline_length_m": lap.spline_length_m,
                "smoothing_bandwidth_m": lap.smoothing.chosen_bandwidth_m,
                "knot_spacing_m": lap.smoothing.knot_spacing_m,
                "smoothing_candidates": [asdict(c) for c in lap.smoothing.candidates],
                "residual_vs_final": residuals[lap.lap_number],
            }
            for lap in laps
        ],
        "lap_failures": lap_failures,
        "registration": asdict(registration),
        "final_smoothing": {
            "chosen_bandwidth_m": final_smoothing.chosen_bandwidth_m,
            "knot_spacing_m": final_smoothing.knot_spacing_m,
            "method": "periodic penalised cubic B-spline (P-spline), fixed knots, circular second-difference "
            "penalty; bandwidth is Silverman's equivalent-kernel width",
            "rule": final_smoothing.rule,
            "candidates": [asdict(c) for c in final_smoothing.candidates],
        },
        "elevation_smoothing": {
            "chosen_bandwidth_m": elevation_smoothing.chosen_bandwidth_m,
            "method": "the elevation channel is fitted on the same aggregated points and the same knots as "
            "the horizontal channel but with its own penalty weight; z comes from that fit, x, y, yaw and "
            "curvature from the horizontal one",
            "rule": elevation_smoothing.rule,
            "candidates": [asdict(c) for c in elevation_smoothing.candidates],
        },
        "geometry": {
            "length_3d_m": line.length_3d_m,
            "length_2d_m": line.length_2d_m,
            "length_error_fraction": length_error,
            "length_error_m": line.length_3d_m - official,
            "point_count": centreline.point_count,
            "closure_error_m": closure,
            "direction_computed": direction.value,
            "direction_manifest": manifest.direction,
            "max_abs_curvature_1pm": float(np.max(np.abs(line.curvature_1pm))),
            "min_turn_radius_m": float(1.0 / max(np.max(np.abs(line.curvature_1pm)), 1e-9)),
            "raw_finite_difference_curvature_max_abs_1pm": float(np.max(np.abs(raw_kappa))),
            "raw_finite_difference_curvature_p95_abs_1pm": float(np.percentile(np.abs(raw_kappa), 95)),
            "z_range_m": [float(np.min(line.xyz_m[:, 2])), float(np.max(line.xyz_m[:, 2]))],
            "max_abs_grade_rad": float(np.max(np.abs(line.grade_rad))),
            "elevation": asdict(elevation),
            "elevation_quality": "unvalidated: OpenF1 z scale assumed equal to x/y; no survey cross-check. "
            "The published channel is bounded by the declared road-gradient ceiling and the count of "
            "rejected z samples is recorded; an out-of-bounds profile is declared unavailable, not zeroed",
        },
        "timing_line": {
            "method": "median of per-lap positions interpolated at the OpenF1 lap date_start and "
            "date_start+lap_duration, projected onto the final line; arrays rotated so s=0 there "
            "without re-fitting",
            "s_offset_applied_m": float(s0[0]),
            "distance_from_line_m": float(timing_dist[0]),
            "crossing_scatter_rms_m": crossing_scatter,
            "length_before_alignment_m": unaligned.length_3d_m,
            "length_after_alignment_m": line.length_3d_m,
        },
        "sectors": {
            "method": "median across laps of positions at cumulative OpenF1 sector durations; "
            "timing-derived, not FIA map",
            "boundaries_s_m": [float(np.median(v)) if v else None for v in sector_s],
        },
        "unavailable": {
            "elevation": elevation.reason,
            "corridor": "unknown: no surveyed or validated boundaries; width arrays are nan",
            "mu": "not claimed: reference grip stays a labelled synthetic assumption on the simulator side",
            "corners": "not labelled: requires the FIA circuit map (event overlay worker)",
        },
        "flags": flags,
    }
    (out_dir / "compile_report.json").write_text(json.dumps(_json_ready(report), indent=2), encoding="utf-8")
    (out_dir / "package.json").write_text(json.dumps(package.to_schema_dict(), indent=2), encoding="utf-8")
    if manifest.path is not None:
        manifest_copy = out_dir / "manifest_used.yaml"
        manifest_copy.write_text(manifest.path.read_text(encoding="utf-8"), encoding="utf-8")
    return package


__all__ = [
    "ELEVATION_BANDWIDTH_CANDIDATES_M",
    "KNOT_SPACING_M",
    "LOCAL_CRS",
    "ROAD_GRADE_CEILING",
    "SCALE_CANDIDATES",
    "SMOOTHING_BANDWIDTH_CANDIDATES_M",
    "SPEED_CEILING_MPS",
    "VERTICAL_SPEED_CEILING_MPS",
    "CleaningReport",
    "CompileError",
    "ElevationCandidate",
    "ElevationChannel",
    "ElevationCleaningReport",
    "ElevationSelection",
    "LapGeometry",
    "ManifestSession",
    "OfficialLength",
    "PeriodicSpline",
    "RegistrationReport",
    "ResampledLine",
    "ScaleInference",
    "SmoothingCandidate",
    "SmoothingSelection",
    "TrackManifest",
    "assess_elevation",
    "build_centreline",
    "choose_elevation_smoothing",
    "choose_smoothing",
    "choose_smoothing_across_laps",
    "clean_samples",
    "compile_track",
    "fit_periodic_spline",
    "infer_scale",
    "load_manifest",
    "loop_direction",
    "polyline_length",
    "process_lap",
    "project_onto_line",
    "raw_finite_difference_curvature",
    "register_and_aggregate",
    "reject_z_outliers",
    "resample_by_arclength",
]
