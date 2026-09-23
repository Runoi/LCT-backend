"""Round-trip tests for the SensorChannel schema (ticket 05, leaf 1.1.1.1)."""
import pytest
from sqlalchemy import select

from src.db import async_session_factory
from src.models.hierarchy import Facility, HierarchyNode
from src.models.sensor import SensorChannel


@pytest.mark.asyncio
async def test_sensor_channel_round_trip_with_facility() -> None:
    async with async_session_factory() as session:
        session.add(Facility(id="fac_schema_test", display_name="Test", facility_type="controlHouse"))
        session.add(
            HierarchyNode(
                id="node_fac_schema_test", parent_id=None, facility_id="fac_schema_test",
                entity_type="facility", entity_id="fac_schema_test", display_name="Test",
            )
        )
        session.add(
            SensorChannel(
                id="sensor_1",
                channel_id="1",
                tag="15-11.1.1.1.",
                sensor_type_id="temperature_sensor",
                system_type="temperature",
                display_name="Датчик температуры 1",
                facility_id="fac_schema_test",
                hierarchy_node_id="node_fac_schema_test",
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        channel = (await session.execute(select(SensorChannel).where(SensorChannel.id == "sensor_1"))).scalar_one()
        assert channel.facility_id == "fac_schema_test"
        assert channel.sensor_type_id == "temperature_sensor"


@pytest.mark.asyncio
async def test_orphan_sensor_channel_has_null_facility_and_node() -> None:
    async with async_session_factory() as session:
        session.add(
            SensorChannel(
                id="sensor_orphan_1",
                channel_id="999999",
                tag="",
                sensor_type_id="unknown",
                system_type="unknown",
                display_name="Неизвестный канал 999999",
                facility_id=None,
                hierarchy_node_id=None,
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        orphan = (
            await session.execute(select(SensorChannel).where(SensorChannel.id == "sensor_orphan_1"))
        ).scalar_one()
        assert orphan.facility_id is None
        assert orphan.hierarchy_node_id is None
        assert orphan.sensor_type_id == "unknown"
