import asyncio
import json

import pytest
from pydantic import ValidationError
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from afterlap_api.race_server import Command, RaceServer
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
