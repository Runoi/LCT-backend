"""Tests for the sensor channel catalogue seed loader."""
import csv
from pathlib import Path

import pytest
from sqlalchemy import select

from src.db import async_session_factory
from src.models.hierarchy import Facility, HierarchyNode
from src.models.sensor import SensorChannel
from src.services.facility_seed import seed_facility_catalogue
from src.services.sensor_channel_seed import DEFAULT_CSV_PATH, seed_sensor_channel_catalogue

FIXTURE_QUOTED = Path(__file__).parent / "fixtures" / "quoted_channel_catalogue.csv"


def _expected_channel_ids_from_real_catalogue() -> set[str]:
    with open(DEFAULT_CSV_PATH, encoding="utf-8-sig", newline="") as f:
        return {r["ид_канала_данных"] for r in csv.DictReader(f)}


@pytest.mark.asyncio
async def test_real_catalogue_seeds_all_channels_with_correct_type_and_facility() -> None:
    expected_ids = _expected_channel_ids_from_real_catalogue()
    assert len(expected_ids) == 11485

    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_sensor_channel_catalogue(session)

    async with async_session_factory() as session:
        seeded_ids = set(
            (await session.execute(select(SensorChannel.channel_id).where(SensorChannel.channel_id.in_(expected_ids))))
            .scalars()
            .all()
        )
        assert seeded_ids == expected_ids

        sample = (
            await session.execute(select(SensorChannel).where(SensorChannel.channel_id == "120578"))
        ).scalar_one()
        assert sample.sensor_type_id == "av_contact"  # "КД АВ"
        assert sample.facility_id == "fac_20"
        assert sample.hierarchy_node_id is not None

        node = (
            await session.execute(select(HierarchyNode).where(HierarchyNode.id == sample.hierarchy_node_id))
        ).scalar_one()
        assert node.parent_id == "node_fac_20"
        assert node.entity_type == "sensor"


@pytest.mark.asyncio
async def test_seed_is_idempotent() -> None:
    expected_ids = _expected_channel_ids_from_real_catalogue()
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_sensor_channel_catalogue(session)
        await seed_sensor_channel_catalogue(session)  # second call must be a no-op

    async with async_session_factory() as session:
        count = (
            await session.execute(select(SensorChannel).where(SensorChannel.channel_id.in_(expected_ids)))
        ).scalars().all()
        assert len(count) == 11485


@pytest.mark.asyncio
async def test_quoted_fixture_parses_multiline_names_and_orphans_unknown_type_or_facility() -> None:
    async with async_session_factory() as session:
        session.add(Facility(id="fac_90001", display_name="Fixture Facility", facility_type="controlHouse"))
        session.add(
            HierarchyNode(
                id="node_fac_90001", parent_id=None, facility_id="fac_90001",
                entity_type="facility", entity_id="fac_90001", display_name="Fixture Facility",
            )
        )
        await session.commit()
        await seed_sensor_channel_catalogue(session, csv_path=FIXTURE_QUOTED)

    async with async_session_factory() as session:
        multiline = (
            await session.execute(select(SensorChannel).where(SensorChannel.channel_id == "900002"))
        ).scalar_one()
        assert multiline.display_name == "Датчик с\nпереносом строки"
        assert multiline.facility_id == "fac_90001"

        with_comma = (
            await session.execute(select(SensorChannel).where(SensorChannel.channel_id == "900001"))
        ).scalar_one()
        assert with_comma.display_name == "Темп. ВШ ПК88,5"

        unknown_type = (
            await session.execute(select(SensorChannel).where(SensorChannel.channel_id == "900003"))
        ).scalar_one()
        assert unknown_type.sensor_type_id == "unknown"
        assert unknown_type.facility_id is None

        unknown_facility = (
            await session.execute(select(SensorChannel).where(SensorChannel.channel_id == "900004"))
        ).scalar_one()
        assert unknown_facility.facility_id is None
        assert unknown_facility.hierarchy_node_id is None
