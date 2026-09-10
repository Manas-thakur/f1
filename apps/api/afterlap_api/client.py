from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Self
from urllib.parse import urlparse

from .call import Incoming
from .plane import ControlPlane, create_app


class Headers(dict[str, str]):
    def __getitem__(self, key: str) -> str:
        return super().__getitem__(key.lower())

    def get(self, key: str, default: str | None = None) -> str | None:  # type: ignore[override]
        return super().get(key.lower(), default)

    def __setitem__(self, key: str, value: str) -> None:
        super().__setitem__(key.lower(), value)


class ClientResponse:
    def __init__(self, status: int, headers: dict[str, str], body: Any) -> None:
        self.status_code = status
        self.headers = Headers({key.lower(): value for key, value in headers.items()})
        self._body = body
        raw = b"" if body is None else json.dumps(body).encode("utf-8")
        self.content = raw
        self.text = raw.decode("utf-8") if raw else ""

    def json(self) -> Any:
        return self._body


class StreamSocket:
    def __init__(self, frames: Iterator[str]) -> None:
        self._frames = frames

    def receive_text(self) -> str:
        return next(self._frames)

    def receive_json(self) -> Any:
        return json.loads(self.receive_text())

    def send_text(self, _text: str) -> None:
        return None

    def close(self) -> None:
        return None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class TestClient:
    __test__ = False

    def __init__(self, app: ControlPlane) -> None:
        self.app = app
        self.app_instance = app

    def __enter__(self) -> Self:
        self.app.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.app.stop()

    def request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        content: bytes | None = None,
    ) -> ClientResponse:
        parsed = urlparse(url)
        path = parsed.path
        query: dict[str, str] = dict(params or {})
        if parsed.query:
            for item in parsed.query.split("&"):
                if "=" in item:
                    name, value = item.split("=", 1)
                    query[name] = value
        body = content
        if json is not None:
            body = __import__("json").dumps(json).encode("utf-8")
        incoming = Incoming(
            method=method,
            path=path,
            query=query,
            headers=headers or {},
            body=body,
        )
        outgoing = self.app.handle(incoming)
        return ClientResponse(outgoing.status, outgoing.headers, outgoing.body)

    def get(self, url: str, **kwargs: Any) -> ClientResponse:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> ClientResponse:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> ClientResponse:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> ClientResponse:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> ClientResponse:
        return self.request("DELETE", url, **kwargs)

    def websocket_connect(self, url: str) -> StreamSocket:
        parsed = urlparse(url)
        parts = [item for item in parsed.path.split("/") if item]
        session_id = parts[parts.index("sessions") + 1]
        after = 0
        if parsed.query:
            for item in parsed.query.split("&"):
                if item.startswith("after_sequence="):
                    after = int(item.split("=", 1)[1])
        return StreamSocket(self.app.iter_stream(session_id, after))


def make_client(settings: Any | None = None) -> TestClient:
    return TestClient(create_app(settings))


__all__ = ["ClientResponse", "StreamSocket", "TestClient", "make_client"]
