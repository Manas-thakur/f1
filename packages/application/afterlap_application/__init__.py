"""Application ports shared by the API and worker composition roots.

Use cases, the session runtime boundary, the registry that owns one runtime
per session, and the bounded process protocol that carries commands to a
session owner. Independent of HTTP and of any persistence adapter: the
composition roots supply those.
"""

from __future__ import annotations

from .process_runtime import (
    ANY_REVISION,
    COMMAND_KINDS,
    DEFAULT_COMMAND_TIMEOUT_S,
    DEFAULT_QUEUE_SIZE,
    ProcessSessionRuntime,
    QueuedInput,
    SessionWorkerHandle,
    WorkerBusy,
    WorkerCommand,
    WorkerConfig,
    WorkerResult,
    WorkerUnavailable,
    run_command_loop,
    worker_main,
)
from .runtime import (
    RuntimeCommand,
    RuntimeFactory,
    RuntimeHealth,
    RuntimePersistence,
    RuntimeRegistry,
    RuntimeResult,
    RuntimeTick,
    RuntimeUnavailable,
    SessionRuntimePort,
)

__all__ = [
    "ANY_REVISION",
    "COMMAND_KINDS",
    "DEFAULT_COMMAND_TIMEOUT_S",
    "DEFAULT_QUEUE_SIZE",
    "ProcessSessionRuntime",
    "QueuedInput",
    "RuntimeCommand",
    "RuntimeFactory",
    "RuntimeHealth",
    "RuntimePersistence",
    "RuntimeRegistry",
    "RuntimeResult",
    "RuntimeTick",
    "RuntimeUnavailable",
    "SessionRuntimePort",
    "SessionWorkerHandle",
    "WorkerBusy",
    "WorkerCommand",
    "WorkerConfig",
    "WorkerResult",
    "WorkerUnavailable",
    "run_command_loop",
    "worker_main",
]
