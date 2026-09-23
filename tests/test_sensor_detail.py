"""Tests for GET /api/v1/sensors/{sensor_id}."""
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.db import async_session_factory
from src.main import app
from src.models.sensor import SensorChannel, SensorReading
from src.services.demo_seed import seed_demo_users
from src.services.facility_seed import seed_facility_catalogue
from src.services.sensor_channel_seed import seed_sensor_channel_catalogue


async def _seed_all() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_sensor_channel_catalogue(session)
        await seed_demo_users(session)


async def _seed_test_channel(suffix: str, facility_id: str) -> str:
    # A dedicated, non-catalogue channel -- never one of the real 11 485
    # channels, so it can never collide with the real readings that
    # test_event_etl.py ingests into the same shared database when the
    # whole suite runs together (a real channel could otherwise already
    # carry readings before this test adds its own).
    channel_id = f"test_detail_{suffix}"
    sensor_id = f"sensor_{channel_id}"
    async with async_session_factory() as session:
        session.add(
            SensorChannel(
                id=sensor_id,
                channel_id=channel_id,
                tag="",
                sensor_type_id="temperature_sensor",
                system_type="temperature",
                display_name=f"Test sensor {suffix}",
                facility_id=facility_id,
                hierarchy_node_id=f"node_{facility_id}",
            )
        )
        await session.commit()
    return sensor_id


async def _login(username: str, password: str) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["token"]


async def _get_detail(token: str, sensor_id: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(f"/api/v1/sensors/{sensor_id}", headers={"Authorization": f"Bearer {token}"})


@pytest.mark.asyncio
async def test_detail_returns_full_shape_for_in_scope_sensor() -> None:
    await _seed_all()
    sensor_id = await _seed_test_channel("1", "fac_5122")
    token = await _login("dispatcher", "dispatcher123")

    response = await _get_detail(token, sensor_id)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == sensor_id
    for field in ("hierarchy_path", "current_reading", "current_state", "data_health", "maintenance_state"):
        assert field in body
    assert body["current_reading"] is None  # no readings ingested in this test


@pytest.mark.asyncio
async def test_detail_includes_the_latest_reading_when_one_exists() -> None:
    await _seed_all()
    sensor_id = await _seed_test_channel("2", "fac_5122")
    async with async_session_factory() as session:
        channel = (await session.execute(select(SensorChannel).where(SensorChannel.id == sensor_id))).scalar_one()
        session.add(
            SensorReading(
                channel_id=channel.channel_id,
                occurred_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                is_alarm=False,
                raw_value="28",
                numeric_value=28.0,
                is_anomaly=False,
                source_event_id="evt_detail_test",
            )
        )
        await session.commit()

    token = await _login("manager", "manager123")
    response = await _get_detail(token, sensor_id)
    assert response.json()["current_reading"]["numeric_value"] == 28.0


@pytest.mark.asyncio
async def test_detail_for_out_of_scope_sensor_returns_403() -> None:
    await _seed_all()
    sensor_id = await _seed_test_channel("3", "fac_20")  # not assigned to dispatcher
    token = await _login("dispatcher", "dispatcher123")
    response = await _get_detail(token, sensor_id)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_detail_for_nonexistent_sensor_returns_404() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _get_detail(token, "sensor_does_not_exist")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_orphan_sensor_reachable_only_by_all_facilities_caller() -> None:
    await _seed_all()
    async with async_session_factory() as session:
        session.add(
            SensorChannel(
                id="sensor_orphan_detail_1",
                channel_id="700010",
                tag="",
                sensor_type_id="unknown",
                system_type="unknown",
                display_name="Неизвестный канал 700010",
                facility_id=None,
                hierarchy_node_id=None,
            )
        )
        await session.commit()

    manager_token = await _login("manager", "manager123")
    manager_response = await _get_detail(manager_token, "sensor_orphan_detail_1")
    assert manager_response.status_code == 200

    dispatcher_token = await _login("dispatcher", "dispatcher123")
    dispatcher_response = await _get_detail(dispatcher_token, "sensor_orphan_detail_1")
    assert dispatcher_response.status_code == 403
