"""Work-order creation and scope-filtered listing (ticket 09)."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.work_order import WorkOrder
from src.schemas.work_order import CreateWorkOrderRequest, WorkOrderOut
from src.services.work_order_numbering import generate_display_number


def to_work_order_out(work_order: WorkOrder) -> WorkOrderOut:
    """Compose a WorkOrder row into its API shape.

    Args:
        work_order: The ORM row.

    Returns:
        The WorkOrderOut.
    """
    return WorkOrderOut(
        id=work_order.id,
        display_number=work_order.display_number,
        source_risk_id=work_order.source_risk_id,
        facility_id=work_order.facility_id,
        target_entity_type=work_order.target_entity_type,
        target_entity_id=work_order.target_entity_id,
        work_type=work_order.work_type,
        priority=work_order.priority,
        due_at=work_order.due_at,
        description=work_order.description,
        comment=work_order.comment,
        status=work_order.status,
        created_by=work_order.created_by,
        created_at=work_order.created_at,
        updated_at=work_order.updated_at,
        version=work_order.version,
    )


async def create_work_order(session: AsyncSession, body: CreateWorkOrderRequest, created_by: str) -> WorkOrder:
    """Insert a new draft work order.

    Args:
        session: An active async database session.
        body: The already-validated creation request.
        created_by: The id of the creating user (audit metadata).

    Returns:
        The created WorkOrder.
    """
    now = datetime.now(timezone.utc)
    display_number = await generate_display_number(session, now=now)
    work_order = WorkOrder(
        id=f"wo_{uuid4().hex[:20]}",
        display_number=display_number,
        source_risk_id=body.source_risk_id,
        facility_id=body.facility_id,
        target_entity_type=body.target_entity_type,
        target_entity_id=body.target_entity_id,
        work_type=body.work_type,
        priority=body.priority,
        due_at=body.due_at,
        description=body.description,
        comment=body.comment,
        status="draft",
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    session.add(work_order)
    await session.commit()
    return work_order


async def list_work_orders(
    session: AsyncSession,
    allowed_facility_ids: set[str] | None,
    *,
    facility_id: str | None = None,
    status: str | None = None,
    work_type: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[WorkOrder], str | None, int]:
    """List work orders filtered by scope, newest first.

    Args:
        session: An active async database session.
        allowed_facility_ids: None for all_facilities scope, else the exact
            set of facility ids the caller may see.
        facility_id: Optional exact facility filter.
        status: Optional exact status filter.
        work_type: Optional exact WORK_TYPES filter.
        cursor: Opaque cursor -- the last-seen work order id, exclusive.
        limit: Page size.

    Returns:
        (items, next_cursor, total_matching_scope_and_filters).
    """
    if allowed_facility_ids is not None and not allowed_facility_ids:
        return [], None, 0

    stmt = select(WorkOrder)
    if allowed_facility_ids is not None:
        stmt = stmt.where(WorkOrder.facility_id.in_(allowed_facility_ids))
    if facility_id:
        stmt = stmt.where(WorkOrder.facility_id == facility_id)
    if status:
        stmt = stmt.where(WorkOrder.status == status)
    if work_type:
        stmt = stmt.where(WorkOrder.work_type == work_type)

    all_matching = (await session.execute(stmt)).scalars().all()
    all_matching = sorted(all_matching, key=lambda wo: wo.created_at, reverse=True)
    total = len(all_matching)

    start = 0
    if cursor:
        for i, work_order in enumerate(all_matching):
            if work_order.id == cursor:
                start = i + 1
                break
        else:
            start = total

    page = all_matching[start : start + limit]
    next_cursor = page[-1].id if len(page) == limit and (start + limit) < total else None
    return page, next_cursor, total
