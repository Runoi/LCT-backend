"""Tests for GET /api/v1/facilities/{facility_id}."""
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


async def _get_detail(token: str, facility_id: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(f"/api/v1/facilities/{facility_id}", headers={"Authorization": f"Bearer {token}"})


@pytest.mark.asyncio
async def test_detail_returns_full_shape_for_in_scope_facility() -> None:
    await _seed_all()
    token = await _login("dispatcher", "dispatcher123")
    response = await _get_detail(token, "fac_5122")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "fac_5122"
    assert "source_health" in body and isinstance(body["source_health"], list)
    for field in ("current_state", "forecast", "incidents", "assets", "data_health", "priority_score"):
        assert field in body


@pytest.mark.asyncio
async def test_detail_for_out_of_scope_facility_returns_403_without_leaking_data() -> None:
    await _seed_all()
    token = await _login("dispatcher", "dispatcher123")

    # dispatcher's scope is only fac_5122/fac_5339; fac_20 is a real facility outside it
    response = await _get_detail(token, "fac_20")
    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "FACILITY_ACCESS_DENIED"
    assert "fac_20" not in str(body)  # no facility identifier/name leaked in the denial body
    assert "display_name" not in body["error"].get("details", {})


@pytest.mark.asyncio
async def test_detail_for_nonexistent_facility_returns_404() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _get_detail(token, "fac_does_not_exist")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_and_detail_share_the_exact_same_shape() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        list_response = await client.get(
            "/api/v1/facilities", headers={"Authorization": f"Bearer {token}"}, params={"limit": 200}
        )
    list_item = next(item for item in list_response.json()["data"] if item["id"] == "fac_5122")

    detail_response = await _get_detail(token, "fac_5122")
    detail_item = detail_response.json()

    assert list_item.keys() == detail_item.keys()
