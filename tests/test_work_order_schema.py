"""Round-trip tests for WorkOrder (leaf 1.1.1)."""
from datetime import datetime, timezone

import pytest

from src.db import async_session_factory
from src.models.auth import User
from src.models.work_order import WorkOrder


async def _seed_user(user_id: str) -> None:
    async with async_session_factory() as session:
        if await session.get(User, user_id) is None:
            session.add(User(id=user_id, username=user_id, password_hash="x", display_name=user_id, role="test"))
            await session.commit()


@pytest.mark.asyncio
async def test_round_trip_with_nullable_source_risk_and_comment() -> None:
    await _seed_user("usr_wo_schema_test")
    now = datetime(2043, 1, 1, tzinfo=timezone.utc)

    async with async_session_factory() as session:
        session.add(
            WorkOrder(
                id="wo_schema_test_1",
                display_number="ЗН-2043-0001",
                source_risk_id=None,
                facility_id=None,
                target_entity_type="sensor",
                target_entity_id="sensor_schema_test",
                work_type="inspection",
                priority="medium",
                due_at=now,
                description="test description",
                comment=None,
                status="draft",
                created_by="usr_wo_schema_test",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        work_order = await session.get(WorkOrder, "wo_schema_test_1")
    assert work_order.source_risk_id is None
    assert work_order.comment is None
    assert work_order.status == "draft"
    assert work_order.display_number == "ЗН-2043-0001"
