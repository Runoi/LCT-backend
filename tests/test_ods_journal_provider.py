"""Tests for the synthetic ОДС journal provider (leaf 1.2.1).

Seeds its own dedicated, non-catalogue Facility/SensorChannel rows for the
"historical" alarm data it grounds weights in -- never reusing real
catalogue facility ids -- so these assertions hold whether this file runs
alone (no real ETL data yet) or as part of the full suite (where the real
169993-row ETL also contributes historical alarms in the same global
aggregate, on completely different, real facility ids).
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from src.db import async_session_factory
from src.models.emulation_providers import OdsJournalEntry, SyntheticProviderRun
from src.models.hierarchy import Facility
from src.models.sensor import SensorChannel, SensorReading
from src.services.ods_journal_provider import PROVIDER, generate_ods_journal


async def _reset_provider_run() -> None:
    async with async_session_factory() as session:
        existing = await session.get(SyntheticProviderRun, PROVIDER)
        if existing is not None:
            await session.delete(existing)
        await session.execute(OdsJournalEntry.__table__.delete())
        await session.commit()


async def _seed_grounding_alarms() -> tuple[str, str]:
    """Give one dedicated test facility 10x the alarm volume of another."""
    busy_facility, quiet_facility = "fac_ods_test_busy", "fac_ods_test_quiet"
    busy_channel, quiet_channel = "ods_test_busy_channel", "ods_test_quiet_channel"

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

    base = datetime(2028, 1, 1, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        for i in range(10):
            session.add(
                SensorReading(
                    channel_id=busy_channel,
                    occurred_at=base + timedelta(minutes=i),
                    is_alarm=True,
                    raw_value="x",
                    numeric_value=None,
                    is_anomaly=False,
                    source_event_id=f"ods_test_busy_{i}",
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
                source_event_id="ods_test_quiet_0",
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
        first_count = await generate_ods_journal(session, seed=1)
    async with async_session_factory() as session:
        second_count = await generate_ods_journal(session, seed=1)
    assert first_count > 0
    assert second_count == 0


@pytest.mark.asyncio
async def test_same_seed_reproduces_the_same_entry_count() -> None:
    await _reset_provider_run()
    await _seed_grounding_alarms()
    fixed_now = datetime(2027, 1, 1, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        first_count = await generate_ods_journal(session, seed=99, now=fixed_now)

    await _reset_provider_run()
    async with async_session_factory() as session:
        second_count = await generate_ods_journal(session, seed=99, now=fixed_now)

    assert first_count == second_count
    assert first_count > 0


@pytest.mark.asyncio
async def test_facility_with_more_real_alarms_gets_a_larger_share() -> None:
    await _reset_provider_run()
    busy_facility, quiet_facility = await _seed_grounding_alarms()

    async with async_session_factory() as session:
        await generate_ods_journal(session, seed=1)

    async with async_session_factory() as session:
        entry_counts_by_facility = dict(
            (
                await session.execute(
                    select(OdsJournalEntry.facility_id, func.count(OdsJournalEntry.id)).group_by(
                        OdsJournalEntry.facility_id
                    )
                )
            ).all()
        )

    assert entry_counts_by_facility.get(busy_facility, 0) >= entry_counts_by_facility.get(quiet_facility, 0)
