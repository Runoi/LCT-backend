"""GET /api/v1/me — the current user's role, permissions, scope, locale."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.db import async_session_factory
from src.deps.auth import get_current_user
from src.models.auth import User
from src.services.scope import resolve_permissions, resolve_scope

router = APIRouter(prefix="/api/v1", tags=["me"])


class ScopeOut(BaseModel):
    """The resolved scope: all facilities, or an assigned subset."""

    type: str
    facility_ids: list[str] | None = None


class MeOut(BaseModel):
    """The current user's identity, permissions, scope, and locale."""

    role: str
    permissions: list[str]
    scope: ScopeOut
    timezone: str
    locale: str


@router.get("/me", response_model=MeOut, response_model_exclude_none=True)
async def get_me(user: User = Depends(get_current_user)) -> MeOut:
    """Return the authenticated user's role, permissions, scope, and locale.

    Args:
        user: The authenticated user, injected by get_current_user.

    Returns:
        A MeOut with the resolved scope (facility_ids omitted for
        all_facilities scope) and the sorted permission list.
    """
    async with async_session_factory() as session:
        scope = await resolve_scope(session, user.id)
        permissions = await resolve_permissions(session, user.id)

    return MeOut(
        role=user.role,
        permissions=permissions,
        scope=ScopeOut(**scope),
        timezone=user.timezone,
        locale=user.locale,
    )
