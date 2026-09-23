"""Tests for status_for_elapsed / sync_work_order_statuses (leaf 1.1.2)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.db import async_session_factory
from src.models.auth import User
from src.models.work_order import WorkOrder
from src.services.work_order_lifecycle import status_for_elapsed, sync_work_order_statuses


def test_status_for_elapsed_walks_the_full_chain_in_order() -> None:
    created_at = datetime(2046, 1, 1, tzinfo=timezone.utc)
    assert status_for_elapsed(created_at, created_at) == "draft"
    assert status_for_elapsed(created_at, created_at + timedelta(minutes=4)) == "draft"
    assert status_for_elapsed(created_at, created_at + timedelta(minutes=5)) == "ready"
    assert status_for_elapsed(created_at, created_at + timedelta(minutes=19)) == "ready"
    assert status_for_elapsed(created_at, created_at + timedelta(minutes=20)) == "assigned"
    assert status_for_elapsed(created_at, created_at + timedelta(minutes=49)) == "assigned"
    assert status_for_elapsed(created_at, created_at + timedelta(minutes=50)) == "in_progress"
    assert status_for_elapsed(created_at, created_at + timedelta(minutes=109)) == "in_progress"
    assert status_for_elapsed(created_at, created_at + timedelta(minutes=110)) == "completed"
    assert status_for_elapsed(created_at, created_at + timedelta(days=30)) == "completed"  # never regresses/overshoots


async def _seed_user(user_id: str) -> None:
    async with async_session_factory() as session:
        if await session.get(User, user_id) is None:
            session.add(User(id=user_id, username=user_id, password_hash="x", display_name=user_id, role="test"))
            await session.commit()


async def _insert(work_order_id: str, created_at: datetime, status: str) -> None:
    async with async_session_factory() as session:
        session.add(
            WorkOrder(
                id=work_order_id,
                display_number=f"ЗН-9999-{work_order_id}",
                source_risk_id=None,
                facility_id=None,
                target_entity_type="sensor",
                target_entity_id="sensor_lifecycle_test",
                work_type="inspection",
                priority="medium",
                due_at=created_at,
                description="test",
                comment=None,
                status=status,
                created_by="usr_wo_lifecycle_test",
                created_at=created_at,
                updated_at=created_at,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_sync_advances_eligible_rows_and_reports_the_changed_count() -> None:
    await _seed_user("usr_wo_lifecycle_test")
    created_at = datetime(2047, 1, 1, tzinfo=timezone.utc)
    await _insert("wo_lifecycle_sync_1", created_at, "draft")

    async with async_session_factory() as session:
        changed = await sync_work_order_statuses(session, now=created_at + timedelta(minutes=25))

    assert changed >= 1
    async with async_session_factory() as session:
        work_order = await session.get(WorkOrder, "wo_lifecycle_sync_1")
    assert work_order.status == "assigned"  # 25 min elapsed -> past the 20-min assigned threshold


@pytest.mark.asyncio
async def test_sync_never_touches_cancelled_or_integration_error() -> None:
    await _seed_user("usr_wo_lifecycle_test")
    created_at = datetime(2048, 1, 1, tzinfo=timezone.utc)
    await _insert("wo_lifecycle_cancelled", created_at, "cancelled")
    await _insert("wo_lifecycle_integration_error", created_at, "integration_error")

    async with async_session_factory() as session:
        await sync_work_order_statuses(session, now=created_at + timedelta(days=1))

    async with async_session_factory() as session:
        cancelled = await session.get(WorkOrder, "wo_lifecycle_cancelled")
        integration_error = await session.get(WorkOrder, "wo_lifecycle_integration_error")
    assert cancelled.status == "cancelled"
    assert integration_error.status == "integration_error"


@pytest.mark.asyncio
async def test_sync_leaves_completed_rows_unchanged() -> None:
    await _seed_user("usr_wo_lifecycle_test")
    created_at = datetime(2049, 1, 1, tzinfo=timezone.utc)
    await _insert("wo_lifecycle_completed", created_at, "completed")

    async with async_session_factory() as session:
        before = await session.get(WorkOrder, "wo_lifecycle_completed")
        before_updated_at = before.updated_at

    async with async_session_factory() as session:
        await sync_work_order_statuses(session, now=created_at + timedelta(days=1))

    async with async_session_factory() as session:
        after = await session.get(WorkOrder, "wo_lifecycle_completed")
    assert after.status == "completed"
    assert after.updated_at == before_updated_at
