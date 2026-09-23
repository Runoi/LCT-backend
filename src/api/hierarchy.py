"""GET /api/v1/facilities/{facility_id}/hierarchy."""
from fastapi import APIRouter, Depends
from sqlalchemy import select

from src.db import async_session_factory
from src.deps.auth import get_current_user
from src.errors import ApiError
from src.models.auth import User
from src.models.hierarchy import Facility
from src.schemas.hierarchy import HierarchyNodeOut
from src.services.hierarchy_query import get_facility_hierarchy
from src.services.scope import resolve_scope

router = APIRouter(prefix="/api/v1", tags=["hierarchy"])


@router.get("/facilities/{facility_id}/hierarchy", response_model=list[HierarchyNodeOut])
async def get_hierarchy(facility_id: str, user: User = Depends(get_current_user)) -> list[HierarchyNodeOut]:
    """Return every node in a facility's tree, enforcing the caller's scope.

    Args:
        facility_id: The facility whose tree to fetch.
        user: The authenticated caller, injected by get_current_user.

    Returns:
        The full node list (empty if the facility has no nodes yet).

    Raises:
        ApiError: 404 if the facility does not exist; 403 if it exists but
            is outside the caller's scope.
    """
    async with async_session_factory() as session:
        facility = (await session.execute(select(Facility).where(Facility.id == facility_id))).scalar_one_or_none()
        if facility is None:
            raise ApiError(404, "NOT_FOUND", "Объект не найден")

        scope = await resolve_scope(session, user.id)
        if scope["type"] != "all_facilities" and facility_id not in scope["facility_ids"]:
            raise ApiError(403, "FACILITY_ACCESS_DENIED", "Недостаточно прав для просмотра объекта")

        return await get_facility_hierarchy(session, facility_id)
