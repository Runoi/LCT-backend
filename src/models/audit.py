"""Append-only journal of user actions (TZ section 11: "журналирование всех действий пользователей").

`user_id` deliberately has no foreign key: the journal must outlive the
users it describes. Rows are only ever inserted -- no code path updates
or deletes them.
"""
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class AuditLogEntry(Base):
    """One journaled user action with its actor, target and outcome."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String, index=True)
    target_type: Mapped[str | None] = mapped_column(String, nullable=True)
    target_id: Mapped[str | None] = mapped_column(String, nullable=True)
    result: Mapped[str] = mapped_column(String)  # "success" | "denied" | "failure"
    status_code: Mapped[int] = mapped_column(Integer)
    ip: Mapped[str | None] = mapped_column(String, nullable=True)
    trace_id: Mapped[str] = mapped_column(String)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
