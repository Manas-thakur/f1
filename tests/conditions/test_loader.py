"""Config loading and the frozen-tape cache, with no network access."""

from __future__ import annotations

import json
import math

import pytest

from afterlap_core.conditions.loader import (
    ConditionsConfig,
    ConditionsUnavailable,
    environment_for,
    load_conditions,
    tape_cache_path,
)
from afterlap_core.conditions.openf1_weather import OPENF1_PERMISSION, OPENF1_WEATHER_URL
from afterlap_core.config import list_configs
from afterlap_core.tracks.provenance import RawSourceCache

from .conftest import scratch_paths

SHIPPED = (
    "static-reference",
    "monza-2025-race",
    "monaco-2025-race",
    "mexico-city-2025-race",
    "spa-2025-race",
    "synthetic-wet-gusty",
)


def test_every_shipped_conditions_document_validates():
    ids = list_configs("conditions")
    for expected in SHIPPED:
        assert expected in ids
    for cid in ids:
        from afterlap_core.conditions.loader import load_conditions_config

        config = load_conditions_config(cid)
        assert config.id == cid


def test_static_reference_is_isa_still_and_dry():
    tape = load_conditions("static-reference")
    at = tape.at(1000.0)
    assert at.pressure_pa == 101325.0
    assert at.air_temperature_k == 288.15
    assert at.wind_speed_mps == 0.0
    assert at.rainfall is False
    assert tape.provenance.is_synthetic
    assert tape.gust.enabled is False


def test_synthetic_wet_gusty_declares_its_gust_model():
    tape = load_conditions("synthetic-wet-gusty")
    assert tape.gust.enabled and tape.gust.sigma_mps == 3.0
    assert tape.at(0.0).rainfall is True
    assert tape.at(0.0).wind_direction_rad == pytest.approx(math.radians(90.0))


def _write_config(paths, text: str, cid: str) -> None:
    (paths.configs / "conditions" / f"{cid}.yaml").write_text(text, encoding="utf-8")


def test_openf1_config_without_cache_or_network_is_unavailable(tmp_path):
    paths = scratch_paths(tmp_path)
    _write_config(paths, "id: offline-case\nsource: openf1\nsession_key: 1001\n", "offline-case")
    with pytest.raises(ConditionsUnavailable):
        load_conditions("offline-case", paths, allow_network=False)


def test_openf1_config_builds_from_the_raw_cache_then_freezes(tmp_path, synthetic_openf1_records):
    paths = scratch_paths(tmp_path)
    _write_config(
        paths,
        "id: cached-case\nsource: openf1\nsession_key: 1001\naltitude_m: 162.0\naltitude_source: unit test\n",
        "cached-case",
    )
    raw = RawSourceCache(paths=paths)
    raw.put(
        json.dumps(synthetic_openf1_records["monza_like"]).encode("utf-8"),
        source="openf1",
        source_id="openf1-weather-1001",
        title="synthetic fixture standing in for an OpenF1 response",
        url=f"{OPENF1_WEATHER_URL}?session_key=1001",
        permission=OPENF1_PERMISSION,
        priority=3,
        content_type="application/json",
        filename="payload.json",
    )
    tape = load_conditions("cached-case", paths, allow_network=False)
    assert tape.provenance.raw_sha256 is not None
    assert tape.altitude_m == 162.0
    frozen = tape_cache_path("cached-case", paths)
    assert frozen.exists()
    again = load_conditions("cached-case", paths, allow_network=False)
    assert again.content_hash == tape.content_hash

    _write_config(paths, "id: cached-case\nsource: openf1\nsession_key: 1002\n", "cached-case")
    with pytest.raises(ConditionsUnavailable):
        load_conditions("cached-case", paths, allow_network=False)


def test_config_shape_is_validated():
    with pytest.raises(ValueError):
        ConditionsConfig(id="x", source="openf1")
    with pytest.raises(ValueError):
        ConditionsConfig(id="x", source="synthetic")
    with pytest.raises(ValueError):
        ConditionsConfig(id="x", source="openf1", session_key=1, altitude_m=10.0)


def test_environment_for_uses_the_absolute_yaw_when_the_track_has_one():
    tape = load_conditions("static-reference")

    class _Compiled:
        def yaw_at(self, s_m: float) -> float:
            return 1.25

    class _Sketch:
        pass

    compiled = environment_for(tape, _Compiled())
    sketch = environment_for(tape, _Sketch())
    assert compiled.heading_offset_rad == pytest.approx(1.25)
    assert sketch.heading_offset_rad is None
    assert "relative-only" in sketch.describes
    assert "heading_offset=1.2500rad" in compiled.describes
