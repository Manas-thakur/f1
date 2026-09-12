import asyncio
import json

import numpy as np
import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from afterlap_api.race_server import RaceServer
from afterlap_core.race.environment import encode


async def exchange(socket, operation, **payload):
    await socket.send(json.dumps({"id": operation, "operation": operation, **payload}))
    frame = None
    acknowledged = False
    while frame is None or not acknowledged:
        message = json.loads(await asyncio.wait_for(socket.recv(), 5))
        assert message["type"] != "error", message
        if message["type"] == "frame":
            frame = message
        if message["type"] == "ack":
            assert message["id"] == operation
            acknowledged = True
    return frame


@pytest.mark.asyncio
async def test_websocket_advanced_settings_replay_and_invalid_reset_are_atomic():
    runtime = RaceServer()
    async with serve(runtime.connect, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}") as socket:
            await socket.recv()
            await socket.recv()
            frame = await exchange(
                socket,
                "reset",
                settings={
                    "circuit": "monza",
                    "cars": 2,
                    "seed": 123,
                    "wetness": 0.2,
                    "variability": {
                        "preset": "training",
                        "driver_scale": 0.8,
                        "vehicle_scale": 0.7,
                        "sensor_scale": 0.3,
                        "surface_scale": 0.9,
                        "wind_scale": 0.2,
                        "wetness_target": 0.8,
                        "weather_tau_s": 60,
                        "drivers": {"car-01": {"headway_s": 1.2, "reaction_s": 0.25, "pace": 0.9}},
                    },
                },
            )
            settings = frame["settings"]
            assert settings["variability"]["wetness_target"] == 0.8
            assert settings["variability"]["weather_tau_s"] == 60
            assert settings["variability"]["drivers"]["car-01"]["headway_s"] == 1.2
            assert runtime.session.drivers["car-01"].traits.reaction_s == 0.25
            for _ in range(12):
                await exchange(socket, "step")
            checkpoint = await exchange(socket, "checkpoint")
            for _ in range(10):
                expected = await exchange(socket, "step")
            restored = await exchange(socket, "restore")
            assert restored["time_s"] == checkpoint["time_s"]
            assert restored["settings"] == settings
            assert restored["has_checkpoint"]
            assert restored["generation"] == checkpoint["generation"] + 1
            for _ in range(10):
                repeated = await exchange(socket, "step")
            assert repeated["time_s"] == expected["time_s"]
            assert repeated["cars"] == expected["cars"]
            for invalid in (
                {"surface_scale": 2},
                {"wetness_target": -0.1},
                {"weather_tau_s": 0},
                {"drivers": {"car-03": {"pace": 0.9}}},
                {"drivers": {"car-01": {"pace": 1.2}}},
                {"not_a_parameter": 1},
            ):
                await socket.send(
                    json.dumps(
                        {"id": "bad", "operation": "reset", "settings": {"cars": 2, "variability": invalid}}
                    )
                )
                error = json.loads(await asyncio.wait_for(socket.recv(), 5))
                assert error["type"] == "error"
                assert runtime.session.settings.model_dump() == settings
                assert runtime.session.simulator.session_time_s == expected["time_s"]
            async with connect(f"ws://127.0.0.1:{port}") as observer:
                await observer.recv()
                current = json.loads(await observer.recv())
                assert current["settings"] == settings
                assert current["cars"] == expected["cars"]
            actor = encode(runtime.session)
            runtime.session.weather.phases = (0, 0, 0, 0)
            runtime.session.drivers["car-02"].traits = runtime.session.drivers["car-02"].traits.model_copy(
                update={"reserve_j": 1500000, "headway_s": 2}
            )
            runtime.session.simulator.world.cars["car-02"].battery_energy_j = 1e9
            np.testing.assert_array_equal(encode(runtime.session), actor)
            assert "world" not in repeated
            assert all("driver_name" in car for car in repeated["cars"])
