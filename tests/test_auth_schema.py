"""Round-trip tests for the auth/RBAC schema (ticket 03, leaf 1.1.1.1)."""
import pytest
from sqlalchemy import select

from src.db import async_session_factory
from src.models.auth import (
    District,
    DistrictFacility,
    User,
    UserPermission,
    UserScope,
    UserScopeDistrict,
    UserScopeFacility,
    UserSession,
)
from src.services.permissions import PERMISSIONS


@pytest.mark.asyncio
async def test_auth_schema_round_trip() -> None:
    async with async_session_factory() as session:
        district = District(id="dist_1", name="Test District")
        session.add(district)
        session.add(DistrictFacility(district_id="dist_1", facility_id="fac_1"))

        user = User(
            id="usr_1",
            username="tester",
            password_hash="hashed",
            display_name="Test User",
            role="Диспетчер",
        )
        session.add(user)
        session.add(UserPermission(user_id="usr_1", permission="sensor.read"))
        session.add(UserScope(user_id="usr_1", scope_type="assigned_facilities"))
        session.add(UserScopeFacility(user_id="usr_1", facility_id="fac_1"))
        session.add(UserScopeDistrict(user_id="usr_1", district_id="dist_1"))
        session.add(UserSession(token="tok_1", user_id="usr_1"))
        await session.commit()

    async with async_session_factory() as session:
        fetched_user = (await session.execute(select(User).where(User.id == "usr_1"))).scalar_one()
        assert fetched_user.username == "tester"

        perms = (
            await session.execute(select(UserPermission).where(UserPermission.user_id == "usr_1"))
        ).scalars().all()
        assert {p.permission for p in perms} == {"sensor.read"}

        scope = (await session.execute(select(UserScope).where(UserScope.user_id == "usr_1"))).scalar_one()
        assert scope.scope_type == "assigned_facilities"

        district_facilities = (
            await session.execute(select(DistrictFacility).where(DistrictFacility.district_id == "dist_1"))
        ).scalars().all()
        assert {df.facility_id for df in district_facilities} == {"fac_1"}

        session_row = (
            await session.execute(select(UserSession).where(UserSession.token == "tok_1"))
        ).scalar_one()
        assert session_row.revoked_at is None


def test_permissions_catalogue_is_nonempty() -> None:
    assert len(PERMISSIONS) == 12
    assert "facility.read.all" in PERMISSIONS
