"""Scope-filtered, cursor-paginated sensor queries (ticket 05).

Orphaned/unknown channels (facility_id is None) are visible only to
all_facilities-scope callers -- they cannot be attributed to any
specific dispatcher's assigned facilities.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.errors import ApiError
from src.models.hierarchy import HierarchyNode
from src.models.sensor import SensorChannel, SensorReading
from src.schemas.sensor import CurrentReading, SensorDetailOut, SensorOut
from src.services.reference_data import SENSOR_TYPES

_VALUE_TYPE_BY_ID = {t.id: t.value_type for t in SENSOR_TYPES}


def _value_type_for(sensor_type_id: str) -> str:
    return _VALUE_TYPE_BY_ID.get(sensor_type_id, "categorical")


def _to_sensor_out(channel: SensorChannel) -> SensorOut:
    return SensorOut(
        id=channel.id,
        channel_id=channel.channel_id,
        tag=channel.tag,
        sensor_type=channel.sensor_type_id,
        system_type=channel.system_type,
        value_type=_value_type_for(channel.sensor_type_id),
        display_name=channel.display_name,
        facility_id=channel.facility_id,
        hierarchy_node_id=channel.hierarchy_node_id,
    )


async def list_sensors(
    session: AsyncSession,
    allowed_facility_ids: set[str] | None,
    facility_id: str | None = None,
    hierarchy_node_id: str | None = None,
    sensor_type: str | None = None,
    query: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[SensorOut], str | None, int]:
    """List sensor channels visible to the caller's scope.

    Args:
        session: An active async database session.
        allowed_facility_ids: None for all_facilities scope (sees every
            channel, including orphans with facility_id=None), else the
            exact set of facility ids the caller may see (orphans excluded).
        facility_id: Optional exact facility filter.
        hierarchy_node_id: Optional exact hierarchy node filter.
        sensor_type: Optional exact sensor_type_id filter.
        query: Optional case-insensitive substring match on display_name/tag.
        cursor: Opaque cursor -- the last-seen sensor id, exclusive.
        limit: Page size.

    Returns:
        (items, next_cursor, total_matching_scope_and_filters).
    """
    stmt = select(SensorChannel).order_by(SensorChannel.id)
    if allowed_facility_ids is None:
        pass  # all_facilities: no scope restriction, orphans included
    elif not allowed_facility_ids:
        return [], None, 0
    else:
        stmt = stmt.where(SensorChannel.facility_id.in_(allowed_facility_ids))

    if facility_id:
        stmt = stmt.where(SensorChannel.facility_id == facility_id)
    if hierarchy_node_id:
        stmt = stmt.where(SensorChannel.hierarchy_node_id == hierarchy_node_id)
    if sensor_type:
        stmt = stmt.where(SensorChannel.sensor_type_id == sensor_type)
    if query:
        like = f"%{query}%"
        stmt = stmt.where((SensorChannel.display_name.ilike(like)) | (SensorChannel.tag.ilike(like)))

    all_matching = (await session.execute(stmt)).scalars().all()
    total = len(all_matching)

    start = 0
    if cursor:
        for i, channel in enumerate(all_matching):
            if channel.id == cursor:
                start = i + 1
                break
        else:
            start = total

    page = all_matching[start : start + limit]
    next_cursor = page[-1].id if len(page) == limit and (start + limit) < total else None

    return [_to_sensor_out(c) for c in page], next_cursor, total


async def _hierarchy_path(session: AsyncSession, node_id: str | None) -> list[str]:
    if node_id is None:
        return []
    by_id = dict((await session.execute(select(HierarchyNode.id, HierarchyNode.parent_id))).all())
    chain: list[str] = []
    current: str | None = node_id
    while current is not None and current in by_id:
        chain.append(current)
        current = by_id[current]
    chain.reverse()
    return chain


async def get_sensor_detail(
    session: AsyncSession, sensor_id: str, allowed_facility_ids: set[str] | None
) -> SensorDetailOut:
    """Fetch one sensor's full detail card, enforcing scope.

    Args:
        session: An active async database session.
        sensor_id: The requested sensor id.
        allowed_facility_ids: None for all_facilities scope, else the exact
            set of facility ids the caller may see.

    Returns:
        The sensor's full SensorDetailOut.

    Raises:
        ApiError: 404 if the sensor does not exist; 403 if it exists but is
            outside scope (orphans are out of scope for anyone restricted).
    """
    channel = (await session.execute(select(SensorChannel).where(SensorChannel.id == sensor_id))).scalar_one_or_none()
    if channel is None:
        raise ApiError(404, "NOT_FOUND", "Датчик не найден")

    if allowed_facility_ids is not None:
        if channel.facility_id is None or channel.facility_id not in allowed_facility_ids:
            raise ApiError(403, "SENSOR_ACCESS_DENIED", "Недостаточно прав для просмотра датчика")

    latest = (
        await session.execute(
            select(SensorReading)
            .where(SensorReading.channel_id == channel.channel_id)
            .order_by(SensorReading.occurred_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    current_reading = None
    if latest is not None:
        current_reading = CurrentReading(
            value=latest.raw_value,
            numeric_value=latest.numeric_value,
            unit=None,
            measured_at=latest.occurred_at,
        )

    base = _to_sensor_out(channel)
    return SensorDetailOut(
        **base.model_dump(),
        hierarchy_path=await _hierarchy_path(session, channel.hierarchy_node_id),
        current_reading=current_reading,
        current_state="unknown",
        forecast_summary=None,
        data_health="unavailable",
        maintenance_state="unknown",
    )
