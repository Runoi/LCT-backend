"""GET /api/v1/facilities/{facility_id}/layout."""
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from src.db import async_session_factory
from src.deps.auth import get_current_user
from src.errors import ApiError
from src.models.auth import User
from src.models.hierarchy import Facility
from src.services.layout import get_facility_layout
from src.services.scope import resolve_scope

router = APIRouter(prefix="/api/v1", tags=["layout"])


@router.get("/facilities/{facility_id}/layout")
async def get_layout(facility_id: str, user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Return the facility's schematic GeoJSON layout, enforcing scope.

    Args:
        facility_id: The facility whose layout to fetch.
        user: The authenticated caller, injected by get_current_user.

    Returns:
        A GeoJSON FeatureCollection.

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

        return await get_facility_layout(session, facility_id)
