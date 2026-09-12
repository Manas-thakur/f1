from __future__ import annotations

import json
import socket
from typing import Any

MAX_MESSAGE_BYTES = 8 * 1024 * 1024


def encode_message(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(body) > MAX_MESSAGE_BYTES:
        raise ValueError("runtime message exceeds the 8 MiB limit")
    return len(body).to_bytes(4, "big") + body


def read_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        piece = sock.recv(size - len(chunks))
        if not piece:
            raise ConnectionError("runtime socket closed")
        chunks.extend(piece)
    return bytes(chunks)


def read_message(sock: socket.socket) -> dict[str, Any]:
    length = int.from_bytes(read_exact(sock, 4), "big")
    if not 0 < length <= MAX_MESSAGE_BYTES:
        raise ValueError("runtime message length must be between 1 byte and 8 MiB")
    payload: object = json.loads(read_exact(sock, length).decode("utf-8"), parse_constant=_reject_constant)
    if not isinstance(payload, dict):
        raise ValueError("runtime message must be a JSON object")
    return payload


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value} is forbidden")


def write_message(sock: socket.socket, payload: dict[str, Any]) -> None:
    sock.sendall(encode_message(payload))


def connect(host: str, port: int, timeout_s: float | None = 60.0) -> socket.socket:
    sock = socket.create_connection((host, port), timeout=timeout_s)
    sock.settimeout(timeout_s)
    return sock


__all__ = ["connect", "encode_message", "read_message", "write_message"]
