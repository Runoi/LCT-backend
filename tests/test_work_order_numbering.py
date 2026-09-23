"""Tests for generate_display_number (leaf 1.1.1).

Uses dedicated years (2044/2045) untouched by any other test file, since
the sequence counter is a real global COUNT(*) over the whole shared table
for a given year -- any other test creating a work order in the same year
would make an exact-number assertion flaky.
"""
from datetime import datetime, timezone

import pytest

from src.db import async_session_factory
from src.models.auth import User
from src.models.work_order import WorkOrder
from src.services.work_order_numbering import generate_display_number


async def _seed_user(user_id: str) -> None:
    async with async_session_factory() as session:
        if await session.get(User, user_id) is None:
            session.add(User(id=user_id, username=user_id, password_hash="x", display_name=user_id, role="test"))
            await session.commit()


async def _insert(work_order_id: str, display_number: str, created_at: datetime) -> None:
    async with async_session_factory() as session:
        session.add(
            WorkOrder(
                id=work_order_id,
                display_number=display_number,
                source_risk_id=None,
                facility_id=None,
                target_entity_type="sensor",
                target_entity_id="sensor_numbering_test",
                work_type="inspection",
                priority="medium",
                due_at=created_at,
                description="test",
                comment=None,
                status="draft",
                created_by="usr_wo_numbering_test",
                created_at=created_at,
                updated_at=created_at,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_display_numbers_are_sequential_within_a_year() -> None:
    await _seed_user("usr_wo_numbering_test")
    year = datetime(2044, 6, 1, tzinfo=timezone.utc)

    async with async_session_factory() as session:
        first = await generate_display_number(session, now=year)
    assert first == "ЗН-2044-0001"
    await _insert("wo_numbering_1", first, year)

    async with async_session_factory() as session:
        second = await generate_display_number(session, now=year)
    assert second == "ЗН-2044-0002"
    await _insert("wo_numbering_2", second, year)

    async with async_session_factory() as session:
        third = await generate_display_number(session, now=year)
    assert third == "ЗН-2044-0003"


@pytest.mark.asyncio
async def test_different_year_starts_a_fresh_sequence() -> None:
    await _seed_user("usr_wo_numbering_test")
    # 2044 already has entries from the previous test (module-level ordering
    # within this file is guaranteed; both tests share year isolation from
    # every OTHER test file, which is what actually matters here).
    async with async_session_factory() as session:
        number = await generate_display_number(session, now=datetime(2045, 6, 1, tzinfo=timezone.utc))
    assert number == "ЗН-2045-0001"
