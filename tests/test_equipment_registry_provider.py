"""Tests for the synthetic equipment registry provider (leaf 1.2.2)."""
import pytest
from sqlalchemy import func, select

from src.db import async_session_factory
from src.models.emulation_providers import EquipmentRegistryItem, SyntheticProviderRun
from src.models.hierarchy import Facility
from src.models.sensor import SensorChannel
from src.services.equipment_registry_provider import PROVIDER, generate_equipment_registry


async def _reset_provider_run() -> None:
    async with async_session_factory() as session:
        existing = await session.get(SyntheticProviderRun, PROVIDER)
        if existing is not None:
            await session.delete(existing)
        await session.execute(EquipmentRegistryItem.__table__.delete())
        await session.commit()


async def _seed_test_catalogue() -> str:
    """One dedicated, non-catalogue facility with channels in 2 systems."""
    facility_id = "fac_equip_test"
    async with async_session_factory() as session:
        if await session.get(Facility, facility_id) is None:
            session.add(Facility(id=facility_id, display_name=facility_id, facility_type="test", district_id=None))
        for i, system_type in enumerate(["temperature", "temperature", "security"]):
            channel_id = f"equip_test_channel_{i}"
            if await session.get(SensorChannel, f"sensor_{channel_id}") is None:
                session.add(
                    SensorChannel(
                        id=f"sensor_{channel_id}",
                        channel_id=channel_id,
                        tag="",
                        sensor_type_id="temperature_sensor" if system_type == "temperature" else "door_contact",
                        system_type=system_type,
                        display_name=channel_id,
                        facility_id=facility_id,
                        hierarchy_node_id=None,
                    )
                )
        await session.commit()
    return facility_id


@pytest.mark.asyncio
async def test_one_item_per_real_facility_system_type_pair() -> None:
    await _reset_provider_run()
    facility_id = await _seed_test_catalogue()

    async with async_session_factory() as session:
        count = await generate_equipment_registry(session)
    assert count > 0

    async with async_session_factory() as session:
        items = (
            await session.execute(select(EquipmentRegistryItem).where(EquipmentRegistryItem.facility_id == facility_id))
        ).scalars().all()
    by_system = {item.system_type: item.channel_count for item in items}
    assert by_system == {"temperature": 2, "security": 1}


@pytest.mark.asyncio
async def test_generation_is_idempotent() -> None:
    await _reset_provider_run()
    await _seed_test_catalogue()
    async with async_session_factory() as session:
        first_count = await generate_equipment_registry(session)
    async with async_session_factory() as session:
        second_count = await generate_equipment_registry(session)
    assert first_count > 0
    assert second_count == 0


@pytest.mark.asyncio
async def test_install_year_is_fully_deterministic_across_runs() -> None:
    facility_id = await _seed_test_catalogue()

    await _reset_provider_run()
    async with async_session_factory() as session:
        await generate_equipment_registry(session)
    async with async_session_factory() as session:
        first_years = dict(
            (
                await session.execute(
                    select(EquipmentRegistryItem.system_type, EquipmentRegistryItem.install_year).where(
                        EquipmentRegistryItem.facility_id == facility_id
                    )
                )
            ).all()
        )

    await _reset_provider_run()
    async with async_session_factory() as session:
        await generate_equipment_registry(session)
    async with async_session_factory() as session:
        second_years = dict(
            (
                await session.execute(
                    select(EquipmentRegistryItem.system_type, EquipmentRegistryItem.install_year).where(
                        EquipmentRegistryItem.facility_id == facility_id
                    )
                )
            ).all()
        )

    assert first_years == second_years
