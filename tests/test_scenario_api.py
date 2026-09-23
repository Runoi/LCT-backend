"""Tests for GET/POST /api/v1/system/scenarios* (leaf 1.3.2)."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

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


async def _login(username: str, password: str) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["token"]


async def _get(token: str, path: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers={"Authorization": f"Bearer {token}"})


async def _post(token: str, path: str, json: dict):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, headers={"Authorization": f"Bearer {token}"}, json=json)


@pytest.mark.asyncio
async def test_list_scenarios_returns_16() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _get(token, "/api/v1/system/scenarios")
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 16
    assert all({"id", "display_name", "category", "description"} <= set(s.keys()) for s in body["data"])


@pytest.mark.asyncio
async def test_activate_known_scenario_inserts_readings() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")

    async with async_session_factory() as session:
        facility_id = (
            await session.execute(
                select(SensorChannel.facility_id)
                .where(SensorChannel.sensor_type_id == "smoke_detector", SensorChannel.facility_id.isnot(None))
                .limit(1)
            )
        ).scalar_one()

    response = await _post(token, "/api/v1/system/scenarios/fire_smoke_only/activate", {"facility_id": facility_id, "seed": 1})
    assert response.status_code == 200
    body = response.json()
    assert body == {"scenario_id": "fire_smoke_only", "facility_id": facility_id, "readings_inserted": 1}


@pytest.mark.asyncio
async def test_activate_unknown_scenario_returns_422() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _post(token, "/api/v1/system/scenarios/does_not_exist/activate", {"facility_id": "fac_5122"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_activate_scenario_at_facility_missing_sensor_type_returns_422() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _post(
        token, "/api/v1/system/scenarios/fire_smoke_only/activate", {"facility_id": "fac_definitely_does_not_exist_999"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_scenarios_requires_authentication() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/system/scenarios")
    assert response.status_code == 401
