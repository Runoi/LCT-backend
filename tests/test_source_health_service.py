"""Tests for source-health computation + degradation override (leaf 1.3.1).

All assertions drive an explicit `now` -- no real sleep -- and clean up
their own ReplayState/SyntheticProviderRun/SourceHealthOverride rows so
they don't interfere with other tests sharing this database.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.db import async_session_factory
from src.models.emulation_providers import SyntheticProviderRun
from src.models.replay import SINGLETON_ID, ReplayState
from src.models.source_health import SourceHealthOverride
from src.services.reference_data import FRESHNESS_BOUNDARIES
from src.services.source_health import (
    SOURCES,
    InvalidStatusError,
    UnknownSourceError,
    clear_source_health_override,
    get_source_health,
    set_source_health_override,
)

_FRESH_MAX = next(b.max_age_seconds for b in FRESHNESS_BOUNDARIES if b.id == "fresh")
_DELAYED_MAX = next(b.max_age_seconds for b in FRESHNESS_BOUNDARIES if b.id == "delayed")


async def _reset_all_state() -> None:
    async with async_session_factory() as session:
        state = (await session.execute(select(ReplayState).where(ReplayState.id == SINGLETON_ID))).scalar_one_or_none()
        if state is not None:
            await session.delete(state)
        for source, _ in SOURCES:
            run = await session.get(SyntheticProviderRun, source)
            if run is not None:
                await session.delete(run)
            override = await session.get(SourceHealthOverride, source)
            if override is not None:
                await session.delete(override)
        await session.commit()


async def _set_last_success(source: str, last_success_at: datetime) -> None:
    async with async_session_factory() as session:
        if source == "smvu":
            session.add(ReplayState(id=SINGLETON_ID, virtual_cursor=last_success_at, last_tick_at=last_success_at, tick_count=1))
        else:
            session.add(SyntheticProviderRun(provider=source, last_run_at=last_success_at, row_count=1))
        await session.commit()


@pytest.mark.asyncio
async def test_no_data_at_all_is_unavailable_for_every_source() -> None:
    await _reset_all_state()
    async with async_session_factory() as session:
        entries = await get_source_health(session, now=datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert len(entries) == 4
    assert {e.source for e in entries} == {"smvu", "ods_journal", "equipment_registry", "work_order_system"}
    assert all(e.status == "unavailable" and e.last_success_at is None and e.delay_seconds is None for e in entries)


@pytest.mark.asyncio
async def test_status_thresholds_match_freshness_boundaries_exactly() -> None:
    await _reset_all_state()
    now = datetime(2030, 2, 1, tzinfo=timezone.utc)
    await _set_last_success("smvu", now - timedelta(seconds=_FRESH_MAX))
    async with async_session_factory() as session:
        entries = await get_source_health(session, now=now)
    smvu = next(e for e in entries if e.source == "smvu")
    assert smvu.status == "online"
    assert smvu.delay_seconds == _FRESH_MAX

    await _reset_all_state()
    await _set_last_success("smvu", now - timedelta(seconds=_FRESH_MAX + 1))
    async with async_session_factory() as session:
        entries = await get_source_health(session, now=now)
    smvu = next(e for e in entries if e.source == "smvu")
    assert smvu.status == "delayed"

    await _reset_all_state()
    await _set_last_success("smvu", now - timedelta(seconds=_DELAYED_MAX + 1))
    async with async_session_factory() as session:
        entries = await get_source_health(session, now=now)
    smvu = next(e for e in entries if e.source == "smvu")
    assert smvu.status == "unavailable"


@pytest.mark.asyncio
async def test_override_forces_status_regardless_of_real_freshness() -> None:
    await _reset_all_state()
    now = datetime(2030, 3, 1, tzinfo=timezone.utc)
    await _set_last_success("ods_journal", now)  # would otherwise be "online"

    async with async_session_factory() as session:
        await set_source_health_override(session, "ods_journal", "unavailable", duration_seconds=60, now=now)
        entries = await get_source_health(session, now=now)
    ods = next(e for e in entries if e.source == "ods_journal")
    assert ods.status == "unavailable"


@pytest.mark.asyncio
async def test_override_expires_and_reverts_to_computed_status() -> None:
    await _reset_all_state()
    now = datetime(2030, 4, 1, tzinfo=timezone.utc)
    await _set_last_success("equipment_registry", now)

    async with async_session_factory() as session:
        await set_source_health_override(session, "equipment_registry", "unavailable", duration_seconds=60, now=now)

    past_expiry = now + timedelta(seconds=61)
    async with async_session_factory() as session:
        entries = await get_source_health(session, now=past_expiry)
    eq = next(e for e in entries if e.source == "equipment_registry")
    assert eq.status == "online"  # override expired; reverts to freshness-based


@pytest.mark.asyncio
async def test_clear_override_reverts_immediately() -> None:
    await _reset_all_state()
    now = datetime(2030, 5, 1, tzinfo=timezone.utc)
    await _set_last_success("work_order_system", now)

    async with async_session_factory() as session:
        await set_source_health_override(session, "work_order_system", "delayed", duration_seconds=3600, now=now)
        await clear_source_health_override(session, "work_order_system")
        entries = await get_source_health(session, now=now)
    wos = next(e for e in entries if e.source == "work_order_system")
    assert wos.status == "online"


@pytest.mark.asyncio
async def test_unknown_source_raises_on_override_and_clear() -> None:
    async with async_session_factory() as session:
        with pytest.raises(UnknownSourceError):
            await set_source_health_override(session, "not_a_real_source", "unavailable", duration_seconds=10)
        with pytest.raises(UnknownSourceError):
            await clear_source_health_override(session, "not_a_real_source")


@pytest.mark.asyncio
async def test_invalid_status_raises() -> None:
    async with async_session_factory() as session:
        with pytest.raises(InvalidStatusError):
            await set_source_health_override(session, "smvu", "not_a_real_status", duration_seconds=10)
