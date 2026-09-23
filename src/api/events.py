"""GET /api/v1/events -- scope-filtered, keyset-paginated event/incident journal."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from src.db import async_session_factory
from src.deps.auth import get_current_user
from src.errors import ApiError
from src.models.auth import User
from src.schemas.event import EventListEnvelope, EventListMeta, EventOut
from src.services.event_query import list_events
from src.services.event_sync import sync_events
from src.services.scope import resolve_scope

router = APIRouter(prefix="/api/v1", tags=["events"])


def _parse_iso_datetime(raw: str, field_name: str) -> datetime:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(400, "VALIDATION_ERROR", f"{field_name} must be an ISO 8601 datetime") from exc


@router.get("/events", response_model=EventListEnvelope)
async def get_events(
    facility_id: str | None = Query(default=None),
    sensor_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
) -> EventListEnvelope:
    """List events/incidents within the caller's scope.

    Args:
        facility_id: Optional exact facility filter.
        sensor_id: Optional exact sensor filter.
        event_type: Optional exact event_type (sensor_type_id) filter.
        from_: Optional ISO 8601 inclusive lower bound on occurred_at.
        to: Optional ISO 8601 inclusive upper bound on occurred_at.
        cursor: Opaque pagination cursor.
        limit: Page size, 1-200.
        user: The authenticated caller, injected by get_current_user.

    Returns:
        An EventListEnvelope containing only events the caller may see.
    """
    occurred_from = _parse_iso_datetime(from_, "from") if from_ else None
    occurred_to = _parse_iso_datetime(to, "to") if to else None

    async with async_session_factory() as session:
        await sync_events(session)
        scope = await resolve_scope(session, user.id)
        allowed_ids = None if scope["type"] == "all_facilities" else set(scope["facility_ids"])

        items, next_cursor, total = await list_events(
            session,
            allowed_facility_ids=allowed_ids,
            facility_id=facility_id,
            sensor_id=sensor_id,
            event_type=event_type,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
            cursor=cursor,
            limit=limit,
        )

    return EventListEnvelope(
        data=[EventOut.model_validate(item) for item in items],
        meta=EventListMeta(next_cursor=next_cursor, total=total, generated_at=datetime.now(timezone.utc)),
    )
