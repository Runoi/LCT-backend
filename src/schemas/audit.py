"""Pydantic response models for GET /api/v1/audit."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditEntryOut(BaseModel):
    """One journaled user action."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    user_id: str | None
    username: str | None
    action: str
    target_type: str | None
    target_id: str | None
    result: str
    status_code: int
    ip: str | None
    trace_id: str
    details: dict | None


class AuditListMeta(BaseModel):
    """Cursor-pagination metadata for the audit journal envelope."""

    next_cursor: str | None
    total: int
    generated_at: datetime


class AuditListEnvelope(BaseModel):
    """The standard {data, meta} envelope for GET /api/v1/audit."""

    data: list[AuditEntryOut]
    meta: AuditListMeta
