from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response
from websockets.typing import Origin

from afterlap_api.control_state import ControlState
from afterlap_contracts import DeploymentProfile
from afterlap_core.race import RaceConditionPatch, RaceSession, RaceSettings
from afterlap_core.race.circuit import catalogue
from afterlap_core.race.control import DriverControl
from afterlap_core.race.decision import BoostDecisionEngine
from afterlap_core.race.training import load_training_metrics


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    id: str = Field(max_length=100)
    operation: Literal[
        "reset", "configure", "start", "pause", "step", "checkpoint", "restore", "speed", "control", "boost"
    ]
    settings: RaceSettings | None = None
    conditions: RaceConditionPatch | None = None
    speed: float = Field(default=1, ge=0.1, le=8)
    car_id: str = Field(default="car-01", pattern=r"^car-[0-9]{2}$")
    action: DriverControl | None = None
    enabled: bool = True


class RaceServer:
    def __init__(
        self,
        settings: RaceSettings | None = None,
        policy_path: Path | None = None,
        metrics_path: Path | None = None,
        control_state_path: Path | None = None,
    ) -> None:
        self.session = RaceSession(settings)
        self.control_state = ControlState(control_state_path)
        self.repair_selection()
        self.decision_engine = BoostDecisionEngine(policy_path)
        self.training_metrics = load_training_metrics(metrics_path)
        self.checkpoint: dict[str, Any] | None = None
        self.speed = 1.0
        self.actual_rate = 0.0
        self.generation = 0
        self.lock = asyncio.Lock()
        self.clients: set[asyncio.Queue[str]] = set()

    def frame(self) -> str:
        payload = self.session.frame()
        observations = self.session.observations()
        recommendations = {
            car_id: self.decision_engine.recommend(self.session, observation).payload()
            for car_id, observation in observations.items()
        }
        return json.dumps(
            {
                **payload,
                "generation": self.generation,
                "circuit_map": self.session.map,
                "requested_rate": self.speed,
                "actual_rate": self.actual_rate,
                "has_checkpoint": self.checkpoint is not None,
                "selected_car_id": self.control_state.selected(),
                "recommendations": recommendations,
                "training_metrics": self.training_metrics,
            },
            allow_nan=False,
        )

    def publish(self) -> None:
        payload = self.frame()
        for queue in self.clients:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(payload)

    def repair_selection(self) -> None:
        if self.control_state.selected() not in self.session.bundle.car_configs:
            self.control_state.select(next(iter(self.session.bundle.car_configs)))

    def select(self, car_id: str) -> None:
        if car_id not in self.session.bundle.car_configs:
            raise ValueError("unknown car")
        self.control_state.select(car_id)

    def apply(self, command: Command) -> None:
        session = self.session
        if command.operation == "reset":
            self.session = RaceSession(command.settings or RaceSettings())
            self.repair_selection()
            self.checkpoint = None
            self.generation += 1
        elif command.operation == "configure":
            if command.conditions is None:
                raise ValueError("live conditions are required")
            session.configure_conditions(command.conditions)
        elif command.operation == "pause":
            if not session.done:
                session.status = "paused"
        elif command.operation == "start":
            if session.done:
                raise ValueError("reset the completed race before starting")
            session.status = "running"
        elif command.operation == "step":
            if session.status != "paused":
                raise ValueError("single-step requires a paused race")
            session.advance(session.settings.dt_s)
        elif command.operation == "checkpoint":
            self.checkpoint = session.snapshot()
        elif command.operation == "restore":
            if self.checkpoint is None:
                raise ValueError("no saved checkpoint")
            session.restore(self.checkpoint)
            if not session.done:
                session.status = "paused"
            self.generation += 1
        elif command.operation == "speed":
            self.speed = command.speed
        elif command.operation == "control":
            action = None if command.action is None else command.action.driver_action()
            session.control(command.car_id, action)
        elif command.operation == "boost":
            if command.car_id not in session.bundle.car_configs:
                raise ValueError("unknown car")
            if not command.enabled:
                session.bms_profiles.pop(command.car_id, None)
                return
            observation = session.observations()[command.car_id]
            recommendation = self.decision_engine.recommend(session, observation)
            if not recommendation.can_apply:
                raise ValueError(f"boost unavailable: {recommendation.reason}")
            session.bms_profiles.clear()
            session.bms_profiles[command.car_id] = DeploymentProfile(recommendation.mode)

    @staticmethod
    def json_response(connection: ServerConnection, status: HTTPStatus, payload: dict[str, str]) -> Response:
        response = connection.respond(status, json.dumps(payload))
        del response.headers["Content-Type"]
        response.headers["Content-Type"] = "application/json"
        return response

    async def process_request(self, connection: ServerConnection, request: Request) -> Response | None:
        path = urlsplit(request.path).path
        if path == "/" and request.method == "GET":
            return None
        selection = re.fullmatch(r"/selection/(car-[0-9]{2})", path)
        if path != "/boost" and selection is None:
            return self.json_response(connection, HTTPStatus.NOT_FOUND, {"error": "not found"})
        if request.method != "POST":
            response = self.json_response(
                connection, HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method not allowed"}
            )
            response.headers["Allow"] = "POST"
            return response
        try:
            async with self.lock:
                if selection is not None:
                    car_id = selection.group(1)
                    self.select(car_id)
                    operation = "selection"
                else:
                    car_id = self.control_state.selected()
                    self.apply(Command(id="http-boost", operation="boost", car_id=car_id))
                    operation = "boost"
                self.publish()
        except ValueError as exc:
            status = HTTPStatus.CONFLICT if str(exc).startswith("boost unavailable") else HTTPStatus.NOT_FOUND
            return self.json_response(connection, status, {"error": str(exc)})
        return self.json_response(
            connection,
            HTTPStatus.OK,
            {"operation": operation, "car_id": car_id, "status": "accepted"},
        )

    async def tick(self) -> None:
        while True:
            start = time.monotonic()
            async with self.lock:
                if self.session.status == "running":
                    before = self.session.simulator.session_time_s
                    try:
                        await asyncio.to_thread(self.session.advance, 0.1)
                    except Exception as exc:
                        self.session.status = "failed"
                        self.session.failure = f"runtime error: {type(exc).__name__}: {exc}"
                    elapsed = self.session.simulator.session_time_s - before
                    self.actual_rate = elapsed / max(time.monotonic() - start, 1e-6)
                    self.publish()
            await asyncio.sleep(max(0.005, 0.1 / self.speed - (time.monotonic() - start)))

    async def connect(self, websocket: ServerConnection) -> None:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        async with self.lock:
            await websocket.send(
                json.dumps(
                    {
                        "type": "catalogue",
                        "circuits": catalogue(),
                        "map": self.session.map,
                    }
                )
            )
            await websocket.send(self.frame())
            self.clients.add(queue)

        async def stream() -> None:
            while True:
                await websocket.send(await queue.get())

        sender = asyncio.create_task(stream())
        try:
            async for raw in websocket:
                command_id = None
                try:
                    command = Command.model_validate_json(raw)
                    command_id = command.id
                    async with self.lock:
                        await asyncio.to_thread(self.apply, command)
                        if command.operation == "reset":
                            payload = json.dumps({"type": "map", "map": self.session.map})
                            await websocket.send(payload)
                        self.publish()
                    await websocket.send(json.dumps({"type": "ack", "id": command.id}))
                except (ValueError, KeyError) as exc:
                    await websocket.send(json.dumps({"type": "error", "id": command_id, "message": str(exc)}))
        except ConnectionClosed:
            pass
        finally:
            self.clients.discard(queue)
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError, ConnectionClosed):
                await sender


def allowed_origins(origin: str) -> list[Origin | re.Pattern[str] | None]:
    return [
        Origin(origin),
        re.compile(r"https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?"),
        re.compile(
            r"https?://(?:10(?:\.[0-9]{1,3}){3}"
            r"|192\.168(?:\.[0-9]{1,3}){2}"
            r"|172\.(?:1[6-9]|2[0-9]|3[0-1])(?:\.[0-9]{1,3}){2})(?::[0-9]{1,5})?"
        ),
        None,
    ]


async def run_server(
    host: str,
    port: int,
    origin: str,
    settings: RaceSettings | None = None,
    policy_path: Path | None = None,
    metrics_path: Path | None = None,
    control_state_path: Path | None = None,
) -> None:
    runtime = RaceServer(settings, policy_path, metrics_path, control_state_path)
    ticker = asyncio.create_task(runtime.tick())
    try:
        async with serve(
            runtime.connect,
            host,
            port,
            origins=allowed_origins(origin),
            process_request=runtime.process_request,
            max_size=16384,
            max_queue=16,
        ):
            await asyncio.Future()
    finally:
        ticker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ticker
        runtime.control_state.close()
