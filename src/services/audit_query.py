"""Read side of the audit journal: filtered, keyset-paginated, newest first."""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.audit import AuditLogEntry


@dataclass(frozen=True)
class AuditFilter:
    """Optional narrowing criteria for the journal; None means "no filter"."""

    user_id: str | None = None
    action: str | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None


def _apply_filter(stmt: Select, criteria: AuditFilter) -> Select:
    if criteria.user_id is not None:
        stmt = stmt.where(AuditLogEntry.user_id == criteria.user_id)
    if criteria.action is not None:
        stmt = stmt.where(AuditLogEntry.action == criteria.action)
    if criteria.occurred_from is not None:
        stmt = stmt.where(AuditLogEntry.occurred_at >= criteria.occurred_from)
    if criteria.occurred_to is not None:
        stmt = stmt.where(AuditLogEntry.occurred_at <= criteria.occurred_to)
    return stmt


async def list_audit_entries(
    session: AsyncSession,
    criteria: AuditFilter,
    *,
    after_id: int | None,
    limit: int,
) -> tuple[list[AuditLogEntry], str | None, int]:
    """Return one page of journal entries, newest first.

    Args:
        session: An active async database session.
        criteria: Filters to apply.
        after_id: Keyset cursor -- only entries with a smaller id are returned.
        limit: Page size.

    Returns:
        (entries, next_cursor, total matching the filter). next_cursor is the
        id of the last returned entry when more entries remain, else None.
    """
    total = (
        await session.execute(_apply_filter(select(func.count()).select_from(AuditLogEntry), criteria))
    ).scalar_one()

    page_stmt = _apply_filter(select(AuditLogEntry), criteria)
    if after_id is not None:
        page_stmt = page_stmt.where(AuditLogEntry.id < after_id)
    rows = (
        await session.execute(page_stmt.order_by(AuditLogEntry.id.desc()).limit(limit + 1))
    ).scalars().all()

    items = list(rows[:limit])
    next_cursor = str(items[-1].id) if len(rows) > limit else None
    return items, next_cursor, total
