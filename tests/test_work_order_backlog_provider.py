"""Tests for the synthetic work-order backlog provider (leaf 1.2.2).

Seeds its own dedicated, non-catalogue Facility/SensorChannel rows for the
alarm data it grounds weights in (see test_ods_journal_provider.py for
why: real ETL data sharing this table could otherwise dominate an
arbitrarily-chosen real facility and invert the comparison).
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from src.db import async_session_factory
from src.models.emulation_providers import ExternalWorkOrderRecord, SyntheticProviderRun
from src.models.hierarchy import Facility
from src.models.sensor import SensorChannel, SensorReading
from src.services.work_order_backlog_provider import PROVIDER, generate_work_order_backlog


async def _reset_provider_run() -> None:
    async with async_session_factory() as session:
        existing = await session.get(SyntheticProviderRun, PROVIDER)
        if existing is not None:
            await session.delete(existing)
        await session.execute(ExternalWorkOrderRecord.__table__.delete())
        await session.commit()


async def _seed_grounding_alarms() -> tuple[str, str]:
    busy_facility, quiet_facility = "fac_ewo_test_busy", "fac_ewo_test_quiet"
    busy_channel, quiet_channel = "ewo_test_busy_channel", "ewo_test_quiet_channel"

    async with async_session_factory() as session:
        for facility_id, channel_id in ((busy_facility, busy_channel), (quiet_facility, quiet_channel)):
            if await session.get(Facility, facility_id) is None:
                session.add(Facility(id=facility_id, display_name=facility_id, facility_type="test", district_id=None))
            if await session.get(SensorChannel, f"sensor_{channel_id}") is None:
                session.add(
                    SensorChannel(
                        id=f"sensor_{channel_id}",
                        channel_id=channel_id,
                        tag="",
                        sensor_type_id="temperature_sensor",
                        system_type="temperature",
                        display_name=channel_id,
                        facility_id=facility_id,
                        hierarchy_node_id=None,
                    )
                )
        await session.commit()

    base = datetime(2029, 1, 1, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        for i in range(20):
            session.add(
                SensorReading(
                    channel_id=busy_channel,
                    occurred_at=base + timedelta(minutes=i),
                    is_alarm=True,
                    raw_value="x",
                    numeric_value=None,
                    is_anomaly=False,
                    source_event_id=f"ewo_test_busy_{i}",
                    origin="historical",
                )
            )
        session.add(
            SensorReading(
                channel_id=quiet_channel,
                occurred_at=base,
                is_alarm=True,
                raw_value="x",
                numeric_value=None,
                is_anomaly=False,
                source_event_id="ewo_test_quiet_0",
                origin="historical",
            )
        )
        await session.commit()
    return busy_facility, quiet_facility


@pytest.mark.asyncio
async def test_generation_is_idempotent() -> None:
    await _reset_provider_run()
    await _seed_grounding_alarms()
    async with async_session_factory() as session:
        first_count = await generate_work_order_backlog(session, seed=1)
    async with async_session_factory() as session:
        second_count = await generate_work_order_backlog(session, seed=1)
    assert first_count > 0
    assert second_count == 0


@pytest.mark.asyncio
async def test_same_seed_reproduces_the_same_backlog_size() -> None:
    await _reset_provider_run()
    await _seed_grounding_alarms()
    fixed_now = datetime(2027, 1, 1, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        first_count = await generate_work_order_backlog(session, seed=55, now=fixed_now)

    await _reset_provider_run()
    async with async_session_factory() as session:
        second_count = await generate_work_order_backlog(session, seed=55, now=fixed_now)

    assert first_count == second_count
    assert first_count > 0


@pytest.mark.asyncio
async def test_facility_with_more_real_alarms_gets_a_larger_backlog_share() -> None:
    await _reset_provider_run()
    busy_facility, quiet_facility = await _seed_grounding_alarms()

    async with async_session_factory() as session:
        await generate_work_order_backlog(session, seed=1)

    async with async_session_factory() as session:
        counts_by_facility = dict(
            (
                await session.execute(
                    select(ExternalWorkOrderRecord.facility_id, func.count(ExternalWorkOrderRecord.id)).group_by(
                        ExternalWorkOrderRecord.facility_id
                    )
                )
            ).all()
        )

    assert counts_by_facility.get(busy_facility, 0) >= counts_by_facility.get(quiet_facility, 0)


@pytest.mark.asyncio
async def test_status_is_restricted_to_terminal_states() -> None:
    await _reset_provider_run()
    await _seed_grounding_alarms()
    async with async_session_factory() as session:
        await generate_work_order_backlog(session, seed=1)

    async with async_session_factory() as session:
        statuses = set(
            (await session.execute(select(ExternalWorkOrderRecord.status))).scalars().all()
        )
    assert statuses <= {"completed", "cancelled"}
