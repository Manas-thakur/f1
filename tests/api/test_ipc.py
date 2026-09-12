from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor

import pytest

from afterlap_api.ipc import MAX_MESSAGE_BYTES, encode_message, read_message


def decode(payload):
    receiver, sender = socket.socketpair()
    with receiver, sender:
        sender.sendall(len(payload).to_bytes(4, "big") + payload)
        sender.shutdown(socket.SHUT_WR)
        return read_message(receiver)


@pytest.mark.parametrize(
    "payload", [b"[]", b"null", b"1", b'"text"', b'{"x":NaN}', b'{"x":Infinity}', b"\xff", b"{"]
)
def test_invalid_wire_payloads_fail_closed(payload):
    with pytest.raises(ValueError):
        decode(payload)


@pytest.mark.parametrize("size", [0, MAX_MESSAGE_BYTES + 1, 2**32 - 1])
def test_frame_limit_is_checked_before_reading_body(size):
    receiver, sender = socket.socketpair()
    with receiver, sender:
        receiver.settimeout(0.1)
        sender.sendall(size.to_bytes(4, "big"))
        with pytest.raises(ValueError, match="length"):
            read_message(receiver)


def test_fragmented_unicode_message_round_trips():
    payload = {"label": "circuit \u03b1", "nested": [True, None, 1.25]}
    receiver, sender = socket.socketpair()
    with receiver, sender, ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(read_message, receiver)
        for byte in encode_message(payload):
            sender.sendall(bytes([byte]))
        assert pending.result(timeout=2) == payload


def test_truncated_frame_raises_connection_error():
    receiver, sender = socket.socketpair()
    with receiver, sender:
        sender.sendall((10).to_bytes(4, "big") + b"{}")
        sender.shutdown(socket.SHUT_WR)
        with pytest.raises(ConnectionError):
            read_message(receiver)


def test_outbound_non_finite_and_oversized_messages_are_refused():
    for payload in [{"x": float("inf")}, {"x": "x" * MAX_MESSAGE_BYTES}]:
        with pytest.raises(ValueError):
            encode_message(payload)
