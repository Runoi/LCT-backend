"""Work-order domain (ticket 09): the whole lifecycle is emulated locally --
the real external help-desk system does not exist and never will
(QA_ORGANIZERS_CLARIFICATIONS.md section 5). Never confuse with ticket 06's
`ExternalWorkOrderRecord`, a fully separate, isolated synthetic-backlog
table used only for source-health realism.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class WorkOrder(Base):
    """One repair/maintenance work order, owned end to end by this backend."""

    __tablename__ = "work_orders"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_number: Mapped[str] = mapped_column(String, unique=True, index=True)
    source_risk_id: Mapped[str | None] = mapped_column(ForeignKey("risks.id"), nullable=True)
    facility_id: Mapped[str | None] = mapped_column(ForeignKey("facilities.id"), nullable=True)
    target_entity_type: Mapped[str] = mapped_column(String)
    target_entity_id: Mapped[str] = mapped_column(String)
    work_type: Mapped[str] = mapped_column(String)
    priority: Mapped[str] = mapped_column(String)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    description: Mapped[str] = mapped_column(String)
    comment: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="draft", index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # No write endpoint increments this yet (ticket 09 has no PATCH/status-
    # transition action) -- present because the contract requires it in the
    # response now, ready for whichever future ticket adds optimistic
    # concurrency on work-order updates (same shape as Risk.version).
    version: Mapped[int] = mapped_column(Integer, default=1)
