"""Tests for GET /api/v1/facilities/{facility_id}/hierarchy."""
import pytest
from httpx import ASGITransport, AsyncClient

from src.db import async_session_factory
from src.main import app
from src.models.hierarchy import Facility, HierarchyNode
from src.services.demo_seed import seed_demo_users
from src.services.facility_seed import seed_facility_catalogue


async def _seed_isolated_test_facility(facility_id: str) -> None:
    # A facility outside the real 78-row catalogue, so ticket 05's sensor
    # channel seeding (which only processes real catalogue rows) never
    # attaches sensor nodes to it -- real facilities like fac_5122 legitimately
    # gain ~100+ sensor child nodes once the whole suite shares one database.
    async with async_session_factory() as session:
        session.add(Facility(id=facility_id, display_name="Isolated Test Facility", facility_type="controlHouse"))
        session.add(
            HierarchyNode(
                id=f"node_{facility_id}", parent_id=None, facility_id=facility_id,
                entity_type="facility", entity_id=facility_id, display_name="Isolated Test Facility",
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


async def _get_hierarchy(token: str, facility_id: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(
            f"/api/v1/facilities/{facility_id}/hierarchy", headers={"Authorization": f"Bearer {token}"}
        )


@pytest.mark.asyncio
async def test_freshly_seeded_facility_has_a_single_leaf_root_node() -> None:
    await _seed_all()
    await _seed_isolated_test_facility("fac_hierarchy_pristine")
    token = await _login("manager", "manager123")
    response = await _get_hierarchy(token, "fac_hierarchy_pristine")
    assert response.status_code == 200
    nodes = response.json()
    assert len(nodes) == 1
    assert nodes[0]["parent_id"] is None
    assert nodes[0]["has_children"] is False
    assert nodes[0]["children_count"] == 0
    assert nodes[0]["path"] == [nodes[0]["id"]]


@pytest.mark.asyncio
async def test_manually_inserted_deeper_chain_is_returned_intact() -> None:
    await _seed_all()
    await _seed_isolated_test_facility("fac_hierarchy_deep_chain")
    async with async_session_factory() as session:
        session.add(
            HierarchyNode(
                id="node_building_1",
                parent_id="node_fac_hierarchy_deep_chain",
                facility_id="fac_hierarchy_deep_chain",
                entity_type="building",
                entity_id="b1",
                display_name="Корпус 1",
            )
        )
        session.add(
            HierarchyNode(
                id="node_collector_1",
                parent_id="node_building_1",
                facility_id="fac_hierarchy_deep_chain",
                entity_type="collector",
                entity_id="c1",
                display_name="Коллектор 1",
            )
        )
        await session.commit()

    token = await _login("manager", "manager123")
    response = await _get_hierarchy(token, "fac_hierarchy_deep_chain")
    nodes = {n["id"]: n for n in response.json()}
    assert len(nodes) == 3

    root = nodes["node_fac_hierarchy_deep_chain"]
    assert root["has_children"] is True
    assert root["children_count"] == 1

    building = nodes["node_building_1"]
    assert building["path"] == ["node_fac_hierarchy_deep_chain", "node_building_1"]
    assert building["has_children"] is True

    collector = nodes["node_collector_1"]
    assert collector["path"] == ["node_fac_hierarchy_deep_chain", "node_building_1", "node_collector_1"]
    assert collector["has_children"] is False
    assert collector["entity_type"] == "collector"


@pytest.mark.asyncio
async def test_hierarchy_for_out_of_scope_facility_returns_403() -> None:
    await _seed_all()
    token = await _login("dispatcher", "dispatcher123")
    response = await _get_hierarchy(token, "fac_20")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_hierarchy_for_nonexistent_facility_returns_404() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _get_hierarchy(token, "fac_does_not_exist")
    assert response.status_code == 404
