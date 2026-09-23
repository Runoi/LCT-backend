"""Human-readable display_number generation (ticket 09).

Known MVP simplification: the sequence number is `count(rows this year) + 1`
computed in the same transaction as the insert, not a dedicated atomic
sequence -- correct for this project's single-writer demo/test usage, not
safe under real concurrent writers. Documented, not hidden.
"""
from datetime import datetime, timezone

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.work_order import WorkOrder


async def generate_display_number(session: AsyncSession, *, now: datetime | None = None) -> str:
    """Generate the next sequential display_number for the current year.

    Args:
        session: An active async database session.
        now: Wall-clock time to derive the year from (defaults to real UTC now).

    Returns:
        "ЗН-{year}-{seq:04d}", e.g. "ЗН-2026-0042".
    """
    now = now or datetime.now(timezone.utc)
    year = now.year
    count = (
        await session.execute(
            select(func.count()).select_from(WorkOrder).where(extract("year", WorkOrder.created_at) == year)
        )
    ).scalar_one()
    return f"ЗН-{year}-{count + 1:04d}"
