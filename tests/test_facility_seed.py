"""Tests for the facility catalogue seed loader.

Assertions here count rows matching the catalogue's own known ids, not
raw table totals -- other test files legitimately insert their own
ad-hoc District/Facility fixtures into the same shared database when the
whole suite runs together in one process (see tests/test_me.py), so a
bare `SELECT count(*)` would be a test-isolation bug, not a real check.
"""
import csv
from pathlib import Path

import pytest
from sqlalchemy import func, select

from src.db import async_session_factory
from src.models.auth import District
from src.models.hierarchy import Facility, HierarchyNode
from src.services.facility_seed import DEFAULT_CSV_PATH, seed_facility_catalogue

FIXTURE_WITH_QUOTED_NEWLINE = Path(__file__).parent / "fixtures" / "quoted_newline_facilities.csv"


def _expected_ids_from_real_catalogue() -> tuple[set[str], set[str]]:
    with open(DEFAULT_CSV_PATH, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    facility_ids = {f"fac_{r['ид_объект']}" for r in rows if r["иерархия_уровень"] == "3"}
    district_ids = {f"dist_{r['ид_объект']}" for r in rows if r["иерархия_уровень"] == "2"}
    return facility_ids, district_ids


@pytest.mark.asyncio
async def test_real_catalogue_seeds_78_facilities_and_16_districts() -> None:
    expected_facility_ids, expected_district_ids = _expected_ids_from_real_catalogue()
    assert len(expected_facility_ids) == 78
    assert len(expected_district_ids) == 16

    async with async_session_factory() as session:
        await seed_facility_catalogue(session)

    async with async_session_factory() as session:
        seeded_facility_ids = set(
            (await session.execute(select(Facility.id).where(Facility.id.in_(expected_facility_ids))))
            .scalars()
            .all()
        )
        seeded_district_ids = set(
            (await session.execute(select(District.id).where(District.id.in_(expected_district_ids))))
            .scalars()
            .all()
        )
        assert seeded_facility_ids == expected_facility_ids
        assert seeded_district_ids == expected_district_ids

        # every catalogue facility's district_id must reference a real district (0 orphans)
        facility_district_ids = set(
            (
                await session.execute(
                    select(Facility.district_id).where(Facility.id.in_(expected_facility_ids))
                )
            )
            .scalars()
            .all()
        )
        all_district_ids = set((await session.execute(select(District.id))).scalars().all())
        assert facility_district_ids <= all_district_ids

        # every catalogue facility has exactly one root hierarchy node
        # (filtered to parent_id IS NULL: other tests legitimately add child
        # nodes under an existing root, which must not break this count)
        root_node_count = (
            await session.execute(
                select(func.count())
                .select_from(HierarchyNode)
                .where(HierarchyNode.facility_id.in_(expected_facility_ids), HierarchyNode.parent_id.is_(None))
            )
        ).scalar_one()
        assert root_node_count == 78


@pytest.mark.asyncio
async def test_known_facility_ids_from_the_dataset_sample_exist() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)

    async with async_session_factory() as session:
        # fac_5122 and fac_5339 are the ids the ticket-03 demo dispatcher scope assumes exist
        for facility_id in ("fac_5122", "fac_5339"):
            facility = (await session.execute(select(Facility).where(Facility.id == facility_id))).scalar_one()
            assert facility.facility_type in ("controlHouse", "guardObject")


@pytest.mark.asyncio
async def test_seed_is_idempotent() -> None:
    expected_facility_ids, _ = _expected_ids_from_real_catalogue()

    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_facility_catalogue(session)  # second call must be a no-op

    async with async_session_factory() as session:
        facility_count = (
            await session.execute(
                select(func.count()).select_from(Facility).where(Facility.id.in_(expected_facility_ids))
            )
        ).scalar_one()
        assert facility_count == 78  # not doubled by the second call


@pytest.mark.asyncio
async def test_real_csv_parser_handles_a_quoted_embedded_newline() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session, csv_path=FIXTURE_WITH_QUOTED_NEWLINE)

    async with async_session_factory() as session:
        # a naive line-split parser would misparse the embedded newline and either
        # miscount rows or split the multiline field into a broken extra row
        multiline = (await session.execute(select(Facility).where(Facility.id == "fac_90002"))).scalar_one()
        assert multiline.display_name == "Объект с\nпереносом строки"
        plain = (await session.execute(select(Facility).where(Facility.id == "fac_90003"))).scalar_one()
        assert plain.display_name == "Обычный объект"
