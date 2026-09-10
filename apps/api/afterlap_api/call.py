from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs


class Headers:
    def __init__(self, raw: dict[str, str] | None = None) -> None:
        self._raw = {key.lower(): value for key, value in (raw or {}).items()}

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._raw.get(key.lower(), default)

    def __getitem__(self, key: str) -> str:
        return self._raw[key.lower()]

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key.lower() in self._raw

    def items(self) -> Any:
        return self._raw.items()


class QueryParams:
    def __init__(self, raw: dict[str, str] | None = None) -> None:
        self._raw = dict(raw or {})

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._raw.get(key, default)

    def __getitem__(self, key: str) -> str:
        return self._raw[key]


@dataclass(slots=True)
class Incoming:
    method: str
    path: str
    query: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = None


@dataclass(slots=True)
class Outgoing:
    status: int
    headers: dict[str, str]
    body: Any


@dataclass(slots=True)
class Reply:
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)


class Url:
    def __init__(self, path: str) -> None:
        self.path = path


class Request:
    def __init__(self, app: Any, incoming: Incoming) -> None:
        self.app = app
        self.method = incoming.method.upper()
        path, _, query_string = incoming.path.partition("?")
        self.url = Url(path)
        merged = dict(incoming.query)
        if query_string:
            for key, values in parse_qs(query_string, keep_blank_values=True).items():
                if values:
                    merged[key] = values[-1]
        self.query_params = QueryParams(merged)
        self.headers = Headers(incoming.headers)
        self._body = incoming.body
        request_id = self.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:12]}"
        self.state = SimpleNamespace(request_id=request_id, started=time.perf_counter())
        self.path_params: dict[str, str] = {}

    @property
    def body(self) -> bytes:
        return self._body or b""


Response = Reply

__all__ = [
    "Headers",
    "Incoming",
    "Outgoing",
    "QueryParams",
    "Reply",
    "Request",
    "Response",
    "Url",
]
