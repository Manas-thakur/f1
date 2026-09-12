import asyncio
import json

import pytest
from pydantic import ValidationError
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import InvalidStatus

from afterlap_api.race_server import Command, RaceServer, allowed_origins
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


def test_transport_start_pause_restore_and_step_preserve_started_state():
    runtime = RaceServer()
    runtime.session = RaceSession(RaceSettings(cars=1))
    assert not runtime.session.frame()["started"]
    runtime.apply(Command(id="save", operation="checkpoint"))
    runtime.apply(Command(id="start", operation="start"))
    runtime.apply(Command(id="pause", operation="pause"))
    assert runtime.session.started
    assert runtime.session.status == "paused"
    assert runtime.session.simulator.session_time_s == 0
    runtime.apply(Command(id="restore", operation="restore"))
    assert not runtime.session.started
    runtime.apply(Command(id="step", operation="step"))
    assert runtime.session.started
    runtime.apply(Command(id="save-step", operation="checkpoint"))
    runtime.apply(Command(id="start-again", operation="start"))
    runtime.apply(Command(id="restore-step", operation="restore"))
    assert runtime.session.started
    assert runtime.session.status == "paused"


@pytest.mark.parametrize("status", ["finished", "truncated", "failed"])
def test_terminal_race_requires_reset_before_playback(status):
    runtime = RaceServer()
    runtime.session.status = status
    with pytest.raises(ValueError, match="reset the completed race"):
        runtime.apply(Command(id="start", operation="start"))
    assert runtime.session.status == status
    runtime.apply(Command(id="new", operation="reset", settings=RaceSettings(cars=1)))
    assert not runtime.session.started
    runtime.apply(Command(id="start-new", operation="start"))
    assert runtime.session.status == "running"


@pytest.mark.asyncio
async def test_websocket_reports_paused_started_state_after_reconnect():
    runtime = RaceServer()
    runtime.session = RaceSession(RaceSettings(cars=1))
    async with serve(runtime.connect, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}") as socket:
            await socket.recv()
            assert not json.loads(await socket.recv())["started"]
            for operation in ("start", "pause"):
                await socket.send(json.dumps({"id": operation, "operation": operation}))
                messages = [json.loads(await asyncio.wait_for(socket.recv(), 5)) for _ in range(2)]
                frame = next(message for message in messages if message["type"] == "frame")
                assert frame["started"]
                assert frame["time_s"] == 0
        async with connect(f"ws://127.0.0.1:{port}") as socket:
            await socket.recv()
            frame = json.loads(await socket.recv())
            assert frame["started"]
            assert frame["status"] == "paused"


@pytest.mark.asyncio
@pytest.mark.parametrize(("compute_s", "rate", "idle_s"), [(0.12, 1, 0), (0.08, 1, 0.02), (0.08, 8, 0)])
async def test_live_pacing_uses_remaining_budget_without_slowing_late_ticks(
    monkeypatch, compute_s, rate, idle_s
):
    from afterlap_api import race_server

    runtime = RaceServer()
    runtime.session = RaceSession(RaceSettings(cars=1))
    runtime.session.status = "running"
    runtime.speed = rate
    now = 100.0
    published = []

    async def compute(function, duration):
        nonlocal now
        assert duration == 0.1
        now += compute_s
        runtime.session.simulator.world.race.session_time_s += duration

    async def sleep(delay):
        assert delay == pytest.approx(idle_s)
        assert published == [pytest.approx(0.1)]
        raise asyncio.CancelledError

    monkeypatch.setattr(race_server.time, "monotonic", lambda: now)
    monkeypatch.setattr(race_server.asyncio, "to_thread", compute)
    monkeypatch.setattr(race_server.asyncio, "sleep", sleep)
    monkeypatch.setattr(
        runtime, "publish", lambda: published.append(runtime.session.simulator.session_time_s)
    )
    with pytest.raises(asyncio.CancelledError):
        await runtime.tick()
