"""GET /api/v1/facilities — scope-filtered, cursor-paginated facility list."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from src.db import async_session_factory
from src.deps.auth import get_current_user
from src.models.auth import User
from src.schemas.facility import FacilityListEnvelope, FacilityListMeta, FacilityOut
from src.services.facility_query import get_facility_detail, list_facilities
from src.services.scope import resolve_scope

router = APIRouter(prefix="/api/v1", tags=["facilities"])


@router.get("/facilities", response_model=FacilityListEnvelope)
async def get_facilities(
    query: str | None = Query(default=None),
    current_state: str | None = Query(default=None),
    risk_level: str | None = Query(default=None),
    district: str | None = Query(default=None),
    bbox: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
) -> FacilityListEnvelope:
    """List facilities within the caller's scope.

    Args:
        query: Optional case-insensitive substring match on display_name.
        current_state: Accepted for contract completeness (see facility_query).
        risk_level: Accepted for contract completeness (see facility_query).
        district: Optional district_id filter.
        bbox: Optional "min_lon,min_lat,max_lon,max_lat" filter.
        cursor: Opaque pagination cursor.
        limit: Page size, 1-200.
        user: The authenticated caller, injected by get_current_user.

    Returns:
        A FacilityListEnvelope containing only facilities the caller may see.
    """
    async with async_session_factory() as session:
        scope = await resolve_scope(session, user.id)
        allowed_ids = None if scope["type"] == "all_facilities" else set(scope["facility_ids"])

        items, next_cursor, total = await list_facilities(
            session,
            allowed_facility_ids=allowed_ids,
            query=query,
            current_state=current_state,
            risk_level=risk_level,
            district=district,
            bbox=bbox,
            cursor=cursor,
            limit=limit,
        )

    return FacilityListEnvelope(
        data=items,
        meta=FacilityListMeta(next_cursor=next_cursor, total=total, generated_at=datetime.now(timezone.utc)),
    )


@router.get("/facilities/{facility_id}", response_model=FacilityOut)
async def get_facility(facility_id: str, user: User = Depends(get_current_user)) -> FacilityOut:
    """Fetch one facility's detail, enforcing the caller's scope.

    Args:
        facility_id: The requested facility id.
        user: The authenticated caller, injected by get_current_user.

    Returns:
        The facility's full detail (same shape as a list item).

    Raises:
        ApiError: 403 if the facility exists but is out of scope; 404 if
            it does not exist.
    """
    async with async_session_factory() as session:
        scope = await resolve_scope(session, user.id)
        allowed_ids = None if scope["type"] == "all_facilities" else set(scope["facility_ids"])
        return await get_facility_detail(session, facility_id, allowed_ids)
