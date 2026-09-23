"""Facility detail/list source_health must match the dedicated endpoint (leaf 1.3.2).

Regression coverage for ticket 04's original hardcoded "unavailable"
placeholder being replaced with the real ticket 06 source-health service.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from src.db import async_session_factory
from src.main import app
from src.services.demo_seed import seed_demo_users
from src.services.facility_seed import seed_facility_catalogue


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


async def _get(token: str, path: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers={"Authorization": f"Bearer {token}"})


@pytest.mark.asyncio
async def test_facility_detail_source_health_matches_dedicated_endpoint() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")

    system_response = await _get(token, "/api/v1/system/source-health")
    assert system_response.status_code == 200
    expected_sources = {(e["source"], e["status"]) for e in system_response.json()["data"]}

    facilities = await _get(token, "/api/v1/facilities?limit=1")
    facility_id = facilities.json()["data"][0]["id"]

    detail = await _get(token, f"/api/v1/facilities/{facility_id}")
    assert detail.status_code == 200
    detail_sources = {(e["source"], e["status"]) for e in detail.json()["source_health"]}

    assert detail_sources == expected_sources
    assert len(expected_sources) == 4  # not the ticket-04 single hardcoded placeholder entry


@pytest.mark.asyncio
async def test_facility_list_source_health_matches_dedicated_endpoint() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")

    system_response = await _get(token, "/api/v1/system/source-health")
    expected_sources = {(e["source"], e["status"]) for e in system_response.json()["data"]}

    listed = await _get(token, "/api/v1/facilities?limit=3")
    for item in listed.json()["data"]:
        item_sources = {(e["source"], e["status"]) for e in item["source_health"]}
        assert item_sources == expected_sources
