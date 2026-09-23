"""Incrementally materialize alarm/anomaly SensorReading rows into Event
rows (ticket 07).

Called lazily at the top of every GET /api/v1/events request (see
`event_query.py`) and once at app startup for a warm cache -- not a
background loop like ticket 06's replay engine, and deliberately
independent of it. Idempotent via `EventSyncState.last_synced_reading_id`,
the same high-water-mark pattern `event_etl.py` uses per-file.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.event import SINGLETON_ID, Event, EventSyncState
from src.models.sensor import SensorChannel, SensorReading

_BATCH_SIZE = 2000
_SOURCE = "smvu"


def _derive_state(is_alarm: bool, is_anomaly: bool) -> str:
    # is_anomaly (bad/sentinel sensor data) takes precedence over is_alarm:
    # a corrupted reading is a data-quality fault regardless of its raw
    # alarm flag. Reuses reference_data.SENSOR_STATES ids ("fault"/"alarm").
    if is_anomaly:
        return "fault"
    return "alarm"


async def sync_events(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Materialize any new alarm/anomaly readings into Event rows.

    Args:
        session: An active async database session.
        now: Wall-clock time recorded as ingested_at for newly-synced
            events (defaults to real UTC now; tests pass an explicit value).

    Returns:
        The number of Event rows newly created.
    """
    now = now or datetime.now(timezone.utc)

    state = (
        await session.execute(select(EventSyncState).where(EventSyncState.id == SINGLETON_ID))
    ).scalar_one_or_none()
    if state is None:
        state = EventSyncState(id=SINGLETON_ID, last_synced_reading_id=0)
        session.add(state)
        await session.flush()

    synced_count = 0
    while True:
        rows = (
            await session.execute(
                select(SensorReading, SensorChannel.sensor_type_id, SensorChannel.facility_id, SensorChannel.id)
                .join(SensorChannel, SensorChannel.channel_id == SensorReading.channel_id)
                .where(
                    SensorReading.id > state.last_synced_reading_id,
                    (SensorReading.is_alarm.is_(True)) | (SensorReading.is_anomaly.is_(True)),
                )
                .order_by(SensorReading.id)
                .limit(_BATCH_SIZE)
            )
        ).all()
        if not rows:
            break

        for reading, sensor_type_id, facility_id, channel_pk_id in rows:
            session.add(
                Event(
                    id=f"evt_{reading.id:012d}",
                    source_reading_id=reading.id,
                    event_type=sensor_type_id,
                    source=_SOURCE,
                    facility_id=facility_id,
                    sensor_id=channel_pk_id,
                    occurred_at=reading.occurred_at,
                    ingested_at=now,
                    state=_derive_state(reading.is_alarm, reading.is_anomaly),
                    value=reading.raw_value,
                    is_confirmed_incident=False,
                    verification_result=None,
                    resolved_at=None,
                    related_risk_id=None,
                )
            )
            synced_count += 1

        state.last_synced_reading_id = rows[-1][0].id
        await session.commit()

        if len(rows) < _BATCH_SIZE:
            break

    return synced_count
