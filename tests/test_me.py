"""Tests for GET /api/v1/me."""
import pytest
from httpx import ASGITransport, AsyncClient

from src.db import async_session_factory
from src.main import app
from src.models.auth import (
    District,
    DistrictFacility,
    User,
    UserPermission,
    UserScope,
    UserScopeDistrict,
    UserScopeFacility,
)
from src.services.auth_service import create_session
from src.services.demo_seed import seed_demo_users
from src.services.permissions import PERMISSIONS


async def _login(username: str, password: str) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["token"]


async def _get_me(token: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})


@pytest.mark.asyncio
async def test_manager_sees_all_facilities_and_full_permission_set() -> None:
    async with async_session_factory() as session:
        await seed_demo_users(session)
    token = await _login("manager", "manager123")

    response = await _get_me(token)
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "Руководитель"
    assert body["scope"] == {"type": "all_facilities"}  # facility_ids omitted for all_facilities
    assert body["permissions"] == sorted(PERMISSIONS)
    assert body["timezone"] == "Europe/Moscow"
    assert body["locale"] == "ru"


@pytest.mark.asyncio
async def test_dispatcher_sees_direct_and_district_expanded_facility_ids() -> None:
    async with async_session_factory() as session:
        await seed_demo_users(session)
    token = await _login("dispatcher", "dispatcher123")

    response = await _get_me(token)
    assert response.status_code == 200
    body = response.json()
    assert body["scope"]["type"] == "assigned_facilities"
    assert set(body["scope"]["facility_ids"]) == {"fac_5122", "fac_5339"}


@pytest.mark.asyncio
async def test_district_assignment_expands_to_member_facility_ids() -> None:
    async with async_session_factory() as session:
        session.add(District(id="dist_test", name="Test District"))
        session.add(DistrictFacility(district_id="dist_test", facility_id="fac_from_district"))
        session.add(
            User(id="usr_district_scoped", username="district_user", password_hash="x", display_name="D", role="Диспетчер района")
        )
        session.add(UserPermission(user_id="usr_district_scoped", permission="facility.read.assigned"))
        session.add(UserScope(user_id="usr_district_scoped", scope_type="assigned_facilities"))
        session.add(UserScopeDistrict(user_id="usr_district_scoped", district_id="dist_test"))
        await session.commit()
        token = await create_session(session, "usr_district_scoped")

    response = await _get_me(token)
    assert response.status_code == 200
    assert response.json()["scope"]["facility_ids"] == ["fac_from_district"]


@pytest.mark.asyncio
async def test_user_with_no_accessible_facilities_gets_200_with_empty_list() -> None:
    async with async_session_factory() as session:
        session.add(
            User(id="usr_no_access", username="no_access", password_hash="x", display_name="N", role="Диспетчер")
        )
        session.add(UserScope(user_id="usr_no_access", scope_type="assigned_facilities"))
        await session.commit()
        token = await create_session(session, "usr_no_access")

    response = await _get_me(token)
    assert response.status_code == 200
    assert response.json()["scope"] == {"type": "assigned_facilities", "facility_ids": []}


@pytest.mark.asyncio
async def test_me_without_token_returns_401() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"


@pytest.mark.asyncio
async def test_scope_facility_ids_are_never_leaked_across_users() -> None:
    async with async_session_factory() as session:
        await seed_demo_users(session)
    token = await _login("dispatcher", "dispatcher123")
    response = await _get_me(token)
    facility_ids = response.json()["scope"]["facility_ids"]
    assert "fac_from_district" not in facility_ids
