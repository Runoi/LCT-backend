"""Tests for GET /api/v1/facilities/{facility_id}/layout."""
import pytest
from httpx import ASGITransport, AsyncClient

from src.db import async_session_factory
from src.main import app
from src.models.hierarchy import Facility, HierarchyNode
from src.services.demo_seed import seed_demo_users
from src.services.facility_seed import seed_facility_catalogue


async def _seed_all() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_demo_users(session)


async def _seed_isolated_test_facility(facility_id: str) -> None:
    # Outside the real 78-row catalogue, so ticket 05's sensor channel
    # seeding never attaches sensor nodes to it (see the identical helper
    # in test_facility_hierarchy_endpoint.py).
    async with async_session_factory() as session:
        session.add(Facility(id=facility_id, display_name="Isolated Test Facility", facility_type="controlHouse"))
        session.add(
            HierarchyNode(
                id=f"node_{facility_id}", parent_id=None, facility_id=facility_id,
                entity_type="facility", entity_id=facility_id, display_name="Isolated Test Facility",
            )
        )
        await session.commit()


async def _login(username: str, password: str) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["token"]


async def _get_layout(token: str, facility_id: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(
            f"/api/v1/facilities/{facility_id}/layout", headers={"Authorization": f"Bearer {token}"}
        )


@pytest.mark.asyncio
async def test_layout_returns_valid_geojson_with_one_feature_per_node() -> None:
    await _seed_all()
    await _seed_isolated_test_facility("fac_layout_pristine")
    token = await _login("manager", "manager123")
    response = await _get_layout(token, "fac_layout_pristine")
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 1  # freshly-seeded facility has one root node
    feature = body["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Point"
    assert feature["properties"]["is_demo"] is True


@pytest.mark.asyncio
async def test_layout_is_deterministic_across_repeated_calls() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    first = await _get_layout(token, "fac_5122")
    second = await _get_layout(token, "fac_5122")
    assert first.json() == second.json()


@pytest.mark.asyncio
async def test_layout_for_out_of_scope_facility_returns_403() -> None:
    await _seed_all()
    token = await _login("dispatcher", "dispatcher123")
    response = await _get_layout(token, "fac_20")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_layout_for_nonexistent_facility_returns_404() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _get_layout(token, "fac_does_not_exist")
    assert response.status_code == 404
