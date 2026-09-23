"""GET /api/v1/risks[...] -- scope-filtered risk queue and detail card."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from src.db import async_session_factory
from src.deps.auth import require_permission
from src.errors import ApiError
from src.models.auth import User
from src.schemas.risk import AcknowledgeRequest, DeferRequest, RejectRequest, RiskListEnvelope, RiskListMeta, RiskOut
from src.services.reference_data import REJECT_REASONS
from src.services.risk_decision import apply_decision
from src.services.risk_query import get_risk_detail, list_risks, to_risk_out
from src.services.scope import resolve_scope

_REJECT_REASONS_BY_ID = {r.id: r for r in REJECT_REASONS}

router = APIRouter(prefix="/api/v1", tags=["risks"])


def _parse_iso_datetime(raw: str, field_name: str) -> datetime:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(400, "VALIDATION_ERROR", f"{field_name} must be an ISO 8601 datetime") from exc


@router.get("/risks", response_model=RiskListEnvelope)
async def get_risks(
    facility_id: str | None = Query(default=None),
    risk_type: str | None = Query(default=None),
    risk_level: str | None = Query(default=None),
    decision_status: str | None = Query(default=None),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_permission("risk.read")),
) -> RiskListEnvelope:
    """List the risk forecast queue within the caller's scope.

    Args:
        facility_id: Optional exact facility filter.
        risk_type: Optional exact RISK_TYPES filter.
        risk_level: Optional exact RISK_LEVELS filter.
        decision_status: Optional exact decision_status filter.
        from_: Optional ISO 8601 inclusive lower bound on as_of.
        to: Optional ISO 8601 inclusive upper bound on as_of.
        cursor: Opaque pagination cursor.
        limit: Page size, 1-200.
        user: The authenticated caller, injected by require_permission.

    Returns:
        A RiskListEnvelope sorted priority_score desc, prediction_window_start asc.
    """
    as_of_from = _parse_iso_datetime(from_, "from") if from_ else None
    as_of_to = _parse_iso_datetime(to, "to") if to else None

    async with async_session_factory() as session:
        scope = await resolve_scope(session, user.id)
        allowed_ids = None if scope["type"] == "all_facilities" else set(scope["facility_ids"])

        items, next_cursor, total = await list_risks(
            session,
            allowed_facility_ids=allowed_ids,
            facility_id=facility_id,
            risk_type=risk_type,
            risk_level=risk_level,
            decision_status=decision_status,
            as_of_from=as_of_from,
            as_of_to=as_of_to,
            cursor=cursor,
            limit=limit,
        )

    return RiskListEnvelope(
        data=[to_risk_out(item) for item in items],
        meta=RiskListMeta(next_cursor=next_cursor, total=total, generated_at=datetime.now(timezone.utc)),
    )


@router.get("/risks/{risk_id}", response_model=RiskOut)
async def get_risk(risk_id: str, user: User = Depends(require_permission("risk.read"))) -> RiskOut:
    """Fetch one risk's full forecast card, enforcing the caller's scope.

    Args:
        risk_id: The requested risk id.
        user: The authenticated caller, injected by require_permission.

    Returns:
        The risk's full detail card.

    Raises:
        ApiError: 404 if the risk does not exist; 403 if it exists but is
            outside scope.
    """
    async with async_session_factory() as session:
        scope = await resolve_scope(session, user.id)
        allowed_ids = None if scope["type"] == "all_facilities" else set(scope["facility_ids"])
        risk = await get_risk_detail(session, risk_id, allowed_ids)
        return to_risk_out(risk)


@router.post("/risks/{risk_id}/acknowledge", response_model=RiskOut)
async def acknowledge_risk(
    risk_id: str, body: AcknowledgeRequest, user: User = Depends(require_permission("risk.acknowledge"))
) -> RiskOut:
    """Acknowledge a risk forecast, with optimistic concurrency.

    Args:
        risk_id: The risk to acknowledge.
        body: The expected_version the caller last saw.
        user: The authenticated caller, injected by require_permission.

    Returns:
        The updated risk card.

    Raises:
        ApiError: 404/403 per scope (see get_risk_detail); 409 if
            expected_version is stale.
    """
    async with async_session_factory() as session:
        scope = await resolve_scope(session, user.id)
        allowed_ids = None if scope["type"] == "all_facilities" else set(scope["facility_ids"])
        risk = await get_risk_detail(session, risk_id, allowed_ids)
        updated = await apply_decision(session, risk, user, "acknowledged", body.expected_version)
        return to_risk_out(updated)


@router.post("/risks/{risk_id}/reject", response_model=RiskOut)
async def reject_risk(
    risk_id: str, body: RejectRequest, user: User = Depends(require_permission("risk.resolve"))
) -> RiskOut:
    """Reject a risk forecast; requires a reason_code, and a comment for "other".

    Args:
        risk_id: The risk to reject.
        body: expected_version, reason_code (from REJECT_REASONS), and an
            optional comment (required when reason_code="other").
        user: The authenticated caller, injected by require_permission.

    Returns:
        The updated risk card.

    Raises:
        ApiError: 422 for a missing/unknown reason_code, or a missing
            comment when the reason requires one; 404/403 per scope; 409
            if expected_version is stale.
    """
    if body.reason_code is None:
        raise ApiError(422, "DOMAIN_VALIDATION_ERROR", "reason_code обязателен при отклонении прогноза")
    reason = _REJECT_REASONS_BY_ID.get(body.reason_code)
    if reason is None:
        raise ApiError(422, "DOMAIN_VALIDATION_ERROR", f"Неизвестный reason_code: {body.reason_code}")
    if reason.requires_comment and not (body.comment and body.comment.strip()):
        raise ApiError(422, "DOMAIN_VALIDATION_ERROR", f"Комментарий обязателен для причины '{body.reason_code}'")

    async with async_session_factory() as session:
        scope = await resolve_scope(session, user.id)
        allowed_ids = None if scope["type"] == "all_facilities" else set(scope["facility_ids"])
        risk = await get_risk_detail(session, risk_id, allowed_ids)
        updated = await apply_decision(
            session, risk, user, "rejected", body.expected_version, reason_code=body.reason_code, comment=body.comment
        )
        return to_risk_out(updated)


@router.post("/risks/{risk_id}/defer", response_model=RiskOut)
async def defer_risk(
    risk_id: str, body: DeferRequest, user: User = Depends(require_permission("risk.resolve"))
) -> RiskOut:
    """Defer a risk forecast, with optimistic concurrency.

    Args:
        risk_id: The risk to defer.
        body: The expected_version the caller last saw.
        user: The authenticated caller, injected by require_permission.

    Returns:
        The updated risk card.

    Raises:
        ApiError: 404/403 per scope; 409 if expected_version is stale.
    """
    async with async_session_factory() as session:
        scope = await resolve_scope(session, user.id)
        allowed_ids = None if scope["type"] == "all_facilities" else set(scope["facility_ids"])
        risk = await get_risk_detail(session, risk_id, allowed_ids)
        updated = await apply_decision(session, risk, user, "deferred", body.expected_version)
        return to_risk_out(updated)
