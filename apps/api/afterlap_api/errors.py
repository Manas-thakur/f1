"""Typed error responses.

No exception trace ever reaches the UI. Every failure becomes an ``ApiError``
with a stable code the client can act on, and the trace goes to the structured
log with the same ``request_id`` so an operator can correlate them.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from afterlap_contracts import ApiError, ApiErrorResponse, ErrorCode

from .db import LifecycleError
from .runtime.port import RuntimeUnavailable

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

logger = logging.getLogger("afterlap.api")


class CapabilityUnavailable(Exception):
    """A required runtime capability is missing.

    Raised instead of returning a plausible-looking value. The route answers
    503 and names the capability.
    """

    def __init__(self, capability: str, detail: str) -> None:
        super().__init__(detail)
        self.capability = capability
        self.detail = detail


class ModeNotPermitted(Exception):
    """The session's mode forbids this operation, whatever the UI offered."""

    def __init__(self, mode: str, operation: str) -> None:
        super().__init__(f"{operation} is not permitted in {mode} mode")
        self.mode = mode
        self.operation = operation


def error_response(error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.http_status,
        content=ApiErrorResponse(error=error).model_dump(mode="json"),
    )


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _details(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep details JSON-safe and free of anything credential-shaped."""
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        if any(token in key.lower() for token in ("password", "token", "secret", "credential")):
            continue
        safe[key] = value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
    return safe


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers so no route needs its own try/except boilerplate."""

    @app.exception_handler(LifecycleError)
    async def _lifecycle(request: Request, exc: LifecycleError) -> JSONResponse:
        logger.info(
            "lifecycle refusal",
            extra={"request_id": request_id_of(request), "code": exc.code.value, "path": request.url.path},
        )
        return error_response(
            ApiError.of(exc.code, exc.message, request_id_of(request), **_details(exc.details))
        )

    @app.exception_handler(CapabilityUnavailable)
    async def _capability(request: Request, exc: CapabilityUnavailable) -> JSONResponse:
        return error_response(
            ApiError.of(
                ErrorCode.CAPABILITY_UNAVAILABLE,
                exc.detail,
                request_id_of(request),
                capability=exc.capability,
            )
        )

    @app.exception_handler(RuntimeUnavailable)
    async def _runtime(request: Request, exc: RuntimeUnavailable) -> JSONResponse:
        return error_response(
            ApiError.of(
                ErrorCode.CAPABILITY_UNAVAILABLE,
                exc.detail,
                request_id_of(request),
                capability="session_runtime",
                session_id=exc.session_id,
            )
        )

    @app.exception_handler(ModeNotPermitted)
    async def _mode(request: Request, exc: ModeNotPermitted) -> JSONResponse:
        return error_response(
            ApiError.of(
                ErrorCode.MODE_NOT_PERMITTED,
                str(exc),
                request_id_of(request),
                mode=exc.mode,
                operation=exc.operation,
            )
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            ApiError.of(
                ErrorCode.VALIDATION_FAILED,
                "the request body did not match the contract",
                request_id_of(request),
                fields=", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors()[:10]),
            )
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.VALIDATION_FAILED
        return error_response(ApiError.of(code, str(exc.detail), request_id_of(request)))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled error", extra={"request_id": request_id_of(request), "path": request.url.path}
        )
        return error_response(
            ApiError.of(
                ErrorCode.INTERNAL,
                "an internal error occurred; see the server log for this request id",
                request_id_of(request),
            )
        )


__all__ = [
    "CapabilityUnavailable",
    "ModeNotPermitted",
    "error_response",
    "install_error_handlers",
    "request_id_of",
]
