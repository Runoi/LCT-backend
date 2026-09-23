"""Round-trip and arbitrary-depth tests for the facility/hierarchy schema."""
import pytest
from sqlalchemy import select

from src.db import async_session_factory
from src.models.hierarchy import Facility, HierarchyNode


@pytest.mark.asyncio
async def test_facility_and_hierarchy_node_round_trip() -> None:
    async with async_session_factory() as session:
        session.add(Facility(id="fac_test1", display_name="Test Facility", facility_type="controlHouse"))
        session.add(
            HierarchyNode(
                id="node_root_1",
                parent_id=None,
                facility_id="fac_test1",
                entity_type="facility",
                entity_id="fac_test1",
                display_name="Test Facility",
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        facility = (await session.execute(select(Facility).where(Facility.id == "fac_test1"))).scalar_one()
        assert facility.display_name == "Test Facility"
        node = (await session.execute(select(HierarchyNode).where(HierarchyNode.id == "node_root_1"))).scalar_one()
        assert node.parent_id is None
        assert node.facility_id == "fac_test1"


@pytest.mark.asyncio
async def test_hierarchy_supports_arbitrary_depth_not_hardcoded() -> None:
    """A 4-level chain (facility -> building -> collector -> section) round-trips."""
    async with async_session_factory() as session:
        session.add(Facility(id="fac_test2", display_name="Deep Facility", facility_type="controlHouse"))
        session.add(HierarchyNode(id="n1", parent_id=None, facility_id="fac_test2", entity_type="facility", entity_id="fac_test2", display_name="root"))
        session.add(HierarchyNode(id="n2", parent_id="n1", facility_id="fac_test2", entity_type="building", entity_id="b1", display_name="building"))
        session.add(HierarchyNode(id="n3", parent_id="n2", facility_id="fac_test2", entity_type="collector", entity_id="c1", display_name="collector"))
        session.add(HierarchyNode(id="n4", parent_id="n3", facility_id="fac_test2", entity_type="section", entity_id="s1", display_name="section"))
        await session.commit()

    async with async_session_factory() as session:
        # walk the chain manually to prove parent_id links are intact at any depth
        chain = []
        current_id = "n4"
        while current_id is not None:
            node = (await session.execute(select(HierarchyNode).where(HierarchyNode.id == current_id))).scalar_one()
            chain.append(node.entity_type)
            current_id = node.parent_id
        assert chain == ["section", "collector", "building", "facility"]
