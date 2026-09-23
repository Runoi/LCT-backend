"""Tests for the SMVU replay engine (leaf 1.1.1).

tick_once's historical-readings query is intentionally unscoped by
channel (it must replay across every channel in the real deployment), so
each test uses its own dedicated, non-overlapping calendar window --
never August 2026 (the real operational window) and never overlapping
another test's window -- to stay correct regardless of what real or
other-test historical data already shares this database.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.db import async_session_factory
from src.models.replay import SINGLETON_ID, ReplayState
from src.models.sensor import SensorReading
from src.services.replay_engine import get_window_bounds, tick_once


async def _reset_singleton_state(window_start: datetime, last_tick_at: datetime) -> None:
    # Pre-seed with an explicit last_tick_at so the tick uses the normal
    # "elapsed = now - last_tick_at" path (speed_multiplier=1.0 then maps
    # 1:1 to wall-clock minutes) instead of the first-tick-ever fallback
    # (settings.replay_tick_seconds -- a different, test-irrelevant basis).
    async with async_session_factory() as session:
        state = (await session.execute(select(ReplayState).where(ReplayState.id == SINGLETON_ID))).scalar_one_or_none()
        if state is not None:
            await session.delete(state)
            await session.commit()
        session.add(ReplayState(id=SINGLETON_ID, virtual_cursor=window_start, last_tick_at=last_tick_at, tick_count=0))
        await session.commit()


async def _seed_historical(channel_id: str, window_start: datetime, offsets_minutes: list[int]) -> None:
    async with async_session_factory() as session:
        for i, minutes in enumerate(offsets_minutes):
            session.add(
                SensorReading(
                    channel_id=channel_id,
                    occurred_at=window_start + timedelta(minutes=minutes),
                    is_alarm=False,
                    raw_value=str(20.0 + i),
                    numeric_value=20.0 + i,
                    is_anomaly=False,
                    source_event_id=f"hist_{channel_id}_{i}",
                    origin="historical",
                )
            )
        await session.commit()


@pytest.mark.asyncio
async def test_get_window_bounds_ignores_replay_and_fixture_origin() -> None:
    # A window far enough in the future (year 2090) that no other test or
    # real data could plausibly land inside or beyond it.
    window_start = datetime(2090, 1, 1, tzinfo=timezone.utc)
    await _seed_historical("replay_test_channel_bounds", window_start, [0, 30])
    async with async_session_factory() as session:
        session.add(
            SensorReading(
                channel_id="replay_test_channel_bounds",
                occurred_at=window_start + timedelta(days=5),
                is_alarm=False,
                raw_value="99",
                numeric_value=99.0,
                is_anomaly=False,
                source_event_id="not_historical",
                origin="replay",
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        window_start_result, window_end_result = await get_window_bounds(session)
    assert window_end_result >= window_start + timedelta(minutes=30)
    assert window_end_result < window_start + timedelta(days=5)


@pytest.mark.asyncio
async def test_first_tick_replays_readings_in_the_covered_slice() -> None:
    window_start = datetime(2031, 2, 1, tzinfo=timezone.utc)
    window_end = window_start + timedelta(hours=1)
    await _reset_singleton_state(window_start, last_tick_at=window_start)
    await _seed_historical("replay_test_channel_first", window_start, [0, 10, 40])

    tick_at = window_start + timedelta(minutes=20)
    async with async_session_factory() as session:
        replayed = await tick_once(session, now=tick_at, speed_multiplier=1.0, window_bounds=(window_start, window_end))
    # virtual_cursor starts at window_start; readings at +0min are NOT
    # included (open lower bound), +10min is, +40min is not yet.
    assert replayed == 1

    async with async_session_factory() as session:
        replayed_rows = (
            await session.execute(
                select(SensorReading).where(
                    SensorReading.channel_id == "replay_test_channel_first", SensorReading.origin == "replay"
                )
            )
        ).scalars().all()
    assert len(replayed_rows) == 1
    assert replayed_rows[0].occurred_at == tick_at
    assert replayed_rows[0].numeric_value == 21.0  # the +10min reading


@pytest.mark.asyncio
async def test_second_tick_advances_from_the_persisted_cursor() -> None:
    window_start = datetime(2031, 3, 1, tzinfo=timezone.utc)
    window_end = window_start + timedelta(hours=1)
    await _reset_singleton_state(window_start, last_tick_at=window_start)
    await _seed_historical("replay_test_channel_second", window_start, [5, 15, 45])

    async with async_session_factory() as session:
        await tick_once(
            session, now=window_start + timedelta(minutes=20), speed_multiplier=1.0, window_bounds=(window_start, window_end)
        )
    async with async_session_factory() as session:
        second_count = await tick_once(
            session, now=window_start + timedelta(minutes=50), speed_multiplier=1.0, window_bounds=(window_start, window_end)
        )
    # first tick covers (0,20] -> readings at 5,15 (2); second tick covers
    # (20,50] -> reading at 45 (1).
    assert second_count == 1

    async with async_session_factory() as session:
        state = (await session.execute(select(ReplayState).where(ReplayState.id == SINGLETON_ID))).scalar_one()
    assert state.tick_count == 2
    assert state.virtual_cursor == window_start + timedelta(minutes=50)


@pytest.mark.asyncio
async def test_tick_wraps_to_window_start_past_the_window_end() -> None:
    window_start = datetime(2031, 4, 1, tzinfo=timezone.utc)
    window_end = window_start + timedelta(hours=1)
    await _reset_singleton_state(window_start, last_tick_at=window_start)
    await _seed_historical("replay_test_channel_wrap", window_start, [5, 55])  # near start, near end of the 60-min window

    async with async_session_factory() as session:
        # jump the virtual clock 70 minutes in one tick from window_start:
        # covers (0,60] then wraps to [0,10] of the next lap.
        replayed = await tick_once(
            session, now=window_start + timedelta(minutes=70), speed_multiplier=1.0, window_bounds=(window_start, window_end)
        )
    # first segment picks up the +5 and +55 readings; wrapped segment
    # [window_start, +10min] picks up the +5 reading again (post-wrap).
    assert replayed == 3

    async with async_session_factory() as session:
        state = (await session.execute(select(ReplayState).where(ReplayState.id == SINGLETON_ID))).scalar_one()
    assert state.virtual_cursor == window_start + timedelta(minutes=10)


@pytest.mark.asyncio
async def test_tick_with_no_historical_data_is_a_noop() -> None:
    async with async_session_factory() as session:
        replayed = await tick_once(session, now=datetime(2099, 1, 1, tzinfo=timezone.utc), window_bounds=(None, None))
    assert replayed == 0
