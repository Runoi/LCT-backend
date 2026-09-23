"""Synthetic historical work-order backlog generator (ticket 06).

Represents the (per QA_ORGANIZERS_CLARIFICATIONS.md section 5, real and
permanently external) help-desk system as a background data source only:
volume is derived from real per-facility alarm counts (ticket 05), never
uniform noise. Distinct from ticket 09's future live `WorkOrder` lifecycle
table -- this backlog is never exposed through `/api/v1/work-orders`.
"""
from datetime import datetime, timedelta, timezone
from random import Random

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.emulation_providers import ExternalWorkOrderRecord, SyntheticProviderRun
from src.models.sensor import SensorChannel, SensorReading
from src.services.replay_engine import get_window_bounds

PROVIDER = "work_order_system"

_CATEGORIES = ("inspection", "repair", "replacement", "maintenance")  # WORK_TYPES ids (reference_data.py)
_STATUSES = ("completed", "cancelled")  # WORK_ORDER_STATUSES ids, restricted to historical/terminal states
_STATUS_WEIGHTS = (0.7, 0.3)
_ALARMS_PER_ORDER = 200
_MIN_ORDERS = 20
_MAX_ORDERS = 200


async def generate_work_order_backlog(session: AsyncSession, *, seed: int = 99, now: datetime | None = None) -> int:
    """Seed a synthetic historical work-order backlog, idempotently.

    Args:
        session: An active async database session.
        seed: RNG seed for facility/category/status/timestamp selection
            within the real-alarm-derived facility weighting.
        now: Wall-clock time recorded as this run's last_run_at.

    Returns:
        The number of backlog records inserted (0 if already seeded, or if
        no historical alarm data exists yet to derive weights from).
    """
    already_run = await session.get(SyntheticProviderRun, PROVIDER)
    if already_run is not None:
        return 0

    now = now or datetime.now(timezone.utc)
    window_start, window_end = await get_window_bounds(session)
    if window_start is None:
        session.add(SyntheticProviderRun(provider=PROVIDER, last_run_at=now, row_count=0))
        await session.commit()
        return 0

    weight_rows = (
        await session.execute(
            select(SensorChannel.facility_id, func.count(SensorReading.id))
            .select_from(SensorReading)
            .join(SensorChannel, SensorChannel.channel_id == SensorReading.channel_id)
            .where(
                SensorReading.is_alarm.is_(True),
                SensorReading.origin == "historical",
                SensorChannel.facility_id.isnot(None),
            )
            .group_by(SensorChannel.facility_id)
        )
    ).all()
    total_alarms = sum(count for _, count in weight_rows)
    if total_alarms == 0:
        session.add(SyntheticProviderRun(provider=PROVIDER, last_run_at=now, row_count=0))
        await session.commit()
        return 0

    total_orders = max(_MIN_ORDERS, min(_MAX_ORDERS, total_alarms // _ALARMS_PER_ORDER))
    facilities = [f for f, _ in weight_rows]
    weights = [count for _, count in weight_rows]
    window_seconds = (window_end - window_start).total_seconds()
    rng = Random(seed)

    for i in range(total_orders):
        facility_id = rng.choices(facilities, weights=weights, k=1)[0]
        category = rng.choice(_CATEGORIES)
        status = rng.choices(_STATUSES, weights=_STATUS_WEIGHTS, k=1)[0]
        opened_at = window_start + timedelta(seconds=rng.uniform(0, window_seconds))
        session.add(
            ExternalWorkOrderRecord(
                id=f"ewo_{i}", facility_id=facility_id, category=category, opened_at=opened_at, status=status
            )
        )

    session.add(SyntheticProviderRun(provider=PROVIDER, last_run_at=now, row_count=total_orders))
    await session.commit()
    return total_orders
