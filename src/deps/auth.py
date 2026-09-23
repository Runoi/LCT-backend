"""Auth/RBAC enforcement dependencies: get_current_user, require_permission.

These are the shared primitives every future protected endpoint (tickets
04+) must use — access filtering happens here, on the backend, never by
trusting a client-side hidden UI element.
"""
from fastapi import Depends, Header
from sqlalchemy import select

from src.db import async_session_factory
from src.errors import ApiError
from src.models.auth import User, UserPermission
from src.services.auth_service import get_active_session_user


async def _load_user_permissions(user_id: str) -> set[str]:
    async with async_session_factory() as session:
        rows = (
            await session.execute(select(UserPermission.permission).where(UserPermission.user_id == user_id))
        ).scalars().all()
    return set(rows)


async def get_current_user(authorization: str | None = Header(default=None)) -> User:
    """Resolve the bearer token in the Authorization header to a User.

    Args:
        authorization: The raw "Authorization" header value.

    Returns:
        The authenticated, role-configured User.

    Raises:
        ApiError: 401 if the header is missing/malformed or the session is
            missing/revoked; 422 if the user has no role configured.
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise ApiError(401, "SESSION_EXPIRED", "Сессия истекла или токен отсутствует")

    token = authorization.removeprefix("Bearer ").strip()
    async with async_session_factory() as session:
        user = await get_active_session_user(session, token)

    if user is None:
        raise ApiError(401, "SESSION_EXPIRED", "Сессия истекла или была отозвана")
    if not user.role:
        raise ApiError(422, "ROLE_NOT_CONFIGURED", "Роль пользователя не сконфигурирована на сервере")
    return user


def require_permission(permission: str):
    """Build a dependency that additionally requires a specific capability.

    Args:
        permission: The required capability string (e.g. "risk.acknowledge").

    Returns:
        A FastAPI dependency raising 403 when the current user lacks it.
    """

    async def _dependency(user: User = Depends(get_current_user)) -> User:
        granted = await _load_user_permissions(user.id)
        if permission not in granted:
            raise ApiError(403, "PERMISSION_DENIED", f"Недостаточно прав: {permission}")
        return user

    return _dependency


def require_any_permission(*permissions: str):
    """Build a dependency requiring at least one of several capabilities.

    Args:
        permissions: Capability strings; any one of them is sufficient
            (e.g. "work_order.create_draft" OR "work_order.submit").

    Returns:
        A FastAPI dependency raising 403 when the current user has none of them.
    """

    async def _dependency(user: User = Depends(get_current_user)) -> User:
        granted = await _load_user_permissions(user.id)
        if granted.isdisjoint(permissions):
            raise ApiError(403, "PERMISSION_DENIED", f"Недостаточно прав: любое из {', '.join(permissions)}")
        return user

    return _dependency
