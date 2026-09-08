"""Dependency-free HTTP client for the runbook scripts.

Built on ``urllib`` rather than a request library so ``scripts/demo.py`` runs
inside the packaged image without adding anything to the runtime dependency
graph. It does three things the standard library does not do for you:

* it puts an ``Idempotency-Key`` on every mutating call, because every mutable
  route requires one and a retry must never be a second human decision;
* it raises :class:`ApiError` carrying the server's typed error body, so a
  refusal is legible instead of arriving as ``HTTP Error 409: Conflict``;
* it never logs a header. There is no credential in this build, and this client
  is written so that adding one later does not put it in a transcript.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

DEFAULT_TIMEOUT_S = 30.0


class ApiError(RuntimeError):
    """A non-2xx answer, with the typed error body attached."""

    def __init__(self, method: str, path: str, status: int, body: Any) -> None:
        error = body.get("error") if isinstance(body, dict) else None
        source = error if isinstance(error, dict) else (body if isinstance(body, dict) else {})
        code = source.get("code")
        message = source.get("message") or source.get("detail")
        super().__init__(f"{method} {path} -> {status}" + (f" [{code}] {message}" if message else ""))
        self.method = method
        self.path = path
        self.status = status
        self.body = body
        self.error = source
        self.code = code
        self.message = message
        self.retryable = bool(source.get("retryable", False))


@dataclass(slots=True)
class ApiClient:
    """Minimal JSON client against one AFTERLAP origin."""

    base_url: str = "http://127.0.0.1:8000"
    prefix: str = "/api/v1"
    operator_id: str = "console-operator"
    timeout_s: float = DEFAULT_TIMEOUT_S

    def url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        if path.startswith("/api") or path == "/metrics":
            return f"{self.base_url.rstrip('/')}{path}"
        return f"{self.base_url.rstrip('/')}{self.prefix}{path}"

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        timeout_s: float | None = None,
    ) -> Any:
        url = self.url(path)
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if method.upper() not in {"GET", "HEAD"}:
            headers["Idempotency-Key"] = idempotency_key or f"demo-{uuid.uuid4().hex[:16]}"
        headers["X-Operator-Id"] = self.operator_id

        request = urllib.request.Request(url, data=payload, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=timeout_s or self.timeout_s) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                parsed = json.loads(raw) if raw else {}
            except ValueError:
                parsed = {"detail": raw.decode("utf-8", "replace")}
            raise ApiError(method.upper(), path, error.code, parsed) from None

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, body: dict[str, Any], **kwargs: Any) -> Any:
        return self.request("POST", path, body=body, **kwargs)

    def wait_for_live(self, *, timeout_s: float = 60.0, interval_s: float = 0.5) -> float:
        """Block until ``/health/live`` answers. Returns the wait in seconds.

        Liveness, not readiness: the caller decides what to do about a live
        server that is not ready, and that distinction is the whole point of
        having two endpoints.
        """
        deadline = time.monotonic() + timeout_s
        started = time.monotonic()
        last: Exception | None = None
        while time.monotonic() < deadline:
            try:
                body = self.get("/health/live", timeout_s=5.0)
            except (urllib.error.URLError, ApiError, TimeoutError, OSError) as exc:
                last = exc
            else:
                if isinstance(body, dict) and body.get("status") == "live":
                    return time.monotonic() - started
            time.sleep(interval_s)
        raise TimeoutError(f"{self.base_url} never reported live within {timeout_s} s (last error: {last})")


__all__ = ["DEFAULT_TIMEOUT_S", "ApiClient", "ApiError"]
