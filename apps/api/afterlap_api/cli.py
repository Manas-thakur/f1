from __future__ import annotations

import json
import os
import socket
import sys
import threading
import urllib.parse
from typing import Annotated, Any

import typer

from afterlap_contracts import CONTRACT_REVISION, SCHEMA_VERSION

from .call import Incoming
from .deps import Settings
from .ipc import connect, read_message, write_message
from .plane import create_app

app = typer.Typer(
    name="afterlap-api",
    help="AFTERLAP Python CLI. Next.js is the public HTTP server.",
    no_args_is_help=True,
    add_completion=False,
)

DEFAULT_RUNTIME_URL = "http://127.0.0.1:8000"


def runtime_url() -> str:
    return os.environ.get("AFTERLAP_RUNTIME_URL", DEFAULT_RUNTIME_URL).rstrip("/")


def runtime_addr(base_url: str | None = None) -> tuple[str, int]:
    parsed = urllib.parse.urlparse(base_url or runtime_url())
    host = parsed.hostname or os.environ.get("AFTERLAP_HOST", "127.0.0.1")
    port = parsed.port or int(os.environ.get("AFTERLAP_PORT", "8000"))
    return host, port


def _header_pairs(headers: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in headers:
        if ":" not in item:
            raise typer.BadParameter(f"headers must be Name: value, got {item!r}")
        name, value = item.split(":", 1)
        parsed[name.strip()] = value.strip()
    return parsed


def _query_map(items: list[str] | None) -> dict[str, str]:
    query: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise typer.BadParameter(f"query must be name=value, got {item!r}")
        name, value = item.split("=", 1)
        query[name] = value
    return query


def perform_runtime_request(
    method: str,
    path: str,
    *,
    query: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    base_url: str | None = None,
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    host, port = runtime_addr(base_url)
    try:
        sock = connect(host, port, timeout_s=timeout_s)
    except OSError as exc:
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
                    "details": {"capability": "python_runtime", "reason": str(exc)},
                }
            },
        }
    try:
        write_message(
            sock,
            {
                "kind": "request",
                "method": method.upper(),
                "path": path if path.startswith("/") else f"/{path}",
                "query": query or {},
                "headers": headers or {},
                "body": None if body is None else body.decode("utf-8"),
            },
        )
        reply = read_message(sock)
        return {
            "status": int(reply.get("status", 500)),
            "headers": {str(key).lower(): str(value) for key, value in (reply.get("headers") or {}).items()},
            "body": reply.get("body"),
        }
    except (OSError, ConnectionError, ValueError) as exc:
        return {
            "status": 503,
            "headers": {"content-type": "application/json"},
            "body": {
                "error": {
                    "code": "capability_unavailable",
                    "message": "the Python runtime closed the CLI connection",
                    "retryable": True,
                    "request_id": "cli-runtime-io",
                    "details": {"capability": "python_runtime", "reason": str(exc)},
                }
            },
        }
    finally:
        sock.close()


def perform_in_process_request(
    method: str,
    path: str,
    *,
    query: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    plane = create_app(settings)
    plane.start()
    try:
        outgoing = plane.handle(
            Incoming(
                method=method.upper(),
                path=path if path.startswith("/") else f"/{path}",
                query=query or {},
                headers=headers or {},
                body=body,
            )
        )
        return {"status": outgoing.status, "headers": outgoing.headers, "body": outgoing.body}
    finally:
        plane.stop()


def _run_runtime(host: str, port: int) -> None:
    plane = create_app()
    plane.start()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, port))
    listener.listen()
    try:
        while True:
            conn, _addr = listener.accept()
            thread = threading.Thread(target=_serve_connection, args=(conn, plane), daemon=True)
            thread.start()
    except KeyboardInterrupt:
        pass
    finally:
        listener.close()
        plane.stop()


def _serve_connection(conn: socket.socket, plane: Any) -> None:
    try:
        while True:
            message = read_message(conn)
            kind = message.get("kind")
            if kind == "request":
                raw_body = message.get("body")
                body = None if raw_body is None else str(raw_body).encode("utf-8")
                outgoing = plane.handle(
                    Incoming(
                        method=str(message.get("method", "GET")),
                        path=str(message.get("path", "/")),
                        query=dict(message.get("query") or {}),
                        headers=dict(message.get("headers") or {}),
                        body=body,
                    )
                )
                write_message(
                    conn,
                    {
                        "kind": "response",
                        "status": outgoing.status,
                        "headers": outgoing.headers,
                        "body": outgoing.body,
                    },
                )
            elif kind == "stream":
                session_id = str(message.get("session_id", ""))
                after = int(message.get("after_sequence", 0))
                for frame in plane.iter_stream(session_id, after):
                    write_message(conn, {"kind": "envelope", "data": frame})
            else:
                write_message(conn, {"kind": "error", "message": f"unknown kind {kind!r}"})
    except (OSError, ConnectionError, ValueError):
        return
    finally:
        conn.close()


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address for the CLI runtime.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port for the CLI runtime.")] = 8000,
) -> None:
    _run_runtime(host, port)


@app.command()
def runtime(
    host: Annotated[str, typer.Option(help="Bind address for the CLI runtime.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port for the CLI runtime.")] = 8000,
) -> None:
    _run_runtime(host, port)


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
        typer.Option("--in-process", help="Handle the call in this process instead of attaching to serve."),
    ] = False,
) -> None:
    payload = body.encode("utf-8") if body is not None else None
    headers = _header_pairs(header or [])
    mapped = _query_map(query)
    if in_process:
        result = perform_in_process_request(
            method, path, query=mapped or None, headers=headers or None, body=payload
        )
    else:
        result = perform_runtime_request(
            method, path, query=mapped or None, headers=headers or None, body=payload
        )
    typer.echo(json.dumps(result))
    if int(result["status"]) >= 500:
        raise typer.Exit(code=1)


@app.command()
def stream(
    session_id: Annotated[str, typer.Argument()],
    after_sequence: Annotated[int, typer.Option("--after-sequence")] = 0,
    base_url: Annotated[str | None, typer.Option("--runtime-url")] = None,
    in_process: Annotated[bool, typer.Option("--in-process")] = False,
) -> None:
    if in_process:
        plane = create_app()
        plane.start()
        try:
            for frame in plane.iter_stream(session_id, after_sequence):
                typer.echo(frame, err=False)
        finally:
            plane.stop()
        return
    host, port = runtime_addr(base_url)
    try:
        sock = connect(host, port, timeout_s=None)
        sock.settimeout(None)
        write_message(
            sock,
            {"kind": "stream", "session_id": session_id, "after_sequence": after_sequence},
        )
        while True:
            message = read_message(sock)
            if message.get("kind") == "envelope":
                typer.echo(str(message.get("data", "")), err=False)
            elif message.get("kind") == "stream_end":
                break
    except (OSError, ConnectionError) as exc:
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
    "perform_in_process_request",
    "perform_runtime_request",
    "runtime_url",
]
