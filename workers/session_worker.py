"""Compatibility composition root for the shared session process runtime."""

from __future__ import annotations

from afterlap_application.process_runtime import (
    ANY_REVISION,
    COMMAND_KINDS,
    DEFAULT_COMMAND_TIMEOUT_S,
    DEFAULT_QUEUE_SIZE,
    ProcessSessionRuntime,
    SessionWorkerHandle,
    WorkerBusy,
    WorkerCommand,
    WorkerConfig,
    WorkerResult,
    WorkerUnavailable,
    run_command_loop,
    worker_main,
)

__all__ = [
    "ANY_REVISION",
    "COMMAND_KINDS",
    "DEFAULT_COMMAND_TIMEOUT_S",
    "DEFAULT_QUEUE_SIZE",
    "ProcessSessionRuntime",
    "SessionWorkerHandle",
    "WorkerBusy",
    "WorkerCommand",
    "WorkerConfig",
    "WorkerResult",
    "WorkerUnavailable",
    "run_command_loop",
    "worker_main",
]
