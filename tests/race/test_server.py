import asyncio
import json
import urllib.error
import urllib.request
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import InvalidStatus

from afterlap_api.control_state import ControlState
from afterlap_api.race_server import Command, RaceServer, allowed_origins
from afterlap_contracts import DeploymentProfile
from afterlap_core.race import RaceConditionPatch, RaceSession, RaceSettings, RacingLineSettings
from afterlap_core.simulation.physics import tractive_force


def available_boost():
    recommendation = Mock(can_apply=True, mode="push")
    recommendation.payload.return_value = {}
    return recommendation


def test_zero_power_never_creates_force_at_standstill():
    assert tractive_force(0, 0, 18000) == 0


def test_controls_validate_bounds_and_require_checkpoint():
    runtime = RaceServer()
    with pytest.raises(ValidationError):
        Command.model_validate({"id": "1", "operation": "speed", "speed": float("nan")})
    with pytest.raises(ValueError, match="no saved checkpoint"):
        runtime.apply(Command(id="2", operation="restore"))
    runtime.apply(Command(id="3", operation="checkpoint"))
    runtime.apply(Command(id="4", operation="step"))
    runtime.apply(Command(id="5", operation="restore"))
    assert runtime.session.simulator.session_time_s == 0


def test_boost_command_uses_live_recommendation_guard():
    runtime = RaceServer(RaceSettings(cars=1, time_limit_s=3))
    with pytest.raises(ValueError, match="boost unavailable"):
        runtime.apply(Command(id="boost", operation="boost", car_id="car-01"))
    runtime.session.bms_profiles["car-01"] = DeploymentProfile.PUSH
    runtime.apply(Command(id="off", operation="boost", car_id="car-01", enabled=False))
    assert runtime.session.bms_profiles == {"car-01": DeploymentProfile.NEUTRAL}


def test_frame_includes_recommendations_without_simulator_truth():
    runtime = RaceServer(RaceSettings(cars=1, time_limit_s=3))
    frame = json.loads(runtime.frame())
    assert frame["recommendations"]["car-01"]["source"] == "rules_baseline"
    assert frame["recommendations"]["car-01"]["overtake_available"] is False
    assert "world" not in frame


def test_boost_targets_only_the_requested_car():
    runtime = RaceServer(RaceSettings(cars=2))
    runtime.decision_engine.recommend = Mock(return_value=available_boost())
    runtime.session.bms_profiles["car-01"] = DeploymentProfile.OVERTAKE
    runtime.apply(Command(id="boost", operation="boost", car_id="car-02"))
    assert runtime.session.bms_profiles == {"car-02": "push"}
    assert runtime.control_state.selected() == "car-02"
    with pytest.raises(ValueError, match="unknown car"):
        runtime.apply(Command(id="missing", operation="boost", car_id="car-03"))


def test_manual_boost_releases_when_the_guard_expires():
    runtime = RaceServer(RaceSettings(cars=2))
    runtime.decision_engine.recommend = Mock(return_value=available_boost())
    runtime.apply(Command(id="boost", operation="boost", car_id="car-01"))
    expired = Mock(can_apply=False, reason="battery energy depleted")
    runtime.decision_engine.recommend = Mock(return_value=expired)
    runtime.synchronize_manual_boost()
    assert runtime.session.bms_profiles == {"car-01": DeploymentProfile.NEUTRAL}


def test_changing_selection_releases_the_previous_manual_boost():
    runtime = RaceServer(RaceSettings(cars=2))
    runtime.decision_engine.recommend = Mock(return_value=available_boost())
    runtime.apply(Command(id="boost", operation="boost", car_id="car-01"))
    runtime.select("car-02")
    assert runtime.control_state.selected() == "car-02"
    assert runtime.session.bms_profiles == {"car-02": DeploymentProfile.NEUTRAL}


def test_control_state_persists_the_selected_car(tmp_path):
    path = tmp_path / "control.sqlite3"
    state = ControlState(path)
    state.select("car-02")
    state.close()
    restored = ControlState(path)
    assert restored.selected() == "car-02"
    restored.close()


def test_reset_repairs_a_selection_missing_from_the_new_grid():
    runtime = RaceServer(RaceSettings(cars=20))
    runtime.select("car-20")
    runtime.apply(Command(id="reset", operation="reset", settings=RaceSettings(cars=2)))
    assert runtime.control_state.selected() == "car-01"
    assert json.loads(runtime.frame())["selected_car_id"] == "car-01"


def test_server_starts_with_script_supplied_racing_line_settings():
    settings = RaceSettings(
        circuit="monza",
        cars=3,
        contact_mode="terminate",
        racing_line=RacingLineSettings(randomness=0.2, corner_strength=0.6),
    )
    runtime = RaceServer(settings)
    assert runtime.session.settings == settings
    assert runtime.session.frame()["settings"]["racing_line"]["randomness"] == 0.2


