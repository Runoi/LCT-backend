"""Scope-filtered risk queue queries (ticket 08).

Uses the same in-memory sort+slice pattern as tickets 04/05's facility/
sensor lists (not the keyset pagination ticket 07's event journal needs):
row count here is bounded by the number of distinct alarming sensors, not
raw telemetry volume, and the documented custom sort
(priority_score desc, prediction_window_start asc) is far simpler to
express in Python than as a composite-key SQL keyset.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.errors import ApiError
from src.models.risk import Risk
from src.schemas.risk import PredictionWindow, RiskOut, RiskTarget


def to_risk_out(risk: Risk) -> RiskOut:
    """Compose a Risk row into its nested API shape.

    Args:
        risk: The ORM row.

    Returns:
        The RiskOut with target/prediction_window nested per contract.
    """
    return RiskOut(
        id=risk.id,
        forecast_id=risk.forecast_id,
        risk_type=risk.risk_type,
        target=RiskTarget(type=risk.target_type, id=risk.target_id, facility_id=risk.facility_id),
        as_of=risk.as_of,
        lead_min_hours=risk.lead_min_hours,
        horizon_hours=risk.horizon_hours,
        prediction_window=PredictionWindow(start=risk.prediction_window_start, end=risk.prediction_window_end),
        probability=risk.probability,
        threshold=risk.threshold,
        risk_level=risk.risk_level,
        priority_score=risk.priority_score,
        decision_status=risk.decision_status,
        sla_due_at=risk.sla_due_at,
        data_health=risk.data_health,
        model=risk.model,
        top_factors=list(risk.top_factors),
        recommendation=risk.recommendation,
        version=risk.version,
        created_at=risk.created_at,
        updated_at=risk.updated_at,
    )


async def list_risks(
    session: AsyncSession,
    allowed_facility_ids: set[str] | None,
    *,
    facility_id: str | None = None,
    risk_type: str | None = None,
    risk_level: str | None = None,
    decision_status: str | None = None,
    as_of_from: datetime | None = None,
    as_of_to: datetime | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[Risk], str | None, int]:
    """List risks filtered by scope and the documented query params.

    Args:
        session: An active async database session.
        allowed_facility_ids: None for all_facilities scope, else the exact
            set of facility ids the caller may see.
        facility_id: Optional exact facility filter.
        risk_type: Optional exact RISK_TYPES filter.
        risk_level: Optional exact RISK_LEVELS filter.
        decision_status: Optional exact decision_status filter.
        as_of_from: Optional inclusive lower bound on as_of.
        as_of_to: Optional inclusive upper bound on as_of.
        cursor: Opaque cursor -- the last-seen risk id, exclusive.
        limit: Page size.

    Returns:
        (items, next_cursor, total_matching_scope_and_filters), sorted
        priority_score desc then prediction_window_start asc.
    """
    if allowed_facility_ids is not None and not allowed_facility_ids:
        return [], None, 0

    stmt = select(Risk)
    if allowed_facility_ids is not None:
        stmt = stmt.where(Risk.facility_id.in_(allowed_facility_ids))
    if facility_id:
        stmt = stmt.where(Risk.facility_id == facility_id)
    if risk_type:
        stmt = stmt.where(Risk.risk_type == risk_type)
    if risk_level:
        stmt = stmt.where(Risk.risk_level == risk_level)
    if decision_status:
        stmt = stmt.where(Risk.decision_status == decision_status)
    if as_of_from:
        stmt = stmt.where(Risk.as_of >= as_of_from)
    if as_of_to:
        stmt = stmt.where(Risk.as_of <= as_of_to)

    all_matching = (await session.execute(stmt)).scalars().all()
    all_matching = sorted(all_matching, key=lambda r: (-r.priority_score, r.prediction_window_start))
    total = len(all_matching)

    start = 0
    if cursor:
        for i, risk in enumerate(all_matching):
            if risk.id == cursor:
                start = i + 1
                break
        else:
            start = total  # unknown cursor -> empty page, not an error

    page = all_matching[start : start + limit]
    next_cursor = page[-1].id if len(page) == limit and (start + limit) < total else None
    return page, next_cursor, total


async def get_risk_detail(session: AsyncSession, risk_id: str, allowed_facility_ids: set[str] | None) -> Risk:
    """Fetch one risk's ORM row, enforcing scope without leaking data.

    Args:
        session: An active async database session.
        risk_id: The requested risk id.
        allowed_facility_ids: None for all_facilities scope, else the exact
            set of facility ids the caller may see.

    Returns:
        The Risk row.

    Raises:
        ApiError: 404 if it does not exist at all; 403 if it exists but is
            outside scope (no risk data included in the error body).
    """
    risk = (await session.execute(select(Risk).where(Risk.id == risk_id))).scalar_one_or_none()
    if risk is None:
        raise ApiError(404, "NOT_FOUND", "Прогноз не найден")
    if allowed_facility_ids is not None and risk.facility_id not in allowed_facility_ids:
        raise ApiError(403, "FACILITY_ACCESS_DENIED", "Недостаточно прав для просмотра прогноза")
    return risk
