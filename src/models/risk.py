"""Risk forecast domain (ticket 08): the queue + decision journal.

`related_risk_id` on `Event` (ticket 07) points here once `sync_risks`
(leaf 1.2.2) evaluates a group of events -- the real write path ticket 07
left as an honest placeholder.
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base

SINGLETON_ID = "singleton"


class Risk(Base):
    """One risk forecast (a "card" in the /risks queue)."""

    __tablename__ = "risks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    forecast_id: Mapped[str] = mapped_column(String)
    risk_type: Mapped[str] = mapped_column(String, index=True)
    target_type: Mapped[str] = mapped_column(String)
    target_id: Mapped[str] = mapped_column(String, index=True)
    facility_id: Mapped[str | None] = mapped_column(ForeignKey("facilities.id"), nullable=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lead_min_hours: Mapped[float] = mapped_column(Float)
    horizon_hours: Mapped[float] = mapped_column(Float)
    prediction_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    prediction_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    probability: Mapped[float] = mapped_column(Float)
    threshold: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String, index=True)
    priority_score: Mapped[float] = mapped_column(Float, index=True)
    decision_status: Mapped[str] = mapped_column(String, default="open", index=True)
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data_health: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    top_factors: Mapped[list] = mapped_column(JSON)
    recommendation: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RiskDecision(Base):
    """An append-only journal entry for one decision on one Risk."""

    __tablename__ = "risk_decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    risk_id: Mapped[str] = mapped_column(ForeignKey("risks.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String)
    reason_code: Mapped[str | None] = mapped_column(String, nullable=True)
    comment: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RiskSyncState(Base):
    """Singleton high-water-mark: the highest Event.id already risk-evaluated."""

    __tablename__ = "risk_sync_state"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=SINGLETON_ID)
    last_synced_event_id: Mapped[str] = mapped_column(String, default="")
