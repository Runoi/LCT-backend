"""ORM models for authentication, permissions, and scope (ticket 03).

District/DistrictFacility double as the ticket-04 grouping entity (see
`docs/adr/0007-leaf-rows-are-facilities-level2-are-districts.md`): the same
table is seeded from the real facility catalogue, not a parallel structure.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.config import get_settings
from src.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _default_session_expiry() -> datetime:
    # Любой путь вставки сессии получает срок действия, а не только create_session.
    return _utcnow() + timedelta(minutes=get_settings().session_ttl_minutes)


class User(Base):
    """A backend user (mock LDAP/AD identity)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="")
    timezone: Mapped[str] = mapped_column(String, default="Europe/Moscow")
    locale: Mapped[str] = mapped_column(String, default="ru")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class UserPermission(Base):
    """A single granted capability string for a user."""

    __tablename__ = "user_permissions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    permission: Mapped[str] = mapped_column(String, primary_key=True)


class District(Base):
    """A scope-grouping of facilities ('район'). Seeded from real data in ticket 04."""

    __tablename__ = "districts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)


class DistrictFacility(Base):
    """Membership of a facility_id in a district."""

    __tablename__ = "district_facilities"

    district_id: Mapped[str] = mapped_column(ForeignKey("districts.id"), primary_key=True)
    facility_id: Mapped[str] = mapped_column(String, primary_key=True)


class UserScope(Base):
    """The scope type for a user: all facilities, or an assigned subset."""

    __tablename__ = "user_scope"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String)  # "all_facilities" | "assigned_facilities"


class UserScopeFacility(Base):
    """A facility_id directly assigned to a user's scope."""

    __tablename__ = "user_scope_facilities"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    facility_id: Mapped[str] = mapped_column(String, primary_key=True)


class UserScopeDistrict(Base):
    """A district assigned to a user's scope (expands to its member facility_ids)."""

    __tablename__ = "user_scope_districts"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    district_id: Mapped[str] = mapped_column(ForeignKey("districts.id"), primary_key=True)


class UserSession(Base):
    """A server-side session token with a fixed expiry; revocation takes effect immediately."""

    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_default_session_expiry)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
