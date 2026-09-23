"""Tests for the streaming event-log ETL."""
from pathlib import Path

import pytest
from sqlalchemy import func, select

from src.db import async_session_factory
from src.models.sensor import EtlIngestedSource, SensorChannel, SensorReading
from src.services.event_etl import ingest_event_log
from src.services.facility_seed import seed_facility_catalogue
from src.services.sensor_channel_seed import seed_sensor_channel_catalogue

FIXTURE_WITH_ORPHAN = Path(__file__).parent / "fixtures" / "event_log_variants.csv"
FIXTURE_IDEMPOTENCY = Path(__file__).parent / "fixtures" / "event_log_idempotency_check.csv"


@pytest.mark.asyncio
async def test_real_operational_window_ingests_every_row_exactly_once() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_sensor_channel_catalogue(session)
        ingested = await ingest_event_log(session)
        assert ingested == 169993

    async with async_session_factory() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(SensorReading).where(SensorReading.source_event_id.isnot(None))
            )
        ).scalar_one()
        assert count >= 169993  # >= because other tests may add readings to a shared db in one suite run

        source = (
            await session.execute(
                select(EtlIngestedSource).where(EtlIngestedSource.source_path == "data\\журнал_событий_пример.csv")
            )
        ).scalar_one_or_none()
        if source is None:  # posix-style path recorded instead, depending on platform
            source = (
                await session.execute(
                    select(EtlIngestedSource).where(EtlIngestedSource.source_path.like("%журнал_событий_пример.csv"))
                )
            ).scalar_one()
        assert source.row_count == 169993


@pytest.mark.asyncio
async def test_second_ingest_of_the_same_source_is_a_no_op() -> None:
    # Uses its own dedicated fixture (distinct channel ids from every other
    # fixture in this file/suite) so this test's outcome never depends on
    # whether another test already ingested the same source in a shared db.
    async with async_session_factory() as session:
        first = await ingest_event_log(session, csv_path=FIXTURE_IDEMPOTENCY)
        second = await ingest_event_log(session, csv_path=FIXTURE_IDEMPOTENCY)
        assert first == 2
        assert second == 0


@pytest.mark.asyncio
async def test_orphaned_channel_id_creates_placeholder_not_dropped() -> None:
    async with async_session_factory() as session:
        ingested = await ingest_event_log(session, csv_path=FIXTURE_WITH_ORPHAN)
        assert ingested == 5  # the fixture has 5 rows, none pre-seeded

    async with async_session_factory() as session:
        for channel_id in ("800001", "800099", "800002", "800003"):
            channel = (
                await session.execute(select(SensorChannel).where(SensorChannel.channel_id == channel_id))
            ).scalar_one()
            assert channel.sensor_type_id == "unknown"
            assert channel.facility_id is None

        readings = (
            await session.execute(select(SensorReading).where(SensorReading.channel_id == "800001"))
        ).scalars().all()
        assert len(readings) == 2

        sentinel_reading = (
            await session.execute(select(SensorReading).where(SensorReading.channel_id == "800099"))
        ).scalar_one()
        assert sentinel_reading.is_anomaly is True
