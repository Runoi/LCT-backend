"""Tests for materializing Event rows from SensorReading (leaf 1.1).

sync_events scans ALL SensorReading rows past the global high-water-mark,
so once the whole suite shares one database it will also materialize
alarms from real ETL data and other test files' fixtures -- harmless,
since every assertion here is scoped to this file's own dedicated,
non-catalogue channel (never a raw global count).
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.db import async_session_factory
from src.models.event import Event
from src.models.hierarchy import Facility
from src.models.sensor import SensorChannel, SensorReading
from src.services.event_sync import sync_events


async def _seed_channel(suffix: str, facility_id: str | None) -> str:
    channel_id = f"event_sync_test_{suffix}"
    async with async_session_factory() as session:
        if facility_id is not None and await session.get(Facility, facility_id) is None:
            session.add(Facility(id=facility_id, display_name=facility_id, facility_type="test", district_id=None))
        session.add(
            SensorChannel(
                id=f"sensor_{channel_id}",
                channel_id=channel_id,
                tag="",
                sensor_type_id="smoke_detector",
                system_type="fire_protection",
                display_name=channel_id,
                facility_id=facility_id,
                hierarchy_node_id=None,
            )
        )
        await session.commit()
    return channel_id


async def _add_reading(channel_id: str, *, is_alarm: bool, is_anomaly: bool, suffix: str, raw_value: str = "x") -> int:
    async with async_session_factory() as session:
        reading = SensorReading(
            channel_id=channel_id,
            occurred_at=datetime(2032, 1, 1, tzinfo=timezone.utc),
            is_alarm=is_alarm,
            raw_value=raw_value,
            numeric_value=None,
            is_anomaly=is_anomaly,
            source_event_id=f"event_sync_test_{suffix}",
            origin="historical",
        )
        session.add(reading)
        await session.commit()
        await session.refresh(reading)
        return reading.id


async def _events_for_channel(sensor_id: str) -> list[Event]:
    async with async_session_factory() as session:
        return (
            (await session.execute(select(Event).where(Event.sensor_id == sensor_id).order_by(Event.id)))
            .scalars()
            .all()
        )


@pytest.mark.asyncio
async def test_only_alarm_or_anomaly_readings_become_events() -> None:
    channel_id = await _seed_channel("filter", "fac_event_sync_filter")
    sensor_id = f"sensor_{channel_id}"

    await _add_reading(channel_id, is_alarm=False, is_anomaly=False, suffix="normal")
    await _add_reading(channel_id, is_alarm=True, is_anomaly=False, suffix="alarm")
    await _add_reading(channel_id, is_alarm=False, is_anomaly=True, suffix="anomaly")

    async with async_session_factory() as session:
        await sync_events(session, now=datetime(2032, 1, 1, 1, 0, 0, tzinfo=timezone.utc))

    events = await _events_for_channel(sensor_id)
    assert {e.value for e in events} == {"x"}
    assert len(events) == 2  # normal reading excluded
    states = {e.state for e in events}
    assert states == {"alarm", "fault"}


@pytest.mark.asyncio
async def test_sync_is_idempotent() -> None:
    channel_id = await _seed_channel("idempotent", "fac_event_sync_idempotent")
    await _add_reading(channel_id, is_alarm=True, is_anomaly=False, suffix="idempotent")

    async with async_session_factory() as session:
        first_count = await sync_events(session)
    async with async_session_factory() as session:
        second_count = await sync_events(session)

    assert first_count >= 1  # at least our own reading (possibly more from other tests sharing the DB)
    assert second_count == 0


@pytest.mark.asyncio
async def test_event_fields_are_derived_correctly() -> None:
    channel_id = await _seed_channel("fields", "fac_event_sync_fields")
    sensor_id = f"sensor_{channel_id}"
    now = datetime(2032, 2, 1, tzinfo=timezone.utc)

    await _add_reading(channel_id, is_alarm=True, is_anomaly=False, suffix="fields", raw_value="Дым обнаружен")

    async with async_session_factory() as session:
        await sync_events(session, now=now)

    events = await _events_for_channel(sensor_id)
    event = next(e for e in events if e.value == "Дым обнаружен")
    assert event.event_type == "smoke_detector"
    assert event.source == "smvu"
    assert event.facility_id == "fac_event_sync_fields"
    assert event.sensor_id == sensor_id
    assert event.state == "alarm"
    assert event.ingested_at == now
    assert event.is_confirmed_incident is False
    assert event.verification_result is None
    assert event.resolved_at is None
    assert event.related_risk_id is None


@pytest.mark.asyncio
async def test_orphan_channel_reading_creates_event_with_null_facility() -> None:
    channel_id = await _seed_channel("orphan", None)
    sensor_id = f"sensor_{channel_id}"

    await _add_reading(channel_id, is_alarm=True, is_anomaly=False, suffix="orphan")

    async with async_session_factory() as session:
        await sync_events(session)

    events = await _events_for_channel(sensor_id)
    assert len(events) == 1
    assert events[0].facility_id is None


@pytest.mark.asyncio
async def test_setting_confirmed_incident_round_trips_directly_on_the_row() -> None:
    channel_id = await _seed_channel("incident", "fac_event_sync_incident")
    sensor_id = f"sensor_{channel_id}"
    await _add_reading(channel_id, is_alarm=True, is_anomaly=False, suffix="incident")

    async with async_session_factory() as session:
        await sync_events(session)

    events = await _events_for_channel(sensor_id)
    event_id = events[0].id
    resolved_at = datetime(2032, 3, 1, tzinfo=timezone.utc)

    async with async_session_factory() as session:
        event = await session.get(Event, event_id)
        event.is_confirmed_incident = True
        event.verification_result = "confirmed_true"
        event.resolved_at = resolved_at
        event.related_risk_id = "risk_test_1"
        await session.commit()

    async with async_session_factory() as session:
        reloaded = await session.get(Event, event_id)
    assert reloaded.is_confirmed_incident is True
    assert reloaded.verification_result == "confirmed_true"
    assert reloaded.resolved_at == resolved_at
    assert reloaded.related_risk_id == "risk_test_1"
