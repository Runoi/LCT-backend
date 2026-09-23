"""Singleton state for the SMVU near-real-time replay engine (ticket 06).

See `src/services/replay_engine.py` for the tick logic that reads and
advances this row.
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base

SINGLETON_ID = "singleton"


class ReplayState(Base):
    """The replay engine's virtual clock position, as a single persisted row."""

    __tablename__ = "replay_state"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=SINGLETON_ID)
    virtual_cursor: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tick_count: Mapped[int] = mapped_column(Integer, default=0)
