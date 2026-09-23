"""Synthetic ОДС (dispatch desk) trigger-journal generator (ticket 06).

Volume and per-(facility, system_type) distribution are derived from real
`is_alarm=True` readings ticket 05 already ingested -- entries land more
often where real alarms already cluster, not uniformly. Only the exact
timestamp/category within that grounded distribution comes from
`random.Random(seed)`, so two runs with the same seed produce the same
entry count and the same weighted facility/system_type draws.
"""
from datetime import datetime, timedelta, timezone
from random import Random

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.emulation_providers import OdsJournalEntry, SyntheticProviderRun
from src.models.sensor import SensorChannel, SensorReading
from src.services.replay_engine import get_window_bounds

PROVIDER = "ods_journal"

_CATEGORIES = ("Плановый осмотр", "Внеплановая заявка", "Сработка датчика без привязки", "Диспетчерское уведомление")
_ALARMS_PER_ENTRY = 50  # scale factor: 1 journal entry per ~50 real alarms
_MIN_ENTRIES = 40
_MAX_ENTRIES = 400


async def generate_ods_journal(session: AsyncSession, *, seed: int = 42, now: datetime | None = None) -> int:
    """Seed synthetic ОДС journal entries, idempotently.

    Args:
        session: An active async database session.
        seed: RNG seed for timestamp/category selection within the
            real-data-derived facility/system_type weighting.
        now: Wall-clock time recorded as this run's last_run_at.

    Returns:
        The number of entries inserted (0 if already seeded, or if no
        historical alarm data exists yet to derive weights from).
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
            select(SensorChannel.facility_id, SensorChannel.system_type, func.count(SensorReading.id))
            .select_from(SensorReading)
            .join(SensorChannel, SensorChannel.channel_id == SensorReading.channel_id)
            .where(
                SensorReading.is_alarm.is_(True),
                SensorReading.origin == "historical",
                SensorChannel.facility_id.isnot(None),
            )
            .group_by(SensorChannel.facility_id, SensorChannel.system_type)
        )
    ).all()
    total_alarms = sum(count for _, _, count in weight_rows)
    if total_alarms == 0:
        session.add(SyntheticProviderRun(provider=PROVIDER, last_run_at=now, row_count=0))
        await session.commit()
        return 0

    total_entries = max(_MIN_ENTRIES, min(_MAX_ENTRIES, total_alarms // _ALARMS_PER_ENTRY))
    weights = [count for _, _, count in weight_rows]
    window_seconds = (window_end - window_start).total_seconds()
    rng = Random(seed)

    for i in range(total_entries):
        facility_id, system_type, _ = rng.choices(weight_rows, weights=weights, k=1)[0]
        category = rng.choice(_CATEGORIES)
        occurred_at = window_start + timedelta(seconds=rng.uniform(0, window_seconds))
        session.add(
            OdsJournalEntry(
                id=f"ods_{i}",
                facility_id=facility_id,
                system_type=system_type,
                category=category,
                occurred_at=occurred_at,
                description=f"{category} ({system_type})",
            )
        )

    session.add(SyntheticProviderRun(provider=PROVIDER, last_run_at=now, row_count=total_entries))
    await session.commit()
    return total_entries
