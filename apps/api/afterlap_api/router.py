from __future__ import annotations

import contextlib
import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from types import UnionType
from typing import Annotated, Any, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel, ValidationError

from afterlap_contracts import ApiError, ApiErrorResponse, ErrorCode

from .call import Incoming, Outgoing, Reply, Request
from .db import LifecycleError
from .deps import QueryBound, operator_from_headers, require_idempotency
from .errors import CapabilityUnavailable, ModeNotPermitted, exception_outgoing, request_id_of
from .runtime.port import RuntimeUnavailable

RouteHandler = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class Route:
    method: str
    path: str
    pattern: re.Pattern[str]
    names: tuple[str, ...]
    handler: RouteHandler
    status_code: int


_ROUTES: list[Route] = []
_LOADED = False


def _compile(path: str) -> tuple[re.Pattern[str], tuple[str, ...]]:
    names: list[str] = []
    parts: list[str] = []
    trimmed = path.strip("/")
    if trimmed == "":
        return re.compile("^/$"), ()
    for segment in trimmed.split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            name = segment[1:-1]
            names.append(name)
            parts.append(f"(?P<{name}>[^/]+)")
        else:
            parts.append(re.escape(segment))
    return re.compile("^/" + "/".join(parts) + "$"), tuple(names)


def _register(method: str, path: str, status_code: int) -> Callable[[RouteHandler], RouteHandler]:
    def decorate(handler: RouteHandler) -> RouteHandler:
        pattern, names = _compile(path)
        _ROUTES.append(Route(method.upper(), path, pattern, names, handler, status_code))
        return handler

    return decorate


def get(path: str, *, status_code: int = 200) -> Callable[[RouteHandler], RouteHandler]:
    return _register("GET", path, status_code)


def post(path: str, *, status_code: int = 200) -> Callable[[RouteHandler], RouteHandler]:
    return _register("POST", path, status_code)


def put(path: str, *, status_code: int = 200) -> Callable[[RouteHandler], RouteHandler]:
    return _register("PUT", path, status_code)


def patch(path: str, *, status_code: int = 200) -> Callable[[RouteHandler], RouteHandler]:
    return _register("PATCH", path, status_code)


def delete(path: str, *, status_code: int = 200) -> Callable[[RouteHandler], RouteHandler]:
    return _register("DELETE", path, status_code)


def match(method: str, path: str) -> tuple[Route, dict[str, str]] | None:
    for route in _ROUTES:
        if route.method != method.upper():
            continue
        found = route.pattern.match(path)
        if found is None:
            continue
        return route, found.groupdict()
    return None


