from __future__ import annotations

import logging
from typing import Any

from afterlap_contracts import ApiError, ApiErrorResponse, ErrorCode

from .call import Outgoing, Request
from .db import LifecycleError
from .redaction import scrub_local_paths
from .runtime.port import RuntimeUnavailable

logger = logging.getLogger("afterlap.api")


class CapabilityUnavailable(Exception):
    def __init__(self, capability: str, detail: str) -> None:
        super().__init__(detail)
        self.capability = capability
        self.detail = detail


class ModeNotPermitted(Exception):
    def __init__(self, mode: str, operation: str) -> None:
        super().__init__(f"{operation} is not permitted in {mode} mode")
        self.mode = mode
        self.operation = operation


def safe_message(text: str) -> str:
    return scrub_local_paths(text)


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _details(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        if any(token in key.lower() for token in ("password", "token", "secret", "credential")):
            continue
        resolved = value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
        safe[key] = scrub_local_paths(resolved) if isinstance(resolved, str) else resolved
    return safe


def _outgoing(error: ApiError) -> Outgoing:
    return Outgoing(error.http_status, {}, ApiErrorResponse(error=error).model_dump(mode="json"))


def exception_outgoing(request: Request, exc: BaseException) -> Outgoing:
    request_id = request_id_of(request)
    if isinstance(exc, LifecycleError):
        logger.info(
            "lifecycle refusal",
            extra={"request_id": request_id, "code": exc.code.value, "path": request.url.path},
        )
        return _outgoing(
            ApiError.of(exc.code, safe_message(exc.message), request_id, **_details(exc.details))
        )
    if isinstance(exc, CapabilityUnavailable):
        return _outgoing(
            ApiError.of(
                ErrorCode.CAPABILITY_UNAVAILABLE,
                safe_message(exc.detail),
                request_id,
                capability=exc.capability,
            )
        )
    if isinstance(exc, RuntimeUnavailable):
        return _outgoing(
            ApiError.of(
                ErrorCode.CAPABILITY_UNAVAILABLE,
                safe_message(exc.detail),
                request_id,
                capability="session_runtime",
                session_id=exc.session_id,
            )
        )
    if isinstance(exc, ModeNotPermitted):
        return _outgoing(
            ApiError.of(
                ErrorCode.MODE_NOT_PERMITTED,
                str(exc),
                request_id,
                mode=exc.mode,
                operation=exc.operation,
            )
        )
    if isinstance(exc, ValueError):
        return _outgoing(ApiError.of(ErrorCode.VALIDATION_FAILED, "a parameter was not valid", request_id))
    logger.error("unhandled error", extra={"request_id": request_id, "path": request.url.path})
    return _outgoing(
        ApiError.of(
            ErrorCode.INTERNAL,
            "an internal error occurred; see the server log for this request id",
            request_id,
        )
    )


__all__ = [
    "CapabilityUnavailable",
    "ModeNotPermitted",
    "exception_outgoing",
    "request_id_of",
    "safe_message",
]
