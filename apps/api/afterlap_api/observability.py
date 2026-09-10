"""Structured logging and operational metrics.

Logs carry session, decision and request identifiers so an operator can
correlate a refusal with the run that produced it. They never carry
credentials, and a database URL is redacted before it is written.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from afterlap_core.diagnostics import redact

if TYPE_CHECKING:
    from .plane import ControlPlane

_CONFIGURED = False

_RESERVED = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "taskName",
    "thread",
    "threadName",
}

_SENSITIVE = ("password", "token", "secret", "credential", "cookie", "authorization")


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with extras merged in and secrets stripped."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            if any(token in key.lower() for token in _SENSITIVE):
                continue
            payload[key] = _scrub(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _scrub(value: Any) -> Any:
    if isinstance(value, str) and "://" in value and "@" in value:
        return redact(value)
    return value


def configure_logging(level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    _CONFIGURED = True


@dataclass(slots=True)
class RequestMetrics:
    """Counters and latency samples the operations spec asks for.

    Planner duration is recorded separately from end-to-end observation age;
    conflating them would let a fast solver hide a stale feed.
    """

    request_count: dict[tuple[str, int], int] = field(default_factory=lambda: defaultdict(int))
    durations_ms: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    planner_durations_ms: list[float] = field(default_factory=list)
    observation_age_s: list[float] = field(default_factory=list)
    websocket_resyncs: int = 0
    spool_depth: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def observe(self, path: str, status: int, duration_ms: float) -> None:
        self.request_count[(path, status)] += 1
        samples = self.durations_ms[path]
        samples.append(duration_ms)
        if len(samples) > 2000:
            del samples[: len(samples) - 2000]

    def observe_planner(self, duration_ms: float) -> None:
        self.planner_durations_ms.append(duration_ms)
        if len(self.planner_durations_ms) > 5000:
            del self.planner_durations_ms[: len(self.planner_durations_ms) - 5000]

    def observe_observation_age(self, age_s: float) -> None:
        self.observation_age_s.append(age_s)
        if len(self.observation_age_s) > 5000:
            del self.observation_age_s[: len(self.observation_age_s) - 5000]

    def percentile(self, samples: list[float], fraction: float) -> float | None:
        if not samples:
            return None
        ordered = sorted(samples)
        index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
        return ordered[index]

    def snapshot(self) -> dict[str, Any]:
        return {
            "uptime_s": time.monotonic() - self.started_at,
            "requests": {f"{path} {status}": count for (path, status), count in self.request_count.items()},
            "planner_duration_ms": {
                "p50": self.percentile(self.planner_durations_ms, 0.50),
                "p95": self.percentile(self.planner_durations_ms, 0.95),
                "p99": self.percentile(self.planner_durations_ms, 0.99),
                "samples": len(self.planner_durations_ms),
            },
            "observation_age_s": {
                "p50": self.percentile(self.observation_age_s, 0.50),
                "p95": self.percentile(self.observation_age_s, 0.95),
                "samples": len(self.observation_age_s),
            },
            "websocket_resyncs": self.websocket_resyncs,
            "spool_depth": self.spool_depth,
        }


def metrics_payload(plane: ControlPlane) -> tuple[int, dict[str, Any]]:
    metrics: RequestMetrics | None = getattr(plane.state, "metrics", None)
    if metrics is None:
        return 503, {"detail": "metrics are not initialised"}
    hub = getattr(plane.state, "hub", None)
    resyncs = getattr(hub, "resync_count", None)
    if resyncs is not None:
        metrics.websocket_resyncs = int(resyncs)
    return 200, metrics.snapshot()


__all__ = ["JsonFormatter", "RequestMetrics", "configure_logging", "metrics_payload"]
