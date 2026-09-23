"""Tests for GET /health against a live database and a simulated outage."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from src.db import get_session
from src.main import app


class _BrokenSession:
    """Fake session whose execute() always raises, simulating a dead database."""

    async def execute(self, *args: object, **kwargs: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


async def _broken_session():
    yield _BrokenSession()


@pytest.mark.asyncio
async def test_health_returns_ok_when_database_is_reachable() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200, "expected 200 when the database is reachable"
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_returns_503_when_database_is_unavailable() -> None:
    app.dependency_overrides[get_session] = _broken_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 503, "expected 503 when the database is unreachable"
    assert response.json() == {"status": "unavailable"}
