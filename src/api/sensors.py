"""GET /api/v1/sensors -- scope-filtered, cursor-paginated sensor list."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from src.db import async_session_factory
from src.deps.auth import get_current_user
from src.models.auth import User
from src.schemas.sensor import SensorDetailOut, SensorListEnvelope, SensorListMeta
from src.services.scope import resolve_scope
from src.services.sensor_query import get_sensor_detail, list_sensors

router = APIRouter(prefix="/api/v1", tags=["sensors"])


@router.get("/sensors", response_model=SensorListEnvelope)
async def get_sensors(
    facility_id: str | None = Query(default=None),
    hierarchy_node_id: str | None = Query(default=None),
    type: str | None = Query(default=None),
    current_state: str | None = Query(default=None),
    risk_level: str | None = Query(default=None),
    query: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
) -> SensorListEnvelope:
    """List sensors within the caller's scope.

    Args:
        facility_id: Optional exact facility filter.
        hierarchy_node_id: Optional exact hierarchy node filter.
        type: Optional exact sensor_type_id filter.
        current_state: Accepted for contract completeness; no real
            current_state data yet (see src/schemas/sensor.py).
        risk_level: Accepted for contract completeness; same caveat.
        query: Optional case-insensitive substring match.
        cursor: Opaque pagination cursor.
        limit: Page size, 1-200.
        user: The authenticated caller, injected by get_current_user.

    Returns:
        A SensorListEnvelope containing only sensors the caller may see.
    """
    del current_state, risk_level  # accepted per contract; not yet meaningful

    async with async_session_factory() as session:
        scope = await resolve_scope(session, user.id)
        allowed_ids = None if scope["type"] == "all_facilities" else set(scope["facility_ids"])

        items, next_cursor, total = await list_sensors(
            session,
            allowed_facility_ids=allowed_ids,
            facility_id=facility_id,
            hierarchy_node_id=hierarchy_node_id,
            sensor_type=type,
            query=query,
            cursor=cursor,
            limit=limit,
        )

    return SensorListEnvelope(
        data=items,
        meta=SensorListMeta(next_cursor=next_cursor, total=total, generated_at=datetime.now(timezone.utc)),
    )


@router.get("/sensors/{sensor_id}", response_model=SensorDetailOut)
async def get_sensor(sensor_id: str, user: User = Depends(get_current_user)) -> SensorDetailOut:
    """Fetch one sensor's detail card, enforcing the caller's scope.

    Args:
        sensor_id: The requested sensor id.
        user: The authenticated caller, injected by get_current_user.

    Returns:
        The sensor's full detail card.

    Raises:
        ApiError: 404 if the sensor does not exist; 403 if it exists but is
            outside scope (orphans are out of scope for anyone restricted).
    """
    async with async_session_factory() as session:
        scope = await resolve_scope(session, user.id)
        allowed_ids = None if scope["type"] == "all_facilities" else set(scope["facility_ids"])
        return await get_sensor_detail(session, sensor_id, allowed_ids)
