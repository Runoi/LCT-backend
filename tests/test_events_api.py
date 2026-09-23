"""Tests for GET /api/v1/events (leaf 1.2).

Uses dedicated, non-catalogue facilities/channels throughout so
assertions never depend on real ETL/replay data sharing this database.
"""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.db import async_session_factory
from src.main import app
from src.models.event import Event
from src.models.hierarchy import Facility
from src.models.sensor import SensorChannel, SensorReading
from src.services.demo_seed import seed_demo_users
from src.services.event_sync import sync_events
from src.services.facility_seed import seed_facility_catalogue


async def _seed_channel(suffix: str, facility_id: str | None, sensor_type_id: str = "smoke_detector") -> str:
    channel_id = f"events_api_test_{suffix}"
    async with async_session_factory() as session:
        if facility_id is not None and await session.get(Facility, facility_id) is None:
            session.add(Facility(id=facility_id, display_name=facility_id, facility_type="test", district_id=None))
        if await session.get(SensorChannel, f"sensor_{channel_id}") is None:
            session.add(
                SensorChannel(
                    id=f"sensor_{channel_id}",
                    channel_id=channel_id,
                    tag="",
                    sensor_type_id=sensor_type_id,
                    system_type="fire_protection",
                    display_name=channel_id,
                    facility_id=facility_id,
                    hierarchy_node_id=None,
                )
            )
        await session.commit()
    return channel_id


async def _add_reading(channel_id: str, occurred_at: datetime, suffix: str) -> None:
    async with async_session_factory() as session:
        session.add(
            SensorReading(
                channel_id=channel_id,
                occurred_at=occurred_at,
                is_alarm=True,
                raw_value="x",
                numeric_value=None,
                is_anomaly=False,
                source_event_id=f"events_api_test_{suffix}",
                origin="historical",
            )
        )
        await session.commit()


async def _seed_all() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_demo_users(session)


async def _login(username: str, password: str) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["token"]


async def _get(token: str | None, path: str, **params):
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers, params=params)


