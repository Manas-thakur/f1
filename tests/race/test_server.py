import asyncio
import json

import pytest
from pydantic import ValidationError
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import InvalidStatus

from afterlap_api.race_server import Command, RaceServer, allowed_origins
from afterlap_contracts import DeploymentProfile
from afterlap_core.race import RaceSession, RaceSettings, RacingLineSettings
from afterlap_core.simulation.physics import tractive_force


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
    assert "car-01" not in runtime.session.bms_profiles


def test_frame_includes_recommendations_without_simulator_truth():
    runtime = RaceServer(RaceSettings(cars=1, time_limit_s=3))
    frame = json.loads(runtime.frame())
    assert frame["recommendations"]["car-01"]["source"] == "rules_baseline"
    assert frame["recommendations"]["car-01"]["overtake_available"] is False
    assert "world" not in frame


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
