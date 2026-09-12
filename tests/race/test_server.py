import asyncio
import json

import pytest
from pydantic import ValidationError
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import InvalidStatus

from afterlap_api.race_server import Command, RaceServer, allowed_origins
from afterlap_contracts import DeploymentProfile
from afterlap_core.race import RaceSession, RaceSettings
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


@pytest.mark.asyncio
async def test_button_press_requests_boost_and_release_returns_to_automatic():
    runtime = RaceServer()
    runtime.button_gpio = 17
    await runtime.record_button_press()
    frame = json.loads(runtime.frame())
    assert frame["button_input"]["connected"] is True
    assert frame["button_input"]["gpio_bcm"] == 17
    assert frame["button_input"]["pressed"] is True
    assert frame["button_input"]["press_count"] == 1
    assert frame["button_input"]["last_press_server_time_s"] >= 0
    assert frame["button_input"]["boost_requested"] is True
    assert frame["button_input"]["boost_engaged"] is False
    assert runtime.session.bms_profiles["car-01"] is DeploymentProfile.OVERTAKE
    runtime.session.advance(0.5)
    assert json.loads(runtime.frame())["button_input"]["boost_engaged"] is True
    await runtime.record_button_release()
    frame = json.loads(runtime.frame())
    assert frame["button_input"]["pressed"] is False
    assert frame["button_input"]["boost_requested"] is False
    assert "car-01" not in runtime.session.bms_profiles


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
