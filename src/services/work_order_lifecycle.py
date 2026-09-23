"""Time-based status auto-advance for the local work-order lifecycle (ticket 09).

Pure function of (created_at, now) -- no mutable per-tick state, so it is
naturally idempotent and safe to call repeatedly (e.g. lazily on every
GET /work-orders, the same pattern tickets 07/08 use for events/risks).

"cancelled" and "integration_error" are deliberately NOT part of this
automatic chain: cancellation is a human decision, and integration_error
would only occur on a real external-system failure -- neither is
reachable through automatic time-based progression in this ticket.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.work_order import WorkOrder

_STATUS_ORDER: tuple[str, ...] = ("draft", "ready", "assigned", "in_progress", "completed")

_CUMULATIVE_MINUTES: dict[str, float] = {
    "draft": 0.0,
    "ready": 5.0,
    "assigned": 20.0,
    "in_progress": 50.0,
    "completed": 110.0,
}


def status_for_elapsed(created_at: datetime, now: datetime) -> str:
    """Derive the automatic lifecycle status for elapsed time since creation.

    Args:
        created_at: When the work order was created.
        now: Wall-clock time to evaluate against.

    Returns:
        The furthest status in _STATUS_ORDER reached by the elapsed time
        (never earlier than "draft", never later than "completed").
    """
    elapsed_minutes = (now - created_at).total_seconds() / 60.0
    result = _STATUS_ORDER[0]
    for status in _STATUS_ORDER:
        if elapsed_minutes >= _CUMULATIVE_MINUTES[status]:
            result = status
    return result


async def sync_work_order_statuses(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Advance every eligible WorkOrder's status to match elapsed time.

    Args:
        session: An active async database session.
        now: Wall-clock time to evaluate against (defaults to real UTC now).

    Returns:
        The number of rows whose status changed.
    """
    now = now or datetime.now(timezone.utc)

    # Only rows still in the automatic chain are eligible -- "cancelled"/
    # "integration_error" (not in _STATUS_ORDER) are excluded by this
    # filter automatically, and "completed" rows never change (loop below
    # is a no-op for them since status_for_elapsed cannot regress).
    rows = (
        await session.execute(select(WorkOrder).where(WorkOrder.status.in_(_STATUS_ORDER)))
    ).scalars().all()

    updated_count = 0
    for work_order in rows:
        new_status = status_for_elapsed(work_order.created_at, now)
        if new_status != work_order.status:
            work_order.status = new_status
            work_order.updated_at = now
            updated_count += 1

    if updated_count:
        await session.commit()
    return updated_count