@pytest.mark.asyncio
async def test_date_range_filtering() -> None:
    await _seed_all()
    channel_id = await _seed_channel("daterange", "fac_events_daterange")
    await _add_reading(channel_id, datetime(2033, 1, 1, tzinfo=timezone.utc), "early")
    await _add_reading(channel_id, datetime(2033, 6, 1, tzinfo=timezone.utc), "mid")
    await _add_reading(channel_id, datetime(2033, 12, 1, tzinfo=timezone.utc), "late")

    token = await _login("manager", "manager123")
    response = await _get(
        token, "/api/v1/events",
        facility_id="fac_events_daterange",
        **{"from": "2033-03-01T00:00:00+00:00", "to": "2033-09-01T00:00:00+00:00"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["occurred_at"].startswith("2033-06-01")


@pytest.mark.asyncio
async def test_facility_sensor_event_type_filters() -> None:
    await _seed_all()
    smoke_channel = await _seed_channel("filters_smoke", "fac_events_filters", sensor_type_id="smoke_detector")
    door_channel = await _seed_channel("filters_door", "fac_events_filters", sensor_type_id="door_contact")
    now = datetime(2033, 2, 1, tzinfo=timezone.utc)
    await _add_reading(smoke_channel, now, "filters_smoke")
    await _add_reading(door_channel, now, "filters_door")

    token = await _login("manager", "manager123")

    by_sensor = await _get(token, "/api/v1/events", sensor_id=f"sensor_{smoke_channel}")
    assert {e["sensor_id"] for e in by_sensor.json()["data"]} == {f"sensor_{smoke_channel}"}

    by_type = await _get(token, "/api/v1/events", facility_id="fac_events_filters", event_type="door_contact")
    assert {e["sensor_id"] for e in by_type.json()["data"]} == {f"sensor_{door_channel}"}


@pytest.mark.asyncio
async def test_keyset_pagination_covers_all_without_duplicates() -> None:
    await _seed_all()
    channel_id = await _seed_channel("paging", "fac_events_paging")
    base = datetime(2033, 3, 1, tzinfo=timezone.utc)
    for i in range(5):
        await _add_reading(channel_id, base + timedelta(minutes=i), f"paging_{i}")

    token = await _login("manager", "manager123")
    seen_ids: set[str] = set()
    cursor = None
    for _ in range(10):  # generous upper bound on page count
        page = await _get(token, "/api/v1/events", facility_id="fac_events_paging", limit=2, **({"cursor": cursor} if cursor else {}))
        body = page.json()
        page_ids = {e["id"] for e in body["data"]}
        assert seen_ids.isdisjoint(page_ids)
        seen_ids |= page_ids
        cursor = body["meta"]["next_cursor"]
        if cursor is None:
            break
    assert len(seen_ids) == 5


@pytest.mark.asyncio
async def test_orphan_event_visible_only_to_all_facilities_scope() -> None:
    await _seed_all()
    channel_id = await _seed_channel("orphan", None)
    await _add_reading(channel_id, datetime(2033, 4, 1, tzinfo=timezone.utc), "orphan")

    manager_token = await _login("manager", "manager123")
    manager_response = await _get(manager_token, "/api/v1/events", sensor_id=f"sensor_{channel_id}")
    assert len(manager_response.json()["data"]) == 1

    dispatcher_token = await _login("dispatcher", "dispatcher123")
    dispatcher_response = await _get(dispatcher_token, "/api/v1/events", sensor_id=f"sensor_{channel_id}")
    assert len(dispatcher_response.json()["data"]) == 0


@pytest.mark.asyncio
async def test_out_of_scope_facility_excluded_for_dispatcher() -> None:
    await _seed_all()
    channel_id = await _seed_channel("outscope", "fac_events_out_of_scope")
    await _add_reading(channel_id, datetime(2033, 5, 1, tzinfo=timezone.utc), "outscope")

    dispatcher_token = await _login("dispatcher", "dispatcher123")
    response = await _get(dispatcher_token, "/api/v1/events", sensor_id=f"sensor_{channel_id}")
    assert len(response.json()["data"]) == 0


@pytest.mark.asyncio
async def test_confirmed_incident_distinguishable_from_plain_alarm() -> None:
    await _seed_all()
    plain_channel = await _seed_channel("incident_plain", "fac_events_incident")
    confirmed_channel = await _seed_channel("incident_confirmed", "fac_events_incident")
    now = datetime(2033, 7, 1, tzinfo=timezone.utc)
    await _add_reading(plain_channel, now, "incident_plain")
    await _add_reading(confirmed_channel, now, "incident_confirmed")

    async with async_session_factory() as session:
        await sync_events(session)
        confirmed_event = (
            await session.execute(select(Event).where(Event.sensor_id == f"sensor_{confirmed_channel}"))
        ).scalar_one()
        confirmed_event.is_confirmed_incident = True
        confirmed_event.verification_result = "confirmed_true"
        confirmed_event.related_risk_id = "risk_events_api_test"
        await session.commit()

    token = await _login("manager", "manager123")
    response = await _get(token, "/api/v1/events", facility_id="fac_events_incident")
    by_sensor = {e["sensor_id"]: e for e in response.json()["data"]}

    plain = by_sensor[f"sensor_{plain_channel}"]
    confirmed = by_sensor[f"sensor_{confirmed_channel}"]
    assert plain["is_confirmed_incident"] is False
    assert plain["related_risk_id"] is None
    assert confirmed["is_confirmed_incident"] is True
    assert confirmed["verification_result"] == "confirmed_true"
    assert confirmed["related_risk_id"] == "risk_events_api_test"
    assert plain["state"] == confirmed["state"] == "alarm"  # same alert state; incident status is a separate field


@pytest.mark.asyncio
async def test_invalid_from_returns_400() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _get(token, "/api/v1/events", **{"from": "not-a-date"})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_events_requires_authentication() -> None:
    response = await _get(None, "/api/v1/events")
    assert response.status_code == 401
