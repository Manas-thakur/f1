"""Typed API errors.

An exception trace never reaches the UI. Every error carries a stable ``code``
so the client can decide whether to refresh evidence, resync or stop.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from .base import Contract


class ErrorCode(StrEnum):
    STALE_REVISION = "stale_revision"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    RECOMMENDATION_EXPIRED = "recommendation_expired"
    RECOMMENDATION_INVALIDATED = "recommendation_invalidated"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    LEASE_NOT_HELD = "lease_not_held"
    MODE_NOT_PERMITTED = "mode_not_permitted"
    NOT_FOUND = "not_found"
    VALIDATION_FAILED = "validation_failed"
    PERSISTENCE_DEGRADED = "persistence_degraded"
    SPOOL_EXHAUSTED = "spool_exhausted"
    INTERNAL = "internal"


HTTP_STATUS_FOR_CODE: dict[ErrorCode, int] = {
    ErrorCode.STALE_REVISION: 409,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.RECOMMENDATION_EXPIRED: 422,
    ErrorCode.RECOMMENDATION_INVALIDATED: 422,
    ErrorCode.CAPABILITY_UNAVAILABLE: 503,
    ErrorCode.LEASE_NOT_HELD: 409,
    ErrorCode.MODE_NOT_PERMITTED: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.PERSISTENCE_DEGRADED: 503,
    ErrorCode.SPOOL_EXHAUSTED: 503,
    ErrorCode.INTERNAL: 500,
}

RETRYABLE_CODES: frozenset[ErrorCode] = frozenset(
    {ErrorCode.CAPABILITY_UNAVAILABLE, ErrorCode.PERSISTENCE_DEGRADED, ErrorCode.INTERNAL}
)


class ApiError(Contract):
    """Typed error body returned by every failing route."""

    code: ErrorCode
    message: str = Field(min_length=1)
    retryable: bool
    request_id: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def of(
        cls,
        code: ErrorCode,
        message: str,
        request_id: str,
        **details: Any,
    ) -> ApiError:
        return cls(
            code=code,
            message=message,
            retryable=code in RETRYABLE_CODES,
            request_id=request_id,
            details=details,
        )

    @property
    def http_status(self) -> int:
        return HTTP_STATUS_FOR_CODE[self.code]


class ApiErrorResponse(Contract):
    """Envelope so the client can discriminate errors from successful bodies."""

    error: ApiError


__all__ = [
    "HTTP_STATUS_FOR_CODE",
    "RETRYABLE_CODES",
    "ApiError",
    "ApiErrorResponse",
    "ErrorCode",
]
