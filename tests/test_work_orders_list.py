"""Tests for GET /api/v1/work-orders (leaf 1.2.2)."""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from src.db import async_session_factory
from src.main import app
from src.models.auth import User
from src.models.work_order import WorkOrder
from src.services.demo_seed import seed_demo_users
from src.services.facility_seed import seed_facility_catalogue


async def _seed_all() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_demo_users(session)


async def _seed_user(user_id: str) -> None:
    async with async_session_factory() as session:
        if await session.get(User, user_id) is None:
            session.add(User(id=user_id, username=user_id, password_hash="x", display_name=user_id, role="test"))
            await session.commit()


async def _insert(
    work_order_id: str,
    facility_id: str | None,
    created_at: datetime,
    *,
    status: str = "draft",
    work_type: str = "inspection",
) -> None:
    await _seed_user("usr_wo_list_test")
    async with async_session_factory() as session:
        session.add(
            WorkOrder(
                id=work_order_id,
                display_number=f"ЗН-9998-{work_order_id}",
                source_risk_id=None,
                facility_id=facility_id,
                target_entity_type="sensor",
                target_entity_id=f"sensor_{work_order_id}",
                work_type=work_type,
                priority="medium",
                due_at=created_at,
                description="test",
                comment=None,
                status=status,
                created_by="usr_wo_list_test",
                created_at=created_at,
                updated_at=created_at,
            )
        )
        await session.commit()


async def _login(username: str, password: str) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["token"]


async def _get(token: str | None, **params):
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/v1/work-orders", headers=headers, params=params)


@pytest.mark.asyncio
async def test_orphan_facility_work_order_excluded_for_restricted_scope() -> None:
    await _seed_all()
    now = datetime(2052, 1, 1, tzinfo=timezone.utc)
    await _insert("wo_list_orphan", None, now)

    manager_token = await _login("manager", "manager123")
    manager_response = await _get(manager_token)
    assert "wo_list_orphan" in {wo["id"] for wo in manager_response.json()["data"]}

    dispatcher_token = await _login("dispatcher", "dispatcher123")
    dispatcher_response = await _get(dispatcher_token)
    assert "wo_list_orphan" not in {wo["id"] for wo in dispatcher_response.json()["data"]}


@pytest.mark.asyncio
async def test_facility_status_and_work_type_filters_narrow_correctly() -> None:
    await _seed_all()
    now = datetime(2053, 1, 1, tzinfo=timezone.utc)
    await _insert("wo_list_filter_a", "fac_5122", now, status="draft", work_type="inspection")
    await _insert("wo_list_filter_b", "fac_5122", now, status="cancelled", work_type="repair")

    token = await _login("manager", "manager123")

    def _mine(body: dict) -> set[str]:
        return {wo["id"] for wo in body["data"] if wo["id"].startswith("wo_list_filter_")}

    by_status = await _get(token, facility_id="fac_5122", status="cancelled")
    assert _mine(by_status.json()) == {"wo_list_filter_b"}

    by_work_type = await _get(token, facility_id="fac_5122", work_type="inspection")
    assert _mine(by_work_type.json()) == {"wo_list_filter_a"}


@pytest.mark.asyncio
async def test_stale_draft_shows_auto_advanced_status_on_read() -> None:
    await _seed_all()
    old_created_at = datetime.now(timezone.utc) - timedelta(hours=3)
    await _insert("wo_list_stale_draft", "fac_5122", old_created_at, status="draft")

    token = await _login("manager", "manager123")
    response = await _get(token, facility_id="fac_5122")
    item = next(wo for wo in response.json()["data"] if wo["id"] == "wo_list_stale_draft")
    assert item["status"] == "completed"  # 3 hours >> the 110-minute completion threshold


@pytest.mark.asyncio
async def test_work_orders_requires_authentication() -> None:
    response = await _get(None)
    assert response.status_code == 401
