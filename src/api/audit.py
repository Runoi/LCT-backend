"""GET /api/v1/audit -- read-only view of the user-action journal.

Deliberately exposes no write, update or delete route: the journal is
append-only and fed exclusively by the audit middleware.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from src.db import async_session_factory
from src.deps.auth import require_permission
from src.errors import ApiError
from src.models.auth import User
from src.schemas.audit import AuditEntryOut, AuditListEnvelope, AuditListMeta
from src.services.audit_query import AuditFilter, list_audit_entries

router = APIRouter(prefix="/api/v1", tags=["audit"])


def _parse_iso_datetime(raw: str, field_name: str) -> datetime:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(400, "VALIDATION_ERROR", f"{field_name} must be an ISO 8601 datetime") from exc


def _parse_cursor(raw: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ApiError(400, "VALIDATION_ERROR", "cursor is not valid") from exc


@router.get("/audit", response_model=AuditListEnvelope)
async def get_audit_journal(
    user_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_permission("audit.read")),
) -> AuditListEnvelope:
    """List journaled user actions, newest first.

    Args:
        user_id: Optional exact actor filter.
        action: Optional exact action filter, e.g. "POST /api/v1/work-orders".
        from_: Optional ISO 8601 inclusive lower bound on occurred_at.
        to: Optional ISO 8601 inclusive upper bound on occurred_at.
        cursor: Opaque pagination cursor from the previous page's meta.
        limit: Page size, 1-200.
        _: The caller; must hold audit.read.

    Returns:
        An AuditListEnvelope with one page of entries.
    """
    criteria = AuditFilter(
        user_id=user_id,
        action=action,
        occurred_from=_parse_iso_datetime(from_, "from") if from_ else None,
        occurred_to=_parse_iso_datetime(to, "to") if to else None,
    )
    after_id = _parse_cursor(cursor) if cursor else None

    async with async_session_factory() as session:
        items, next_cursor, total = await list_audit_entries(session, criteria, after_id=after_id, limit=limit)

    return AuditListEnvelope(
        data=[AuditEntryOut.model_validate(item) for item in items],
        meta=AuditListMeta(next_cursor=next_cursor, total=total, generated_at=datetime.now(timezone.utc)),
    )
