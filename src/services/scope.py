"""Resolve a user's scope (all_facilities, or assigned + district-expanded)."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.auth import (
    DistrictFacility,
    UserPermission,
    UserScope,
    UserScopeDistrict,
    UserScopeFacility,
)


async def resolve_scope(session: AsyncSession, user_id: str) -> dict:
    """Resolve a user's scope to the API contract shape.

    Args:
        session: An active async database session.
        user_id: The id of the user to resolve scope for.

    Returns:
        {"type": "all_facilities"} or
        {"type": "assigned_facilities", "facility_ids": [...]} where the
        facility_ids are the union of directly-assigned facilities and
        every facility belonging to an assigned district, deduplicated.
    """
    user_scope = (
        await session.execute(select(UserScope).where(UserScope.user_id == user_id))
    ).scalar_one_or_none()

    if user_scope is None or user_scope.scope_type == "all_facilities":
        return {"type": "all_facilities"}

    direct_ids = (
        await session.execute(select(UserScopeFacility.facility_id).where(UserScopeFacility.user_id == user_id))
    ).scalars().all()

    district_ids = (
        await session.execute(select(UserScopeDistrict.district_id).where(UserScopeDistrict.user_id == user_id))
    ).scalars().all()

    expanded_ids: list[str] = []
    if district_ids:
        expanded_ids = (
            await session.execute(
                select(DistrictFacility.facility_id).where(DistrictFacility.district_id.in_(district_ids))
            )
        ).scalars().all()

    facility_ids = sorted(set(direct_ids) | set(expanded_ids))
    return {"type": "assigned_facilities", "facility_ids": facility_ids}


async def resolve_permissions(session: AsyncSession, user_id: str) -> list[str]:
    """Resolve the sorted list of permission strings granted to a user.

    Args:
        session: An active async database session.
        user_id: The id of the user to resolve permissions for.

    Returns:
        A sorted list of permission strings.
    """
    permissions = (
        await session.execute(select(UserPermission.permission).where(UserPermission.user_id == user_id))
    ).scalars().all()
    return sorted(permissions)
