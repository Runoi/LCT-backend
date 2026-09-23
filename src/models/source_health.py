"""Artificial source-degradation override (ticket 06).

Not a live external connection check: a purely local, deterministic
override the service itself applies for a bounded duration, for demo and
test purposes (see `src/services/source_health.py`).
"""
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class SourceHealthOverride(Base):
    """A temporary forced status for one source, until it expires."""

    __tablename__ = "source_health_overrides"

    source: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
