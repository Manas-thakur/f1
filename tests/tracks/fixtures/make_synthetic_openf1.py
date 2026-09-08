"""Regenerate ``synthetic_openf1_session.json``.

SYNTHETIC FIXTURE. Nothing here is a real circuit, driver or session. The file
imitates the *shape* of the OpenF1 ``/sessions``, ``/laps`` and ``/location``
payloads so the ingest and compile tests run without the network.

Geometry: a rounded triangle ``r(theta) = R (1 + a cos 3 theta)`` driven at a
constant speed, sampled at 3.7 Hz, with Gaussian position noise, expressed as
integer decimetres like the real feed. Two synthetic drivers share one session;
driver 1 has three clean laps, driver 2 two, plus the rejects the ingest rules
must catch (lap 1, a pit-out lap, a lap with no duration, a slow lap). One clean
lap carries an exact duplicate sample, a time-duplicate and an isolated jump so
the cleaner has something to remove.

Run: ``python tests/tracks/fixtures/make_synthetic_openf1.py``
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "core"))
from afterlap_core.tracks.ingest.openf1 import location_url, location_window

SESSION_KEY = 900001
MEETING_KEY = 900000
BASE_TIME = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
RADIUS_M = 300.0
LOBE = 0.12
SPEED_MPS = 55.0
CADENCE_HZ = 3.7
NOISE_M = 0.25
Z_AMPLITUDE_M = 3.0
SCALE_M_PER_UNIT = 0.1


def curve(theta: np.ndarray) -> np.ndarray:
    r = RADIUS_M * (1.0 + LOBE * np.cos(3.0 * theta))
    return np.column_stack([r * np.cos(theta), r * np.sin(theta), Z_AMPLITUDE_M * np.sin(2.0 * theta)])


def arc_table(n: int = 200_000) -> tuple[np.ndarray, np.ndarray, float]:
    theta = np.linspace(0.0, 2.0 * np.pi, n + 1)
    pts = curve(theta)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate(([0.0], np.cumsum(seg)))
    return theta, s, float(s[-1])


def fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.%f") + "+00:00"


def main() -> None:
    rng = np.random.default_rng(20260908)
    theta_tab, s_tab, length = arc_table()
    lap_time = length / SPEED_MPS
    dt = 1.0 / CADENCE_HZ

    laps_payload: list[dict] = []
    location_payloads: dict[str, dict] = {}

    plan = {
        1: [
            (1, "first"),
            (2, "pit_out"),
            (3, "no_duration"),
            (4, "slow"),
            (5, "clean"),
            (6, "clean"),
            (7, "clean"),
        ],
        2: [(1, "first"), (2, "clean"), (3, "slow"), (4, "clean"), (5, "pit_out")],
    }
    for driver, laps in plan.items():
        t_cursor = BASE_TIME + timedelta(seconds=30.0 * driver)
        times: list[float] = []
        s_along: list[float] = []
        lap_meta: list[tuple[int, str, datetime, float]] = []
        t_rel = 0.0
        for lap_number, kind in laps:
            speed = SPEED_MPS * (0.7 if kind == "slow" else 1.0)
            duration = length / speed
            lap_meta.append((lap_number, kind, t_cursor + timedelta(seconds=t_rel), duration))
            n_samples = int(np.ceil(duration / dt))
            for k in range(n_samples):
                tk = t_rel + k * dt
                times.append(tk)
                s_along.append((tk - t_rel) * speed)
            t_rel += duration
        times_arr = np.asarray(times)
        s_arr = np.asarray(s_along) % length
        theta = np.interp(s_arr, s_tab, theta_tab)
        pts = curve(theta)
        pts[:, :2] += rng.normal(0.0, NOISE_M, size=(len(pts), 2))
        pts[:, 2] += rng.normal(0.0, 0.1, size=len(pts))
        raw = np.rint(pts / SCALE_M_PER_UNIT).astype(int)

        for lap_number, kind, start, duration in lap_meta:
            row = {
                "meeting_key": MEETING_KEY,
                "session_key": SESSION_KEY,
                "driver_number": driver,
                "lap_number": lap_number,
                "date_start": fmt(start),
                "duration_sector_1": round(duration * 0.3, 3),
                "duration_sector_2": round(duration * 0.35, 3),
                "duration_sector_3": round(duration * 0.35, 3),
                "is_pit_out_lap": kind == "pit_out",
                "lap_duration": None if kind == "no_duration" else round(duration, 3),
                "i1_speed": None,
                "i2_speed": None,
                "st_speed": None,
                "segments_sector_1": [],
                "segments_sector_2": [],
                "segments_sector_3": [],
            }
            laps_payload.append(row)
            if kind != "clean":
                continue
            window = location_window(fmt(start), round(duration, 3))
            lo = (datetime.fromisoformat(window[0]) - t_cursor).total_seconds()
            hi = (datetime.fromisoformat(window[1]) - t_cursor).total_seconds()
            mask = (times_arr >= lo) & (times_arr < hi)
            samples = [
                {
                    "date": fmt(t_cursor + timedelta(seconds=float(tk))),
                    "session_key": SESSION_KEY,
                    "driver_number": driver,
                    "meeting_key": MEETING_KEY,
                    "x": int(p[0]),
                    "y": int(p[1]),
                    "z": int(p[2]),
                }
                for tk, p in zip(times_arr[mask], raw[mask], strict=True)
            ]
            if driver == 1 and lap_number == 6:
                dup = dict(samples[40])
                samples.insert(41, dup)
                near = dict(samples[80])
                near["date"] = fmt(datetime.fromisoformat(near["date"]) + timedelta(milliseconds=20))
                near["x"] += 3
                samples.insert(81, near)
                jump = dict(samples[120])
                jump["x"] += 5000
                jump["y"] -= 4000
                samples[120] = jump
            key = f"{driver}:{lap_number}"
            location_payloads[key] = {
                "url": location_url(SESSION_KEY, driver, window),
                "payload": samples,
            }

    sessions_payload = [
        {
            "session_key": SESSION_KEY,
            "session_type": "Race",
            "session_name": "Race",
            "date_start": fmt(BASE_TIME),
            "date_end": fmt(BASE_TIME + timedelta(hours=1)),
            "meeting_key": MEETING_KEY,
            "circuit_key": 0,
            "circuit_short_name": "Synthetic",
            "country_key": 0,
            "country_code": "ZZZ",
            "country_name": "Nowhere",
            "location": "Synthetic loop",
            "gmt_offset": "00:00:00",
            "year": 2025,
            "is_cancelled": False,
        }
    ]
    doc = {
        "synthetic": True,
        "note": "SYNTHETIC FIXTURE in OpenF1 payload shape; not a real circuit, driver or session. "
        "Regenerate with tests/tracks/fixtures/make_synthetic_openf1.py",
        "session_key": SESSION_KEY,
        "truth": {
            "length_m": length,
            "radius_m": RADIUS_M,
            "lobe": LOBE,
            "speed_mps": SPEED_MPS,
            "cadence_hz": CADENCE_HZ,
            "noise_m": NOISE_M,
            "scale_m_per_unit": SCALE_M_PER_UNIT,
            "direction": "counterclockwise",
            "clean_laps": {"1": [5, 6, 7], "2": [2, 4]},
            "lap_time_s": lap_time,
        },
        "sessions_url": f"https://api.openf1.org/v1/sessions?session_key={SESSION_KEY}",
        "sessions_payload": sessions_payload,
        "laps_url": f"https://api.openf1.org/v1/laps?session_key={SESSION_KEY}",
        "laps_payload": laps_payload,
        "location_payloads": location_payloads,
    }
    out = Path(__file__).with_name("synthetic_openf1_session.json")
    out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes); length {length:.2f} m, lap {lap_time:.2f} s")


if __name__ == "__main__":
    main()
