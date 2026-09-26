"""POST/GET /api/v1/work-orders -- local, backend-owned work-order lifecycle."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request

from src.db import async_session_factory
from src.deps.auth import require_any_permission, require_permission
from src.errors import ApiError
from src.models.auth import User
from src.schemas.work_order import CreateWorkOrderRequest, WorkOrderListEnvelope, WorkOrderListMeta, WorkOrderOut
from src.services.reference_data import RISK_LEVELS, WORK_TYPES
from src.services.scope import resolve_scope
from src.services.work_order_lifecycle import sync_work_order_statuses
from src.services.work_order_query import create_work_order, list_work_orders, to_work_order_out

router = APIRouter(prefix="/api/v1", tags=["work-orders"])

_VALID_WORK_TYPES = {t.id for t in WORK_TYPES}
_VALID_PRIORITIES = {level.id for level in RISK_LEVELS}
_VALID_TARGET_ENTITY_TYPES = {"sensor", "facility", "hierarchy_node"}


@router.post("/work-orders", response_model=WorkOrderOut, status_code=201)
async def post_work_order(
    body: CreateWorkOrderRequest,
    request: Request,
    user: User = Depends(require_any_permission("work_order.create_draft", "work_order.submit")),
) -> WorkOrderOut:
    """Create a draft work order.

    Args:
        body: The creation request; mode must be "draft".
        request: The current request, used to enrich the audit journal entry.
        user: The authenticated caller, injected by require_any_permission.

    Returns:
        The created work order.

    Raises:
        ApiError: 422 for mode != "draft" or an unknown work_type/priority/
            target_entity_type; 403 if facility_id is outside the caller's scope.
    """
    request.state.audit["details"] = {"facility_id": body.facility_id}
    if body.mode != "draft":
        raise ApiError(
            422, "DOMAIN_VALIDATION_ERROR",
            "Поддерживается только mode='draft' -- реальной отправки во внешнюю систему заявок нет",
        )
    if body.work_type not in _VALID_WORK_TYPES:
        raise ApiError(422, "DOMAIN_VALIDATION_ERROR", f"Неизвестный work_type: {body.work_type}")
    if body.priority not in _VALID_PRIORITIES:
        raise ApiError(422, "DOMAIN_VALIDATION_ERROR", f"Неизвестный priority: {body.priority}")
    if body.target_entity_type not in _VALID_TARGET_ENTITY_TYPES:
        raise ApiError(422, "DOMAIN_VALIDATION_ERROR", f"Неизвестный target_entity_type: {body.target_entity_type}")

    async with async_session_factory() as session:
        scope = await resolve_scope(session, user.id)
        if scope["type"] != "all_facilities" and body.facility_id not in scope["facility_ids"]:
            raise ApiError(403, "FACILITY_ACCESS_DENIED", "Недостаточно прав для создания заявки по этому объекту")

        work_order = await create_work_order(session, body, user.id)
        request.state.audit["target_type"] = "work_order"
        request.state.audit["target_id"] = work_order.id
        return to_work_order_out(work_order)


@router.get("/work-orders", response_model=WorkOrderListEnvelope)
async def get_work_orders(
    facility_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    work_type: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_permission("work_order.read")),
) -> WorkOrderListEnvelope:
    """List work orders within the caller's scope, newest first.

    Args:
        facility_id: Optional exact facility filter.
        status: Optional exact status filter.
        work_type: Optional exact WORK_TYPES filter.
        cursor: Opaque pagination cursor.
        limit: Page size, 1-200.
        user: The authenticated caller, injected by require_permission.

    Returns:
        A WorkOrderListEnvelope containing only work orders the caller may see.
    """
    async with async_session_factory() as session:
        await sync_work_order_statuses(session)
        scope = await resolve_scope(session, user.id)
        allowed_ids = None if scope["type"] == "all_facilities" else set(scope["facility_ids"])

        items, next_cursor, total = await list_work_orders(
            session,
            allowed_facility_ids=allowed_ids,
            facility_id=facility_id,
            status=status,
            work_type=work_type,
            cursor=cursor,
            limit=limit,
        )

    return WorkOrderListEnvelope(
        data=[to_work_order_out(item) for item in items],
        meta=WorkOrderListMeta(next_cursor=next_cursor, total=total, generated_at=datetime.now(timezone.utc)),
    )
