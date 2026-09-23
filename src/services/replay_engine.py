"""Near-real-time SMVU replay engine (ticket 06, ADR 0005).

Not a second ETL and not a substitute for ticket 05's historical ingest:
a separate background mechanism that replays already-ingested
`origin="historical"` readings as fresh `origin="replay"` rows over real
wall-clock time, at a controllable speed, so the deployed demo looks like
a live telemetry feed rather than a static historical dump.

`tick_once` takes an explicit `now`/`speed_multiplier` so tests can drive
it deterministically without any real `sleep`; `run_replay_loop` is the
thin wrapper that actually runs forever in the app process.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.models.replay import SINGLETON_ID, ReplayState
from src.models.sensor import SensorReading


async def get_window_bounds(session: AsyncSession) -> tuple[datetime, datetime] | tuple[None, None]:
    """Return the (min, max) occurred_at among historical readings.

    Args:
        session: An active async database session.

    Returns:
        (window_start, window_end), or (None, None) if ticket 05's ETL has
        not ingested any historical readings yet.
    """
    row = (
        await session.execute(
            select(func.min(SensorReading.occurred_at), func.max(SensorReading.occurred_at)).where(
                SensorReading.origin == "historical"
            )
        )
    ).one()
    return row[0], row[1]


async def _get_or_create_state(session: AsyncSession, window_start: datetime) -> ReplayState:
    state = (await session.execute(select(ReplayState).where(ReplayState.id == SINGLETON_ID))).scalar_one_or_none()
    if state is None:
        state = ReplayState(id=SINGLETON_ID, virtual_cursor=window_start, last_tick_at=None, tick_count=0)
        session.add(state)
    return state


async def tick_once(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    speed_multiplier: float | None = None,
    window_bounds: tuple[datetime, datetime] | None = None,
) -> int:
    """Advance the virtual clock by one tick and replay the newly-covered slice.

    Args:
        session: An active async database session.
        now: Wall-clock time to treat as "now" (defaults to real UTC now;
            tests pass an explicit value for determinism).
        speed_multiplier: Virtual seconds per wall-clock second (defaults to
            `Settings.replay_speed_multiplier`).
        window_bounds: Optional explicit (window_start, window_end) override.
            Production always computes this from real historical data; tests
            pass it explicitly so a shared test database that already has
            other origin="historical" rows (e.g. from the real ETL) cannot
            widen the window a test expects to control.

    Returns:
        The number of readings replayed this tick (0 if no historical data
        has been ingested yet).
    """
    now = now or datetime.now(timezone.utc)
    speed = speed_multiplier if speed_multiplier is not None else get_settings().replay_speed_multiplier

    if window_bounds is not None:
        window_start, window_end = window_bounds
    else:
        window_start, window_end = await get_window_bounds(session)
    if window_start is None:
        return 0

    state = await _get_or_create_state(session, window_start)
    elapsed_wall_seconds = (
        (now - state.last_tick_at).total_seconds() if state.last_tick_at is not None else get_settings().replay_tick_seconds
    )
    elapsed_wall_seconds = max(elapsed_wall_seconds, 0.0)
    virtual_delta = timedelta(seconds=elapsed_wall_seconds * speed)
    window_span = (window_end - window_start).total_seconds()

    new_cursor_raw = state.virtual_cursor + virtual_delta
    if new_cursor_raw <= window_end:
        rows = (
            await session.execute(
                select(SensorReading)
                .where(SensorReading.origin == "historical")
                .where(SensorReading.occurred_at > state.virtual_cursor)
                .where(SensorReading.occurred_at <= new_cursor_raw)
            )
        ).scalars().all()
        new_cursor = new_cursor_raw
    else:
        first_segment = (
            await session.execute(
                select(SensorReading)
                .where(SensorReading.origin == "historical")
                .where(SensorReading.occurred_at > state.virtual_cursor)
                .where(SensorReading.occurred_at <= window_end)
            )
        ).scalars().all()
        overflow_seconds = (new_cursor_raw - window_end).total_seconds()
        if window_span > 0:
            overflow_seconds = overflow_seconds % window_span
        wrapped_cursor = window_start + timedelta(seconds=overflow_seconds)
        second_segment = (
            await session.execute(
                select(SensorReading)
                .where(SensorReading.origin == "historical")
                .where(SensorReading.occurred_at >= window_start)
                .where(SensorReading.occurred_at <= wrapped_cursor)
            )
        ).scalars().all()
        rows = [*first_segment, *second_segment]
        new_cursor = wrapped_cursor

    next_tick_count = state.tick_count + 1
    for row in rows:
        session.add(
            SensorReading(
                channel_id=row.channel_id,
                occurred_at=now,
                is_alarm=row.is_alarm,
                raw_value=row.raw_value,
                numeric_value=row.numeric_value,
                is_anomaly=row.is_anomaly,
                source_event_id=f"replay_{row.id}_{next_tick_count}",
                origin="replay",
            )
        )

    state.virtual_cursor = new_cursor
    state.last_tick_at = now
    state.tick_count = next_tick_count
    await session.commit()
    return len(rows)


async def run_replay_loop(session_factory, stop_event: asyncio.Event | None = None) -> None:
    """Run `tick_once` forever on a fixed wall-clock cadence.

    Args:
        session_factory: A callable returning a new AsyncSession context
            manager (normally `src.db.async_session_factory`).
        stop_event: When set, the loop exits after its current sleep.
    """
    tick_seconds = get_settings().replay_tick_seconds
    while stop_event is None or not stop_event.is_set():
        async with session_factory() as session:
            await tick_once(session)
        await asyncio.sleep(tick_seconds)
