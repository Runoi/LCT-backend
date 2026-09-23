"""Scope-filtered, cursor-paginated facility queries (ticket 04)."""
import hashlib
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.errors import ApiError
from src.models.hierarchy import Facility, HierarchyNode
from src.schemas.facility import (
    Assets,
    DataHealth,
    FacilityOut,
    Forecast,
    Incidents,
    Location,
    SourceHealthEntry,
)
from src.services.source_health import get_source_health

_LON_MIN, _LON_MAX = 37.3, 38.0
_LAT_MIN, _LAT_MAX = 55.5, 56.0


def _deterministic_point(facility_id: str) -> tuple[float, float]:
    """Derive a stable, non-random synthetic point from a facility_id.

    Args:
        facility_id: The opaque facility identifier.

    Returns:
        (longitude, latitude), always within the fixed demo bounding box.
    """
    digest = hashlib.md5(facility_id.encode("utf-8")).hexdigest()
    lon = _LON_MIN + (int(digest[:8], 16) % 10_000) / 10_000 * (_LON_MAX - _LON_MIN)
    lat = _LAT_MIN + (int(digest[8:16], 16) % 10_000) / 10_000 * (_LAT_MAX - _LAT_MIN)
    return round(lon, 6), round(lat, 6)


async def _load_source_health(session: AsyncSession) -> list[SourceHealthEntry]:
    """Fetch the real, system-wide source-health array once per request.

    See ticket 06's emulation module (`src/services/source_health.py`) --
    this replaces ticket 04's original hardcoded "unavailable" placeholder.
    Called once by the list/detail endpoints, not per facility.
    """
    entries = await get_source_health(session)
    return [
        SourceHealthEntry(
            source=e.source, display_name=e.display_name, status=e.status,
            last_success_at=e.last_success_at, delay_seconds=e.delay_seconds,
        )
        for e in entries
    ]


async def _build_facility_out(
    session: AsyncSession, facility: Facility, source_health: list[SourceHealthEntry]
) -> FacilityOut:
    collector_count = (
        await session.execute(
            select(func.count()).select_from(HierarchyNode).where(HierarchyNode.facility_id == facility.id)
        )
    ).scalar_one()

    return FacilityOut(
        id=facility.id,
        display_name=facility.display_name,
        facility_type=facility.facility_type,
        location=Location(coordinates=_deterministic_point(facility.id)),
        current_state="unknown",
        forecast=Forecast(risk_level="unknown", max_probability=0.0, active_count=0, earliest_window_start=None),
        incidents=Incidents(open_count=0, critical_count=0),
        assets=Assets(collector_count=collector_count, sensor_count=0, offline_sensor_count=0),
        data_health=DataHealth(freshness="unavailable", last_event_at=None, coverage=0.0),
        priority_score=0.0,
        source_health=source_health,
        updated_at=datetime.now(timezone.utc),
    )


async def list_facilities(
    session: AsyncSession,
    allowed_facility_ids: set[str] | None,
    query: str | None = None,
    current_state: str | None = None,
    risk_level: str | None = None,
    district: str | None = None,
    bbox: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[FacilityOut], str | None, int]:
    """List facilities filtered by scope and the documented query params.

    Args:
        session: An active async database session.
        allowed_facility_ids: None for all_facilities scope, else the exact
            set of facility ids the caller may see.
        query: Optional case-insensitive substring match on display_name.
        current_state: Present for contract completeness; MVP data has no
            real current_state yet, so this never actually filters (see
            src/schemas/facility.py module docstring).
        risk_level: Present for contract completeness; same caveat as
            current_state -- no real forecast data yet.
        district: Optional district_id filter.
        bbox: Optional "min_lon,min_lat,max_lon,max_lat" filter against the
            deterministic synthetic geometry.
        cursor: Opaque cursor — the last-seen facility_id, exclusive.
        limit: Page size.

    Returns:
        (items, next_cursor, total_matching_scope_and_filters).
    """
    del current_state, risk_level  # accepted per contract; not yet meaningful (see docstring)

    stmt = select(Facility).order_by(Facility.id)
    if allowed_facility_ids is not None:
        if not allowed_facility_ids:
            return [], None, 0
        stmt = stmt.where(Facility.id.in_(allowed_facility_ids))
    if query:
        stmt = stmt.where(Facility.display_name.ilike(f"%{query}%"))
    if district:
        stmt = stmt.where(Facility.district_id == district)

    all_matching = (await session.execute(stmt)).scalars().all()

    if bbox:
        try:
            min_lon, min_lat, max_lon, max_lat = (float(part) for part in bbox.split(","))
        except ValueError as exc:
            raise ApiError(400, "VALIDATION_ERROR", "bbox must be 'min_lon,min_lat,max_lon,max_lat'") from exc
        all_matching = [
            f
            for f in all_matching
            if min_lon <= _deterministic_point(f.id)[0] <= max_lon
            and min_lat <= _deterministic_point(f.id)[1] <= max_lat
        ]

    total = len(all_matching)

    start = 0
    if cursor:
        for i, facility in enumerate(all_matching):
            if facility.id == cursor:
                start = i + 1
                break
        else:
            start = total  # unknown cursor -> empty page, not an error

    page = all_matching[start : start + limit]
    next_cursor = page[-1].id if len(page) == limit and (start + limit) < total else None

    source_health = await _load_source_health(session)
    items = [await _build_facility_out(session, facility, source_health) for facility in page]
    return items, next_cursor, total


async def get_facility_detail(
    session: AsyncSession, facility_id: str, allowed_facility_ids: set[str] | None
) -> FacilityOut:
    """Fetch one facility's detail, enforcing scope without leaking data.

    Args:
        session: An active async database session.
        facility_id: The requested facility id.
        allowed_facility_ids: None for all_facilities scope, else the exact
            set of facility ids the caller may see.

    Returns:
        The facility's full FacilityOut.

    Raises:
        ApiError: 403 if the facility exists but is outside scope (no
            facility data included in the error body); 404 if it does not
            exist at all.
    """
    facility = (await session.execute(select(Facility).where(Facility.id == facility_id))).scalar_one_or_none()
    if facility is None:
        raise ApiError(404, "NOT_FOUND", "Объект не найден")
    if allowed_facility_ids is not None and facility_id not in allowed_facility_ids:
        raise ApiError(403, "FACILITY_ACCESS_DENIED", "Недостаточно прав для просмотра объекта")
    source_health = await _load_source_health(session)
    return await _build_facility_out(session, facility, source_health)
