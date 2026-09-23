"""Tests for POST /api/v1/work-orders (leaf 1.2.1)."""
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from src.db import async_session_factory
from src.main import app
from src.models.auth import User, UserPermission, UserScope
from src.services.auth_service import hash_password
from src.services.demo_seed import seed_demo_users
from src.services.facility_seed import seed_facility_catalogue


async def _seed_all() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_demo_users(session)


async def _seed_custom_user(user_id: str, permissions: list[str]) -> None:
    async with async_session_factory() as session:
        if await session.get(User, user_id) is not None:
            return
        session.add(
            User(id=user_id, username=user_id, password_hash=hash_password("password123"), display_name=user_id, role="test")
        )
        for permission in permissions:
            session.add(UserPermission(user_id=user_id, permission=permission))
        session.add(UserScope(user_id=user_id, scope_type="all_facilities"))
        await session.commit()


async def _login(username: str, password: str) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["token"]


def _valid_body(**overrides) -> dict:
    body = {
        "mode": "draft",
        "source_risk_id": None,
        "facility_id": "fac_5122",
        "target_entity_type": "sensor",
        "target_entity_id": "sensor_test",
        "work_type": "inspection",
        "priority": "medium",
        "due_at": datetime(2051, 1, 1, tzinfo=timezone.utc).isoformat(),
        "description": "test description",
        "comment": None,
    }
    body.update(overrides)
    return body


async def _create(token: str, body: dict):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/api/v1/work-orders", headers={"Authorization": f"Bearer {token}"}, json=body)


@pytest.mark.asyncio
async def test_valid_draft_creates_work_order_with_number_and_audit_metadata() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _create(token, _valid_body())
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    assert body["display_number"].startswith("ЗН-")
    assert body["created_by"]
    assert body["created_at"]
    assert body["version"] == 1


@pytest.mark.asyncio
async def test_mode_other_than_draft_is_422() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _create(token, _valid_body(mode="submitted"))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unknown_work_type_is_422() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _create(token, _valid_body(work_type="not_a_real_work_type"))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unknown_priority_is_422() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _create(token, _valid_body(priority="not_a_real_priority"))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unknown_target_entity_type_is_422() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _create(token, _valid_body(target_entity_type="not_a_real_type"))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_out_of_scope_facility_is_403() -> None:
    await _seed_all()
    token = await _login("dispatcher", "dispatcher123")
    response = await _create(token, _valid_body(facility_id="fac_20"))  # not assigned to dispatcher
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_caller_with_only_submit_permission_can_still_create() -> None:
    await _seed_all()
    await _seed_custom_user("usr_wo_submit_only", ["work_order.submit"])
    token = await _login("usr_wo_submit_only", "password123")
    response = await _create(token, _valid_body())
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_caller_with_neither_permission_gets_403() -> None:
    await _seed_all()
    await _seed_custom_user("usr_wo_no_permission", ["facility.read.all"])
    token = await _login("usr_wo_no_permission", "password123")
    response = await _create(token, _valid_body())
    assert response.status_code == 403
