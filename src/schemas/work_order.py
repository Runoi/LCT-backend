"""Pydantic response models for POST/GET /api/v1/work-orders (ticket 09)."""
from datetime import datetime

from pydantic import BaseModel


class CreateWorkOrderRequest(BaseModel):
    """Body for POST /api/v1/work-orders.

    mode must be "draft" -- the only mode this backend ever supports, since
    no real external work-order system exists to submit to.
    """

    mode: str
    source_risk_id: str | None = None
    facility_id: str
    target_entity_type: str
    target_entity_id: str
    work_type: str
    priority: str
    due_at: datetime
    description: str
    comment: str | None = None


class WorkOrderOut(BaseModel):
    """One work order's full representation."""

    id: str
    display_number: str
    source_risk_id: str | None
    facility_id: str | None
    target_entity_type: str
    target_entity_id: str
    work_type: str
    priority: str
    due_at: datetime
    description: str
    comment: str | None
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    version: int


class WorkOrderListMeta(BaseModel):
    """Cursor-pagination metadata for the work-order list envelope."""

    next_cursor: str | None
    total: int
    generated_at: datetime


class WorkOrderListEnvelope(BaseModel):
    """The standard {data, meta} envelope for GET /api/v1/work-orders."""

    data: list[WorkOrderOut]
    meta: WorkOrderListMeta
