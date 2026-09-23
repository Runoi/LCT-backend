"""Tests for structured errors and the auth enforcement dependencies."""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.db import async_session_factory
from src.deps.auth import get_current_user, require_permission
from src.errors import ApiError, register_exception_handlers
from src.main import app
from src.models.auth import User
from src.services.auth_service import create_session, revoke_session
from src.services.demo_seed import seed_demo_users


async def _seed_and_login(username: str, password: str) -> str:
    async with async_session_factory() as session:
        await seed_demo_users(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["token"]


@pytest.mark.asyncio
async def test_get_current_user_rejects_missing_authorization_header() -> None:
    with pytest.raises(ApiError) as exc_info:
        await get_current_user(authorization=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "SESSION_EXPIRED"


@pytest.mark.asyncio
async def test_get_current_user_rejects_garbage_token() -> None:
    with pytest.raises(ApiError) as exc_info:
        await get_current_user(authorization="Bearer not-a-real-token")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_revoked_session_is_rejected_immediately_not_after_expiry() -> None:
    token = await _seed_and_login("manager", "manager123")

    # valid immediately after login
    user = await get_current_user(authorization=f"Bearer {token}")
    assert user.username == "manager"

    async with async_session_factory() as session:
        await revoke_session(session, token)

    with pytest.raises(ApiError) as exc_info:
        await get_current_user(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_require_permission_rejects_user_without_it() -> None:
    async with async_session_factory() as session:
        await seed_demo_users(session)
        dispatcher = (
            await session.execute(select(User).where(User.username == "dispatcher"))
        ).scalar_one()

    dependency = require_permission("report.export")  # dispatcher does not have this one
    with pytest.raises(ApiError) as exc_info:
        await dependency(user=dispatcher)
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_role_not_configured_returns_422() -> None:
    async with async_session_factory() as session:
        blank_role_user = User(
            id="usr_blank",
            username="blank",
            password_hash="irrelevant",
            display_name="Blank Role",
            role="",
        )
        session.add(blank_role_user)
        await session.commit()
        token = await create_session(session, "usr_blank")

    with pytest.raises(ApiError) as exc_info:
        await get_current_user(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "ROLE_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_structured_error_envelope_shape_on_real_endpoint() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": "manager", "password": "wrong"})
    assert response.status_code == 401
    body = response.json()
    assert set(body.keys()) == {"error"}
    error = body["error"]
    assert set(error.keys()) == {"code", "message", "trace_id", "details", "retryable"}
    assert error["code"] == "SESSION_EXPIRED"
    assert error["retryable"] is False


@pytest.mark.asyncio
async def test_structured_error_envelope_for_api_error_directly() -> None:
    probe_app = FastAPI()
    register_exception_handlers(probe_app)

    @probe_app.get("/_probe")
    async def _probe() -> None:
        raise ApiError(403, "PERMISSION_DENIED", "no access", details={"needed": "report.export"})

    transport = ASGITransport(app=probe_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/_probe")
    assert response.status_code == 403
    body = response.json()["error"]
    assert body["code"] == "PERMISSION_DENIED"
    assert body["details"] == {"needed": "report.export"}
