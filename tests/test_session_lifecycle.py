"""Session expiry (SESSION_TTL_MINUTES) and POST /api/v1/auth/logout."""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.config import get_settings
from src.db import async_session_factory
from src.main import app
from src.models.audit import AuditLogEntry
from src.models.auth import UserSession
from src.services.auth_service import create_session, get_active_session_user
from src.services.demo_seed import seed_demo_users


async def _seed() -> None:
    async with async_session_factory() as session:
        await seed_demo_users(session)


async def _call(method: str, path: str, token: str | None = None):
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers)


async def _login(username: str, password: str) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


@pytest.mark.asyncio
async def test_new_session_expires_after_configured_ttl() -> None:
    await _seed()
    issued_at = datetime(2046, 5, 1, 8, 0, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        token = await create_session(session, "usr_manager", now=issued_at)
        row = (await session.execute(select(UserSession).where(UserSession.token == token))).scalar_one()
    assert row.expires_at == issued_at + timedelta(minutes=get_settings().session_ttl_minutes)


@pytest.mark.asyncio
async def test_token_is_valid_until_expiry_and_invalid_after() -> None:
    await _seed()
    issued_at = datetime(2046, 5, 1, 8, 0, tzinfo=timezone.utc)
    ttl = timedelta(minutes=get_settings().session_ttl_minutes)
    async with async_session_factory() as session:
        token = await create_session(session, "usr_manager", now=issued_at)
        just_before = await get_active_session_user(session, token, now=issued_at + ttl - timedelta(seconds=1))
        at_expiry = await get_active_session_user(session, token, now=issued_at + ttl)
    assert just_before is not None and just_before.id == "usr_manager"
    assert at_expiry is None


@pytest.mark.asyncio
async def test_expired_token_is_rejected_over_http() -> None:
    await _seed()
    ttl = timedelta(minutes=get_settings().session_ttl_minutes)
    async with async_session_factory() as session:
        expired = await create_session(session, "usr_manager", now=datetime.now(timezone.utc) - ttl - timedelta(minutes=1))
        fresh = await create_session(session, "usr_manager")

    expired_response = await _call("GET", "/api/v1/me", expired)
    fresh_response = await _call("GET", "/api/v1/me", fresh)
    assert expired_response.status_code == 401
    assert expired_response.json()["error"]["code"] == "SESSION_EXPIRED"
    assert fresh_response.status_code == 200


@pytest.mark.asyncio
async def test_logout_revokes_the_token_immediately() -> None:
    await _seed()
    token = await _login("dispatcher", "dispatcher123")
    assert (await _call("GET", "/api/v1/me", token)).status_code == 200

    logout = await _call("POST", "/api/v1/auth/logout", token)
    assert logout.status_code == 204

    after = await _call("GET", "/api/v1/me", token)
    assert after.status_code == 401
    assert (await _call("POST", "/api/v1/auth/logout", token)).status_code == 401


@pytest.mark.asyncio
async def test_logout_does_not_touch_other_sessions_of_the_same_user() -> None:
    await _seed()
    first = await _login("dispatcher", "dispatcher123")
    second = await _login("dispatcher", "dispatcher123")
    assert (await _call("POST", "/api/v1/auth/logout", first)).status_code == 204
    assert (await _call("GET", "/api/v1/me", second)).status_code == 200


@pytest.mark.asyncio
async def test_logout_without_valid_token_is_401() -> None:
    assert (await _call("POST", "/api/v1/auth/logout")).status_code == 401
    assert (await _call("POST", "/api/v1/auth/logout", "not-a-real-token")).status_code == 401


@pytest.mark.asyncio
async def test_logout_is_journaled_with_the_actor() -> None:
    await _seed()
    token = await _login("dispatcher", "dispatcher123")
    response = await _call("POST", "/api/v1/auth/logout", token)
    assert response.status_code == 204

    async with async_session_factory() as session:
        entries = (
            await session.execute(
                select(AuditLogEntry).where(AuditLogEntry.trace_id == response.headers["X-Trace-Id"])
            )
        ).scalars().all()
    assert len(entries) == 1
    assert entries[0].action == "POST /api/v1/auth/logout"
    assert entries[0].user_id == "usr_dispatcher"
    assert entries[0].result == "success"


@pytest.mark.asyncio
async def test_directly_inserted_session_still_gets_an_expiry() -> None:
    await _seed()
    before = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        session.add(UserSession(token="tok_direct_insert_expiry", user_id="usr_manager"))
        await session.commit()
        row = (
            await session.execute(select(UserSession).where(UserSession.token == "tok_direct_insert_expiry"))
        ).scalar_one()
    ttl = timedelta(minutes=get_settings().session_ttl_minutes)
    assert before + ttl - timedelta(seconds=5) <= row.expires_at <= datetime.now(timezone.utc) + ttl
