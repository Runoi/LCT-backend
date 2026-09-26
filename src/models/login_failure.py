"""Failed login attempts, the input of the brute-force lockout (TZ section 5)."""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class LoginFailure(Base):
    """One failed login attempt; recorded for unknown usernames as well."""

    __tablename__ = "login_failures"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, index=True)
    ip: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
