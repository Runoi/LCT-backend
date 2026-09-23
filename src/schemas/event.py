"""Pydantic response models for GET /api/v1/events (ticket 07)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EventOut(BaseModel):
    """One event/incident-journal entry.

    is_confirmed_incident/verification_result/resolved_at/related_risk_id
    are distinct fields from state (see src/models/event.py) -- an alarm
    event and a confirmed incident are never collapsed into one status.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    source: str
    facility_id: str | None
    sensor_id: str
    occurred_at: datetime
    ingested_at: datetime
    state: str
    value: str
    is_confirmed_incident: bool
    verification_result: str | None
    resolved_at: datetime | None
    related_risk_id: str | None


class EventListMeta(BaseModel):
    """Cursor-pagination metadata for the event list envelope."""

    next_cursor: str | None
    total: int
    generated_at: datetime


class EventListEnvelope(BaseModel):
    """The standard {data, meta} envelope for GET /api/v1/events."""

    data: list[EventOut]
    meta: EventListMeta
