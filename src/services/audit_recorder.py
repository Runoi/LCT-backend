"""HTTP middleware that journals every mutating API request into `audit_log`.

Covering mutations generically (instead of per-endpoint calls) means a new
write endpoint is journaled without anyone remembering to add a call.
GET requests are not journaled: dashboards poll them continuously and the
journal would drown in reads.

Endpoints can enrich the entry through `request.state.audit` (a dict with
optional keys `user_id`, `username`, `target_type`, `target_id`,
`details`). Request/response bodies and headers are never stored, so
passwords and bearer tokens cannot leak into the journal.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import Request, Response
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from src.db import async_session_factory
from src.models.audit import AuditLogEntry
from src.services.auth_service import get_active_session_user

logger = logging.getLogger(__name__)

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
TRACE_HEADER = "X-Trace-Id"


def new_trace_id() -> str:
    """Generate a request trace id in the documented `tr_<hex>` format."""
    return f"tr_{uuid.uuid4().hex[:20]}"


def result_for_status(status_code: int) -> str:
    """Classify an HTTP status into the journal's result vocabulary.

    Args:
        status_code: The final response status code.

    Returns:
        "success" below 400, "denied" for 401/403/429, "failure" otherwise.
    """
    if status_code < 400:
        return "success"
    if status_code in (401, 403, 429):
        return "denied"
    return "failure"


def target_type_for_param(param_name: str) -> str:
    """Derive a target type from a path parameter name (`risk_id` -> `risk`)."""
    return param_name[: -len("_id")] if param_name.endswith("_id") else param_name


def dispatched_route(scope: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """Read the route template and path params the router resolved for a finished request.

    The router writes `route` and `path_params` into the shared ASGI scope
    while dispatching, so they are available once the response is built.

    Args:
        scope: The ASGI scope of the finished request.

    Returns:
        (route template, path params); (None, {}) if no route matched (e.g. 404).
    """
    route = scope.get("route")
    return getattr(route, "path", None), dict(scope.get("path_params") or {})


async def _resolve_actor(request: Request, enrichment: dict[str, Any]) -> tuple[str | None, str | None]:
    if enrichment.get("user_id") or enrichment.get("username"):
        return enrichment.get("user_id"), enrichment.get("username")

    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return None, None
    token = authorization.removeprefix("Bearer ").strip()
    async with async_session_factory() as session:
        user = await get_active_session_user(session, token)
    if user is None:
        return None, None
    return user.id, user.username


def build_entry(
    request: Request,
    status_code: int,
    trace_id: str,
    actor: tuple[str | None, str | None],
    enrichment: dict[str, Any],
) -> AuditLogEntry:
    """Assemble one journal row from the request, its outcome and endpoint enrichment.

    Args:
        request: The finished request.
        status_code: The final response status code.
        trace_id: The request's trace id.
        actor: (user_id, username) of the caller, either may be None.
        enrichment: The endpoint-provided `request.state.audit` dict.

    Returns:
        An unsaved AuditLogEntry.
    """
    template, path_params = dispatched_route(request.scope)
    action = f"{request.method} {template or request.url.path}"

    target_type = enrichment.get("target_type")
    target_id = enrichment.get("target_id")
    if target_type is None and path_params:
        first_name, first_value = next(iter(path_params.items()))
        target_type, target_id = target_type_for_param(first_name), str(first_value)

    return AuditLogEntry(
        occurred_at=datetime.now(timezone.utc),
        user_id=actor[0],
        username=actor[1],
        action=action,
        target_type=target_type,
        target_id=target_id,
        result=result_for_status(status_code),
        status_code=status_code,
        ip=request.client.host if request.client else None,
        trace_id=trace_id,
        details=enrichment.get("details"),
    )


async def write_audit_entry(entry: AuditLogEntry) -> None:
    """Persist one journal row in its own transaction."""
    async with async_session_factory() as session:
        session.add(entry)
        await session.commit()


class AuditMiddleware(BaseHTTPMiddleware):
    """Assign a trace id to every request and journal mutating API calls."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Run the request, stamp its trace id and journal it if it mutates state."""
        trace_id = new_trace_id()
        request.state.trace_id = trace_id
        request.state.audit = {}

        response = await call_next(request)
        response.headers[TRACE_HEADER] = trace_id

        if request.method in MUTATING_METHODS and request.url.path.startswith("/api/"):
            # Журнал не должен ломать ответ пользователю: сбой записи логируем.
            try:
                enrichment = request.state.audit
                actor = await _resolve_actor(request, enrichment)
                await write_audit_entry(build_entry(request, response.status_code, trace_id, actor, enrichment))
            except (SQLAlchemyError, OSError):
                logger.exception("audit journal write failed, trace_id=%s", trace_id)
        return response
