from __future__ import annotations

import math
from dataclasses import dataclass

SECTION_A_URL = (
    "https://www.fia.com/system/files/documents/"
    "fia_2026_f1_regulations_-_section_a_general_provisions_-_iss_03_-_2026-06-25.pdf"
)
SECTION_B_URL = (
    "https://www.fia.com/system/files/documents/"
    "fia_2026_f1_regulations_-_section_b_sporting_-_iss_08_-_2026-08-05_7.pdf"
)
SECTION_C_URL = (
    "https://www.fia.com/system/files/documents/"
    "fia_2026_f1_regulations_-_section_c_technical_-_iss_20_-_2026-08-05.pdf"
)


@dataclass(frozen=True, slots=True)
class RaceRegulations2026:
    pit_lane_speed_limit_mps: float = 80 / 3.6
    required_dry_compounds: int = 2
    classified_distance_fraction: float = 0.9
    normal_duration_limit_s: float = 2 * 60 * 60
    suspended_duration_limit_s: float = 3 * 60 * 60

    def mandatory_stop_due(self, progress_m: float, distance_m: float) -> bool:
        return progress_m >= distance_m * 0.45

    def distance_is_classified(self, completed_laps: int, winner_laps: int) -> bool:
        return completed_laps >= math.floor(winner_laps * self.classified_distance_fraction)

    def points(self, position: int, completion_fraction: float, green_laps: int) -> int:
        if green_laps < 2:
            return 0
        if completion_fraction < 0.25:
            scale = (6, 4, 3, 2, 1)
        elif completion_fraction < 0.5:
            scale = (13, 10, 8, 6, 5, 4, 3, 2, 1)
        elif completion_fraction < 0.75:
            scale = (19, 14, 12, 10, 8, 6, 4, 3, 2)
        else:
            scale = (25, 18, 15, 12, 10, 8, 6, 4, 2, 1)
        return scale[position - 1] if 1 <= position <= len(scale) else 0

    def manifest(self) -> dict[str, object]:
        return {
            "name": "FIA Formula 1 2026 race subset",
            "effective_issue_dates": {
                "section_a": "2026-06-25 issue 03",
                "section_b": "2026-08-05 issue 08",
                "section_c": "2026-08-05 issue 20",
            },
            "sources": {
                "section_a": SECTION_A_URL,
                "section_b": SECTION_B_URL,
                "section_c": SECTION_C_URL,
            },
            "enforced": {
                "grid": "qualifying order, B2.5.4",
                "pit_lane_speed_limit_kph": 80,
                "pit_lane_speed_article": "B1.6.3",
                "dry_compounds": 2,
                "dry_compound_article": "B6.3.6",
                "classification_threshold": "90% of winner laps, B2.5.5",
                "race_points": "A2.2.1",
                "ers_k_max_power_kw": 350,
                "ers_k_article": "C5.2.7-10",
            },
            "session_limits": {
                "scheduled_distance": "least whole laps exceeding 305 km, Monaco 260 km, B2.5.2",
                "normal_duration_s": self.normal_duration_limit_s,
                "suspended_duration_s": self.suspended_duration_limit_s,
            },
            "limitations": (
                "No race director, stewards, safety car, suspension, component pool, scrutineering, "
                "financial, operational, or confidential event-specific FIA control data is modelled."
            ),
        }
