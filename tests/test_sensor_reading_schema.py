"""Round-trip tests for SensorReading + EtlIngestedSource (leaf 1.1.2.1)."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from src.db import async_session_factory
from src.models.sensor import EtlIngestedSource, SensorReading


@pytest.mark.asyncio
async def test_numeric_reading_round_trip() -> None:
    async with async_session_factory() as session:
        session.add(
            SensorReading(
                channel_id="1",
                occurred_at=datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
                is_alarm=False,
                raw_value="28",
                numeric_value=28.0,
                is_anomaly=False,
                source_event_id="evt_1",
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        reading = (
            await session.execute(select(SensorReading).where(SensorReading.source_event_id == "evt_1"))
        ).scalar_one()
        assert reading.numeric_value == 28.0
        assert reading.is_anomaly is False


@pytest.mark.asyncio
async def test_anomaly_reading_round_trip_with_null_numeric_value() -> None:
    async with async_session_factory() as session:
        session.add(
            SensorReading(
                channel_id="9330",
                occurred_at=datetime(2026, 8, 1, 8, 2, 2, tzinfo=timezone.utc),
                is_alarm=False,
                raw_value="01.01.1970 03:00:00",
                numeric_value=None,
                is_anomaly=True,
                source_event_id="evt_2",
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        reading = (
            await session.execute(select(SensorReading).where(SensorReading.source_event_id == "evt_2"))
        ).scalar_one()
        assert reading.numeric_value is None
        assert reading.is_anomaly is True


@pytest.mark.asyncio
async def test_etl_ingested_source_round_trip() -> None:
    async with async_session_factory() as session:
        session.add(EtlIngestedSource(source_path="data/example.csv", row_count=42))
        await session.commit()

    async with async_session_factory() as session:
        source = (
            await session.execute(select(EtlIngestedSource).where(EtlIngestedSource.source_path == "data/example.csv"))
        ).scalar_one()
        assert source.row_count == 42
