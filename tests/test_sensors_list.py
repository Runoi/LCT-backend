"""Tests for GET /api/v1/sensors."""
import pytest
from httpx import ASGITransport, AsyncClient

from src.db import async_session_factory
from src.main import app
from src.models.sensor import SensorChannel
from src.services.demo_seed import seed_demo_users
from src.services.facility_seed import seed_facility_catalogue
from src.services.sensor_channel_seed import seed_sensor_channel_catalogue


async def _seed_all() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_sensor_channel_catalogue(session)
        await seed_demo_users(session)


async def _seed_orphan(channel_id: str) -> None:
    async with async_session_factory() as session:
        session.add(
            SensorChannel(
                id=f"sensor_{channel_id}",
                channel_id=channel_id,
                tag="",
                sensor_type_id="unknown",
                system_type="unknown",
                display_name=f"Неизвестный канал {channel_id}",
                facility_id=None,
                hierarchy_node_id=None,
            )
        )
        await session.commit()


async def _login(username: str, password: str) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["token"]


async def _get_sensors(token: str, **params):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/v1/sensors", headers={"Authorization": f"Bearer {token}"}, params=params)


@pytest.mark.asyncio
async def test_manager_sees_all_channels_including_orphans() -> None:
    await _seed_all()
    await _seed_orphan("700001")
    token = await _login("manager", "manager123")
    response = await _get_sensors(token, limit=200, query="Неизвестный канал 700001")
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["facility_id"] is None
    assert body["data"][0]["sensor_type"] == "unknown"


@pytest.mark.asyncio
async def test_dispatcher_never_sees_orphaned_channels() -> None:
    await _seed_all()
    await _seed_orphan("700002")
    token = await _login("dispatcher", "dispatcher123")
    response = await _get_sensors(token, limit=200, query="700002")
    assert response.status_code == 200
    assert response.json()["meta"]["total"] == 0


@pytest.mark.asyncio
async def test_dispatcher_sees_only_sensors_of_assigned_facilities() -> None:
    await _seed_all()
    token = await _login("dispatcher", "dispatcher123")
    response = await _get_sensors(token, limit=200)
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] > 0
    assert all(item["facility_id"] in ("fac_5122", "fac_5339") for item in body["data"])


@pytest.mark.asyncio
async def test_type_filter_narrows_to_one_sensor_type() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _get_sensors(token, type="smoke_detector", limit=200)
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] > 0
    assert all(item["sensor_type"] == "smoke_detector" for item in body["data"])


@pytest.mark.asyncio
async def test_every_sensor_lacks_geolocation_but_stays_listed() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _get_sensors(token, limit=10)
    body = response.json()
    assert len(body["data"]) == 10
    for item in body["data"]:
        assert item["has_geolocation"] is False
        assert item["position"] is None


@pytest.mark.asyncio
async def test_pagination_cursor_advances_through_pages() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    page1 = await _get_sensors(token, limit=100)
    body1 = page1.json()
    assert len(body1["data"]) == 100
    assert body1["meta"]["next_cursor"] is not None

    page2 = await _get_sensors(token, limit=100, cursor=body1["meta"]["next_cursor"])
    body2 = page2.json()
    ids1 = {item["id"] for item in body1["data"]}
    ids2 = {item["id"] for item in body2["data"]}
    assert ids1.isdisjoint(ids2)


@pytest.mark.asyncio
async def test_sensors_requires_authentication() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/sensors")
    assert response.status_code == 401
