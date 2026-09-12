import json
import sys

from race import main


def test_catalogue_and_schema_are_machine_readable(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["race.py", "catalogue"])
    main()
    circuits = json.loads(capsys.readouterr().out)["circuits"]
    assert len(circuits) == 23
    assert next(item for item in circuits if item["id"] == "monza")["lap_presets"][0]["default_laps"] == 53

    monkeypatch.setattr(sys, "argv", ["race.py", "schema"])
    main()
    schema = json.loads(capsys.readouterr().out)
    assert schema["race_settings"]["properties"]["laps"]["default"] == 52
    assert schema["rl_action"]["fields"] == [
        "driver_mode",
        "deployment_profile",
        "pace_scale",
        "target_lateral_d_m",
        "low_drag",
        "manual_pedals",
        "throttle",
        "brake",
    ]


def test_generate_accepts_every_top_level_race_setting(monkeypatch, tmp_path):
    output = tmp_path / "transitions.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "race.py",
            "generate",
            "--circuit",
            "monza",
            "--cars",
            "1",
            "--laps",
            "2",
            "--dt",
            "0.02",
            "--duration",
            "1",
            "--wetness",
            "0.3",
            "--temperature-k",
            "290",
            "--wind-mps",
            "-4",
            "--no-wake",
            "--preset",
            "stress",
            "--output",
            str(output),
        ],
    )
    main()
    manifest = json.loads(output.read_text().splitlines()[0])
    assert manifest["settings"] == {
        "circuit": "monza",
        "seed": 42,
        "cars": 1,
        "laps": 2,
        "dt_s": 0.02,
        "wetness": 0.3,
        "temperature_k": 290.0,
        "wind_mps": -4.0,
        "wake": False,
        "contact_mode": "ignore",
        "time_limit_s": 1.0,
        "racing_line": {
            "enabled": True,
            "corner_strength": 0.9,
            "randomness": 0.7,
            "wander_m": 0.8,
            "lookahead_m": 65.0,
            "smoothing_m": 30.0,
            "overtake_in_corners": True,
        },
        "variability": {
            "preset": "stress",
            "driver_scale": 1.0,
            "vehicle_scale": 1.0,
            "sensor_scale": 1.0,
            "surface_scale": 1.0,
            "wind_scale": 1.0,
            "wetness_target": None,
            "weather_tau_s": 120.0,
            "drivers": {},
        },
    }
