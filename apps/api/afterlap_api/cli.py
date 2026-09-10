from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Annotated, Any

import typer
import uvicorn

from afterlap_contracts import CONTRACT_REVISION, SCHEMA_VERSION

from .deps import Settings
from .main import API_PREFIX, create_app

app = typer.Typer(
    name="afterlap-api",
    help="AFTERLAP control-plane CLI. Next.js is the public HTTP server; this process owns Python work.",
    no_args_is_help=True,
    add_completion=False,
)

DEFAULT_RUNTIME_URL = "http://127.0.0.1:8000"


def runtime_url() -> str:
    return os.environ.get("AFTERLAP_RUNTIME_URL", DEFAULT_RUNTIME_URL).rstrip("/")


def _decode_body(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return raw.decode("utf-8")


def _header_pairs(headers: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in headers:
        if ":" not in item:
            raise typer.BadParameter(f"headers must be Name: value, got {item!r}")
        name, value = item.split(":", 1)
        parsed[name.strip()] = value.strip()
    return parsed


def perform_http_request(
    method: str,
    path: str,
    *,
    query: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    base_url: str | None = None,
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    rooted = path if path.startswith("/") else f"/{path}"
    url = f"{(base_url or runtime_url())}{rooted}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    request_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None and not any(key.lower() == "content-type" for key in request_headers):
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, method=method.upper(), headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return {
                "status": int(response.status),
                "headers": {k.lower(): v for k, v in response.headers.items()},
                "body": _decode_body(response.read()),
            }
    except urllib.error.HTTPError as exc:
        return {
            "status": int(exc.code),
            "headers": {k.lower(): v for k, v in exc.headers.items()} if exc.headers is not None else {},
            "body": _decode_body(exc.read()),
        }
    except urllib.error.URLError as exc:
        return {
            "status": 503,
            "headers": {"content-type": "application/json"},
            "body": {
                "error": {
                    "code": "capability_unavailable",
                    "message": (
                        "the Python runtime is not reachable; start it with "
                        "`uv run python -m afterlap_api.cli serve`"
                    ),
                    "retryable": True,
                    "request_id": "cli-runtime-down",
                    "details": {"capability": "python_runtime", "reason": str(exc.reason)},
                }
            },
        }


def perform_in_process_request(
    method: str,
    path: str,
    *,
    query: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    from fastapi.testclient import TestClient

    application = create_app(settings)
    with TestClient(application) as client:
        response = client.request(
            method.upper(),
            path if path.startswith("/") else f"/{path}",
            params=query,
            headers=headers,
            content=body,
        )
        payload: Any
        if not response.content:
            payload = None
        else:
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
        return {
            "status": int(response.status_code),
            "headers": {k.lower(): v for k, v in response.headers.items()},
            "body": payload,
        }


@app.command()
def serve(
    host: Annotated[
        str,
        typer.Option(help="Bind address. Public HTTP is Next.js, not this socket."),
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port for the internal Python runtime.")] = 8000,
) -> None:
    uvicorn.run(
        "afterlap_api.main:app",
        host=host,
        port=port,
        factory=False,
        log_level="info",
    )


@app.command("request")
def request_command(
    method: Annotated[str, typer.Argument(help="HTTP method as used by the control-plane contract.")],
    path: Annotated[str, typer.Argument(help="Path beginning with /api/v1 or /metrics.")],
    body: Annotated[str | None, typer.Option("--body", help="JSON request body.")] = None,
    header: Annotated[
        list[str] | None,
        typer.Option("--header", help="Request header as Name: value. Repeatable."),
    ] = None,
    query: Annotated[
        list[str] | None,
        typer.Option("--query", help="Query parameter as name=value. Repeatable."),
    ] = None,
    in_process: Annotated[
        bool,
        typer.Option("--in-process", help="Use an in-process app instead of AFTERLAP_RUNTIME_URL."),
    ] = False,
) -> None:
    query_map: dict[str, str] = {}
    for item in query or []:
        if "=" not in item:
            raise typer.BadParameter(f"query must be name=value, got {item!r}")
        name, value = item.split("=", 1)
        query_map[name] = value
    payload = body.encode("utf-8") if body is not None else None
    headers = _header_pairs(header or [])
    if in_process:
        result = perform_in_process_request(
            method, path, query=query_map or None, headers=headers or None, body=payload
        )
    else:
        result = perform_http_request(
            method, path, query=query_map or None, headers=headers or None, body=payload
        )
    typer.echo(json.dumps(result))
    if int(result["status"]) >= 500:
        raise typer.Exit(code=1)


@app.command()
def stream(
    session_id: Annotated[str, typer.Argument()],
    after_sequence: Annotated[int, typer.Option("--after-sequence")] = 0,
    base_url: Annotated[str | None, typer.Option("--runtime-url")] = None,
) -> None:
    origin = (base_url or runtime_url()).rstrip("/")
    parsed = urllib.parse.urlparse(origin)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    netloc = parsed.netloc
    ws_url = (
        f"{scheme}://{netloc}{API_PREFIX}/sessions/{urllib.parse.quote(session_id)}"
        f"/stream?after_sequence={after_sequence}"
    )
    try:
        from websockets.sync.client import connect
    except ImportError as exc:
        typer.echo(
            json.dumps(
                {
                    "error": {
                        "code": "capability_unavailable",
                        "message": "the websockets package is not installed",
                        "retryable": True,
                        "request_id": "cli-stream",
                        "details": {"capability": "stream", "reason": str(exc)},
                    }
                }
            ),
            err=True,
        )
        raise typer.Exit(code=1) from exc

    try:
        with connect(ws_url) as socket:
            for message in socket:
                text = message if isinstance(message, str) else message.decode("utf-8")
                typer.echo(text, err=False)
    except Exception as exc:
        typer.echo(
            json.dumps(
                {
                    "error": {
                        "code": "capability_unavailable",
                        "message": "the session stream could not be opened",
                        "retryable": True,
                        "request_id": "cli-stream",
                        "details": {"capability": "session_stream", "reason": str(exc)},
                    }
                }
            ),
            err=True,
        )
        raise typer.Exit(code=1) from None


@app.command()
def version() -> None:
    typer.echo(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "contract_revision": CONTRACT_REVISION,
                "python": sys.version.split()[0],
                "runtime_url": runtime_url(),
            },
            indent=2,
        )
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()


__all__ = [
    "DEFAULT_RUNTIME_URL",
    "app",
    "main",
    "perform_http_request",
    "perform_in_process_request",
    "runtime_url",
]
