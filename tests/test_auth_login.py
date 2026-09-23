"""Tests for POST /api/v1/auth/login and demo user seeding."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.db import async_session_factory
from src.main import app
from src.models.auth import User, UserScope
from src.services.demo_seed import seed_demo_users


async def _seed() -> None:
    async with async_session_factory() as session:
        await seed_demo_users(session)


@pytest.mark.asyncio
async def test_seed_creates_exactly_two_users_with_distinct_scopes() -> None:
    await _seed()
    async with async_session_factory() as session:
        manager = (await session.execute(select(User).where(User.username == "manager"))).scalar_one()
        dispatcher = (await session.execute(select(User).where(User.username == "dispatcher"))).scalar_one()
        assert manager.id == "usr_manager"
        assert dispatcher.id == "usr_dispatcher"

        manager_scope = (
            await session.execute(select(UserScope).where(UserScope.user_id == "usr_manager"))
        ).scalar_one()
        dispatcher_scope = (
            await session.execute(select(UserScope).where(UserScope.user_id == "usr_dispatcher"))
        ).scalar_one()
        assert manager_scope.scope_type == "all_facilities"
        assert dispatcher_scope.scope_type == "assigned_facilities"


@pytest.mark.asyncio
async def test_login_with_correct_credentials_returns_token() -> None:
    await _seed()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login", json={"username": "manager", "password": "manager123"}
        )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["token"], str) and len(body["token"]) > 0


@pytest.mark.asyncio
async def test_login_with_wrong_password_returns_401() -> None:
    await _seed()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login", json={"username": "manager", "password": "wrong"}
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_with_unknown_username_returns_401() -> None:
    await _seed()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login", json={"username": "nobody", "password": "whatever"}
        )
    assert response.status_code == 401
