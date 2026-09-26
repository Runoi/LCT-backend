"""Brute-force protection on POST /api/v1/auth/login.

Every test uses its own username and client IP so the shared test database
(and its per-IP counters) cannot leak between tests.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from src.config import get_settings
from src.db import async_session_factory
from src.main import app
from src.models.audit import AuditLogEntry
from src.models.auth import User, UserPermission, UserScope
from src.models.login_failure import LoginFailure
from src.services.auth_service import hash_password

_PASSWORD = "Correct-horse-1"


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _unique_ip() -> str:
    raw = uuid.uuid4().int
    return f"10.{raw % 250 + 1}.{(raw >> 8) % 250 + 1}.{(raw >> 16) % 250 + 1}"


async def _seed_user(username: str) -> None:
    async with async_session_factory() as session:
        session.add(
            User(id=f"usr_{username}", username=username, password_hash=hash_password(_PASSWORD),
                 display_name=username, role="test")
        )
        session.add(UserPermission(user_id=f"usr_{username}", permission="risk.read"))
        session.add(UserScope(user_id=f"usr_{username}", scope_type="all_facilities"))
        await session.commit()


async def _login(username: str, password: str, ip: str):
    transport = ASGITransport(app=app, client=(ip, 51000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/api/v1/auth/login", json={"username": username, "password": password})


async def _failure_count(username: str) -> int:
    async with async_session_factory() as session:
        return (
            await session.execute(select(func.count()).select_from(LoginFailure).where(LoginFailure.username == username))
        ).scalar_one()


def _limit() -> int:
    return get_settings().login_max_failures_per_username


@pytest.mark.asyncio
async def test_lockout_after_limit_refuses_even_the_correct_password() -> None:
    username, ip = _unique("throttle"), _unique_ip()
    await _seed_user(username)

    for _ in range(_limit()):
        assert (await _login(username, "wrong", ip)).status_code == 401

    locked = await _login(username, "wrong", ip)
    assert locked.status_code == 429, locked.text
    error = locked.json()["error"]
    assert error["code"] == "TOO_MANY_REQUESTS"
    assert error["retryable"] is True
    assert 0 < error["details"]["retry_after_seconds"] <= get_settings().login_failure_window_seconds

    correct_while_locked = await _login(username, _PASSWORD, ip)
    assert correct_while_locked.status_code == 429, "correct password must not bypass the lock"


@pytest.mark.asyncio
async def test_refused_attempts_do_not_extend_the_lock() -> None:
    username, ip = _unique("throttle"), _unique_ip()
    for _ in range(_limit()):
        await _login(username, "wrong", ip)
    before = await _failure_count(username)
    assert (await _login(username, "wrong", ip)).status_code == 429
    assert await _failure_count(username) == before


@pytest.mark.asyncio
async def test_failures_outside_the_window_do_not_lock() -> None:
    username, ip = _unique("throttle"), _unique_ip()
    await _seed_user(username)
    stale = datetime.now(timezone.utc) - timedelta(seconds=get_settings().login_failure_window_seconds + 60)
    async with async_session_factory() as session:
        for _ in range(_limit()):
            session.add(LoginFailure(username=username, ip=ip, occurred_at=stale))
        await session.commit()

    response = await _login(username, _PASSWORD, ip)
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_success_resets_the_username_counter() -> None:
    username, ip = _unique("throttle"), _unique_ip()
    await _seed_user(username)
    for _ in range(_limit() - 1):
        await _login(username, "wrong", ip)
    assert (await _login(username, _PASSWORD, ip)).status_code == 200
    assert await _failure_count(username) == 0

    for _ in range(_limit() - 1):
        assert (await _login(username, "wrong", ip)).status_code == 401
    assert (await _login(username, _PASSWORD, ip)).status_code == 200, "counter must have restarted from zero"


@pytest.mark.asyncio
async def test_per_ip_limit_locks_different_usernames_from_one_ip() -> None:
    ip = _unique_ip()
    for _ in range(get_settings().login_max_failures_per_ip):
        assert (await _login(_unique("spray"), "wrong", ip)).status_code == 401

    fresh_username = _unique("spray")
    response = await _login(fresh_username, "wrong", ip)
    assert response.status_code == 429, "per-IP limit must lock a never-seen username from the same IP"

    other_ip = await _login(fresh_username, "wrong", _unique_ip())
    assert other_ip.status_code == 401, "the same username from another IP is not locked by the IP counter"


@pytest.mark.asyncio
async def test_unknown_username_is_indistinguishable() -> None:
    real, unknown, ip = _unique("throttle"), _unique("ghost"), _unique_ip()
    await _seed_user(real)

    real_body = (await _login(real, "wrong", ip)).json()["error"]
    unknown_body = (await _login(unknown, "wrong", _unique_ip())).json()["error"]
    for key in ("code", "message", "details", "retryable"):
        assert real_body[key] == unknown_body[key], f"401 differs in {key}"

    ghost_ip = _unique_ip()
    for _ in range(_limit()):
        await _login(unknown, "wrong", ghost_ip)
    locked = await _login(unknown, "wrong", ghost_ip)
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "TOO_MANY_REQUESTS"


@pytest.mark.asyncio
async def test_lockout_is_journaled_as_denied() -> None:
    username, ip = _unique("throttle"), _unique_ip()
    for _ in range(_limit()):
        await _login(username, "wrong", ip)
    locked = await _login(username, "wrong", ip)
    assert locked.status_code == 429

    async with async_session_factory() as session:
        entry = (
            await session.execute(select(AuditLogEntry).where(AuditLogEntry.trace_id == locked.headers["X-Trace-Id"]))
        ).scalar_one()
    assert entry.action == "POST /api/v1/auth/login"
    assert entry.username == username
    assert entry.user_id is None
    assert entry.result == "denied"
    assert entry.status_code == 429
    assert entry.details == {"reason": "locked_out"}
    assert entry.ip == ip
