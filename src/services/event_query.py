"""Scope-filtered, keyset-paginated event queries (ticket 07).

Uses real SQL LIMIT/keyset pagination (Event.id DESC, cursor = last-seen
id), not the in-memory-slice pattern tickets 04/05 used for the small
facility/sensor catalogues -- the event journal grows continuously via
ticket 06's replay engine and must never be fully materialized.
"""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.event import Event


async def list_events(
    session: AsyncSession,
    allowed_facility_ids: set[str] | None,
    *,
    facility_id: str | None = None,
    sensor_id: str | None = None,
    event_type: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[Event], str | None, int]:
    """List events filtered by scope and the documented query params.

    Args:
        session: An active async database session.
        allowed_facility_ids: None for all_facilities scope, else the exact
            set of facility ids the caller may see (orphan events, with
            facility_id=None, are excluded for any restricted scope, same
            rule as orphan sensors in ticket 05).
        facility_id: Optional exact facility filter.
        sensor_id: Optional exact sensor filter.
        event_type: Optional exact event_type (sensor_type_id) filter.
        occurred_from: Optional inclusive lower bound on occurred_at.
        occurred_to: Optional inclusive upper bound on occurred_at.
        cursor: Opaque cursor -- the last-seen event id, exclusive.
        limit: Page size.

    Returns:
        (items, next_cursor, total_matching_scope_and_filters) -- newest
        first (Event.id DESC).
    """
    if allowed_facility_ids is not None and not allowed_facility_ids:
        return [], None, 0

    base_stmt = select(Event)
    if allowed_facility_ids is not None:
        base_stmt = base_stmt.where(Event.facility_id.in_(allowed_facility_ids))
    if facility_id:
        base_stmt = base_stmt.where(Event.facility_id == facility_id)
    if sensor_id:
        base_stmt = base_stmt.where(Event.sensor_id == sensor_id)
    if event_type:
        base_stmt = base_stmt.where(Event.event_type == event_type)
    if occurred_from:
        base_stmt = base_stmt.where(Event.occurred_at >= occurred_from)
    if occurred_to:
        base_stmt = base_stmt.where(Event.occurred_at <= occurred_to)

    total = (await session.execute(select(func.count()).select_from(base_stmt.subquery()))).scalar_one()

    page_stmt = base_stmt
    if cursor:
        page_stmt = page_stmt.where(Event.id < cursor)
    page_stmt = page_stmt.order_by(Event.id.desc()).limit(limit + 1)

    rows = (await session.execute(page_stmt)).scalars().all()
    items = rows[:limit]
    # next_cursor must be the last INCLUDED item's id, not the lookahead
    # row's id -- using the lookahead row's id here would make the next
    # page's "id < cursor" filter skip that row entirely (id < itself is
    # never true), silently dropping one item per page.
    next_cursor = items[-1].id if len(rows) > limit else None
    return items, next_cursor, total