def test_live_conditions_update_without_resetting_the_race():
    runtime = RaceServer(RaceSettings(cars=2))
    runtime.apply(Command(id="start", operation="start"))
    runtime.session.advance(0.1)
    session = runtime.session
    time_s = session.simulator.session_time_s
    runtime.apply(
        Command(
            id="weather",
            operation="configure",
            conditions=RaceConditionPatch(weather="rainy", wetness=0.8, temperature_k=289.15, wind_mps=7.5),
        )
    )
    assert runtime.session is session
    assert runtime.generation == 0
    assert session.status == "running"
    assert session.simulator.session_time_s == time_s
    assert session.settings.weather == "rainy"
    assert session.weather.wetness_at(time_s) == 0.8
    assert session.weather.temperature_k == 289.15
    assert session.weather.wind_mps == 7.5


def test_live_conditions_require_a_value():
    runtime = RaceServer()
    with pytest.raises(ValueError, match="at least one live condition"):
        runtime.apply(Command(id="empty", operation="configure", conditions=RaceConditionPatch()))


@pytest.mark.asyncio
async def test_websocket_reset_step_and_errors():
    runtime = RaceServer()
    runtime.session = RaceSession(RaceSettings(cars=2))
    async with serve(runtime.connect, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}") as socket:
            assert json.loads(await socket.recv())["type"] == "catalogue"
            assert json.loads(await socket.recv())["status"] == "paused"
            await socket.send(json.dumps({"id": "test", "operation": "step"}))
            messages = [json.loads(await asyncio.wait_for(socket.recv(), 5)) for _ in range(2)]
            frame = next(message for message in messages if message["type"] == "frame")
            assert frame["time_s"] == 0.01
            assert "world" not in frame
            await socket.send(json.dumps({"id": "bad", "operation": "speed", "speed": 99}))
            assert json.loads(await socket.recv())["type"] == "error"


@pytest.mark.asyncio
async def test_http_boost_endpoint_accepts_post_and_rejects_other_methods():
    runtime = RaceServer(RaceSettings(cars=2))
    runtime.decision_engine.recommend = Mock(return_value=available_boost())
    async with serve(runtime.connect, "127.0.0.1", 0, process_request=runtime.process_request) as server:
        port = server.sockets[0].getsockname()[1]
        selection_url = f"http://127.0.0.1:{port}/selection/car-02"
        boost_url = f"http://127.0.0.1:{port}/boost"
        boost_off_url = f"http://127.0.0.1:{port}/boost/off"

        def post(url: str) -> tuple[int, dict[str, str]]:
            request = urllib.request.Request(url, method="POST")
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)

        selection_status, selection_payload = await asyncio.to_thread(post, selection_url)
        assert selection_status == 200
        assert selection_payload == {
            "operation": "selection",
            "car_id": "car-02",
            "status": "accepted",
        }
        assert runtime.control_state.selected() == "car-02"

        status, payload = await asyncio.to_thread(post, boost_url)
        assert status == 200
        assert payload == {"operation": "boost", "car_id": "car-02", "status": "accepted"}
        assert runtime.session.bms_profiles == {"car-02": "push"}

        off_status, off_payload = await asyncio.to_thread(post, boost_off_url)
        assert off_status == 200
        assert off_payload == {"operation": "boost-off", "car_id": "car-02", "status": "accepted"}
        assert runtime.session.bms_profiles == {"car-02": DeploymentProfile.NEUTRAL}

        def get() -> tuple[int, dict[str, str], str]:
            try:
                urllib.request.urlopen(boost_url)
            except urllib.error.HTTPError as error:
                return error.code, json.load(error), error.headers["Allow"]
            raise AssertionError("GET request unexpectedly succeeded")

        get_status, get_payload, allowed = await asyncio.to_thread(get)
        assert get_status == 405
        assert get_payload == {"error": "method not allowed"}
        assert allowed == "POST"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin", ["http://localhost:62387", "https://localhost:62387", "http://127.0.0.1:42000"]
)
async def test_forwarded_local_origin_is_accepted(origin):
    runtime = RaceServer()
    async with serve(
        runtime.connect, "127.0.0.1", 0, origins=allowed_origins("http://127.0.0.1:18760")
    ) as server:
        port = server.sockets[0].getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}", origin=origin) as websocket:
            assert json.loads(await websocket.recv())["type"] == "catalogue"


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["https://example.com", "http://localhost.example.com:62387"])
async def test_unrelated_browser_origins_are_rejected(origin):
    runtime = RaceServer()
    async with serve(
        runtime.connect, "127.0.0.1", 0, origins=allowed_origins("http://127.0.0.1:18760")
    ) as server:
        port = server.sockets[0].getsockname()[1]
        with pytest.raises(InvalidStatus) as error:
            async with connect(f"ws://127.0.0.1:{port}", origin=origin):
                pytest.fail("unrelated origin connected")
        assert error.value.response.status_code == 403
