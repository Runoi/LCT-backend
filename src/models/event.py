"""Event journal (ticket 07): a materialized projection of "notable"
SensorReading rows (is_alarm or is_anomaly), not a live join.

`related_risk_id`/`is_confirmed_incident`/`verification_result`/
`resolved_at` are honest MVP placeholders here: `sync_events` always sets
them to None/False/None/None (no write path exists until tickets 08/09
build the `risks`/decision workflow), but the columns are real and
settable now so the API layer can already prove these are distinguishable
states, not one collapsed status.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base

SINGLETON_ID = "singleton"


class Event(Base):
    """One materialized alarm/anomaly event, denormalized for fast querying."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_reading_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String)
    facility_id: Mapped[str | None] = mapped_column(ForeignKey("facilities.id"), nullable=True)
    sensor_id: Mapped[str] = mapped_column(String, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String)
    value: Mapped[str] = mapped_column(String)
    is_confirmed_incident: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_result: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    related_risk_id: Mapped[str | None] = mapped_column(String, nullable=True)


class EventSyncState(Base):
    """Singleton high-water-mark: the highest SensorReading.id already synced."""

    __tablename__ = "event_sync_state"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=SINGLETON_ID)
    last_synced_reading_id: Mapped[int] = mapped_column(Integer, default=0)