def _annotation_parts(annotation: Any) -> tuple[Any, Any]:
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        return args[0], args[1] if len(args) > 1 else None
    return annotation, None


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        args = [item for item in get_args(annotation) if item is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _is_model(annotation: Any) -> bool:
    return inspect.isclass(annotation) and issubclass(annotation, BaseModel)


def _is_enum(annotation: Any) -> bool:
    return inspect.isclass(annotation) and issubclass(annotation, Enum)


def _coerce(annotation: Any, raw: str, bound: Any) -> Any:
    inner, optional = _unwrap_optional(annotation)
    if raw == "" and optional:
        return None
    if inner is str:
        value: Any = raw
    elif inner is int:
        value = int(raw)
    elif inner is float:
        value = float(raw)
    elif inner is bool:
        value = raw.lower() in {"1", "true", "yes"}
    elif _is_enum(inner):
        value = inner(raw)
    else:
        value = raw
    if isinstance(bound, QueryBound):
        if bound.ge is not None and value < bound.ge:
            raise LifecycleError(ErrorCode.VALIDATION_FAILED, f"value {value} is below {bound.ge}")
        if bound.le is not None and value > bound.le:
            raise LifecycleError(ErrorCode.VALIDATION_FAILED, f"value {value} is above {bound.le}")
    return value


def _dump(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [_dump(item) for item in value]
    return value


async def invoke(plane: Any, incoming: Incoming) -> Outgoing:
    request = Request(plane, incoming)
    path = request.url.path
    api_prefix = "/api/v1"
    routed = path
    if path.startswith(api_prefix):
        routed = path[len(api_prefix) :] or "/"
    if not routed.startswith("/"):
        routed = "/" + routed

    if path == "/metrics" or routed == "/metrics":
        from .observability import metrics_payload

        status, body = metrics_payload(plane)
        return _finish(request, Outgoing(status, {}, body))

    found = match(incoming.method, routed)
    if found is None:
        error = ApiError.of(ErrorCode.NOT_FOUND, "not found", request_id_of(request))
        return _finish(
            request,
            Outgoing(error.http_status, {}, ApiErrorResponse(error=error).model_dump(mode="json")),
        )

    route, params = found
    request.path_params = params
    signature = inspect.signature(route.handler)
    hints = get_type_hints(route.handler, include_extras=True)
    kwargs: dict[str, Any] = {}
    db_cm = None
    command_cm = None
    committed = False
    reply = Reply(status_code=route.status_code)
    try:
        for name, parameter in signature.parameters.items():
            annotation, marker = _annotation_parts(hints.get(name, parameter.annotation))
            if annotation is inspect.Parameter.empty:
                continue
            if annotation is Request or name == "request":
                kwargs[name] = request
                continue
            if annotation is Reply or name == "response":
                kwargs[name] = reply
                continue
            if name in params:
                kwargs[name] = params[name]
                continue
            if marker == "operator":
                kwargs[name] = operator_from_headers(plane.state.settings, request.headers)
                continue
            if marker == "idempotency":
                kwargs[name] = require_idempotency(request.headers)
                continue
            if marker == "db":
                db_cm = plane.state.database.session()
                kwargs[name] = next(db_cm)
                continue
            if marker == "command":
                command_cm = plane.state.database.command_session()
                kwargs[name] = next(command_cm)
                continue
            inner, optional = _unwrap_optional(annotation)
            if _is_model(inner):
                raw = request.body
                if not raw:
                    if optional:
                        kwargs[name] = None
                        continue
                    _reject("the request body is required")
                kwargs[name] = inner.model_validate_json(raw)
                continue
            query_value = request.query_params.get(name)
            if query_value is None:
                if parameter.default is not inspect.Parameter.empty:
                    kwargs[name] = parameter.default
                elif optional:
                    kwargs[name] = None
                else:
                    _reject(f"missing query parameter {name}")
            else:
                kwargs[name] = _coerce(annotation, query_value, marker)

        result = route.handler(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        outgoing = _finish(request, Outgoing(reply.status_code, dict(reply.headers), _dump(result)))
        committed = True
        return outgoing
    except ValidationError as exc:
        error = ApiError.of(
            ErrorCode.VALIDATION_FAILED,
            "the request body did not match the contract",
            request_id_of(request),
            fields=", ".join(".".join(str(part) for part in err["loc"]) for err in exc.errors()[:10]),
        )
        return _finish(
            request,
            Outgoing(error.http_status, {}, ApiErrorResponse(error=error).model_dump(mode="json")),
        )
    except (LifecycleError, CapabilityUnavailable, RuntimeUnavailable, ModeNotPermitted, ValueError) as exc:
        return _finish(request, exception_outgoing(request, exc))
    except Exception as exc:
        return _finish(request, exception_outgoing(request, exc))
    finally:
        _release_session(db_cm, committed)
        _release_session(command_cm, committed)


def _reject(message: str) -> None:
    raise LifecycleError(ErrorCode.VALIDATION_FAILED, message)


def _release_session(gen: Any, committed: bool) -> None:
    if gen is None:
        return
    if committed:
        with contextlib.suppress(StopIteration):
            next(gen)
        return
    with contextlib.suppress(RuntimeError, StopIteration):
        gen.throw(RuntimeError("handler failed"))
    gen.close()


def _finish(request: Request, outgoing: Outgoing) -> Outgoing:
    headers = {key.lower(): value for key, value in outgoing.headers.items()}
    headers["content-type"] = "application/json"
    headers["x-request-id"] = request.state.request_id
    started = getattr(request.state, "started", None)
    metrics = getattr(request.app.state, "metrics", None)
    if metrics is not None and started is not None:
        import time

        metrics.observe(request.url.path, outgoing.status, (time.perf_counter() - started) * 1000.0)
    return Outgoing(outgoing.status, headers, outgoing.body)


def documented_paths() -> list[str]:
    prefix = "/api/v1"
    paths: list[str] = []
    for route in _ROUTES:
        path = route.path if route.path.startswith("/") else f"/{route.path}"
        paths.append(f"{prefix}{path}")
    return paths


def load_routes() -> None:
    global _LOADED
    if _LOADED:
        return
    from .routes import catalog, experiments, exports, health, models, rulesets, sessions

    _ = (catalog, experiments, exports, health, models, rulesets, sessions)
    _LOADED = True


__all__ = [
    "Route",
    "delete",
    "documented_paths",
    "get",
    "invoke",
    "load_routes",
    "match",
    "patch",
    "post",
    "put",
]
