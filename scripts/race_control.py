from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from typing import Any

from websockets.asyncio.client import connect
from websockets.typing import Origin


async def run(url: str, operation: str, car_id: str) -> None:
    async with connect(url, origin=Origin("http://127.0.0.1:18760")) as socket:
        latest: dict[str, Any] | None = None
        while latest is None:
            message = json.loads(await socket.recv())
            if message.get("type") == "frame":
                latest = message
        if operation == "status":
            recommendation = latest["recommendations"][car_id]
            car = next(item for item in latest["cars"] if item["id"] == car_id)
            print(
                json.dumps(
                    {
                        "status": latest["status"],
                        "time_s": latest["time_s"],
                        "car": car,
                        "recommendation": recommendation,
                    },
                    allow_nan=False,
                )
            )
            return
        command_id = str(uuid.uuid4())
        payload: dict[str, Any] = {"id": command_id, "operation": operation, "car_id": car_id}
        if operation == "boost-off":
            payload.update({"operation": "boost", "enabled": False})
        await socket.send(json.dumps(payload))
        while True:
            message = json.loads(await socket.recv())
            if message.get("id") == command_id and message.get("type") in {"ack", "error"}:
                print(json.dumps(message, allow_nan=False))
                if message["type"] == "error":
                    raise SystemExit(1)
                return


def main() -> None:
    parser = argparse.ArgumentParser(description="Control the race through the Next.js WebSocket route")
    parser.add_argument(
        "operation",
        choices=("status", "start", "pause", "step", "checkpoint", "restore", "boost", "boost-off"),
    )
    parser.add_argument("--url", default="ws://127.0.0.1:18760/race/socket")
    parser.add_argument("--car", default="car-01")
    args = parser.parse_args()
    asyncio.run(run(args.url, args.operation, args.car))


if __name__ == "__main__":
    main()
