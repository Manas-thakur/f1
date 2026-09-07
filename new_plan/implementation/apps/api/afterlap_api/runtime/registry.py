"""Registry of live session runtimes, one per active session."""

from __future__ import annotations

from collections.abc import Callable

from .port import RuntimeUnavailable, SessionRuntimePort

RuntimeFactory = Callable[[str], SessionRuntimePort]


class RuntimeRegistry:
    """Owns the runtime attached to each active session.

    A session with no attached runtime is reported unavailable rather than
    served from a stale cache: the API must not answer with a state nobody is
    currently computing.
    """

    def __init__(self, factory: RuntimeFactory | None = None) -> None:
        self._runtimes: dict[str, SessionRuntimePort] = {}
        self._factory = factory

    def attach(self, session_id: str, runtime: SessionRuntimePort) -> None:
        self._runtimes[session_id] = runtime

    def get(self, session_id: str) -> SessionRuntimePort:
        runtime = self._runtimes.get(session_id)
        if runtime is not None:
            return runtime
        if self._factory is None:
            raise RuntimeUnavailable(
                session_id,
                "no session runtime is attached; start the session before requesting live state",
            )
        runtime = self._factory(session_id)
        self._runtimes[session_id] = runtime
        return runtime

    def has(self, session_id: str) -> bool:
        return session_id in self._runtimes

    def detach(self, session_id: str) -> None:
        runtime = self._runtimes.pop(session_id, None)
        if runtime is not None:
            runtime.stop()

    def stop_all(self) -> None:
        for session_id in list(self._runtimes):
            self.detach(session_id)

    @property
    def active_sessions(self) -> tuple[str, ...]:
        return tuple(sorted(self._runtimes))
