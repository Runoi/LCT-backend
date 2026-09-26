"""Tests for GET /api/v1/audit -- read-only journal API behind audit.read."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from src.db import async_session_factory
from src.main import app
from src.models.audit import AuditLogEntry
from src.services.demo_seed import seed_demo_users

_BASE_TIME = datetime(2045, 3, 1, 12, 0, tzinfo=timezone.utc)


async def _login(username: str, password: str) -> str:
    async with async_session_factory() as session:
        await seed_demo_users(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["token"]


async def _request(method: str, path: str, token: str, params: dict | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers={"Authorization": f"Bearer {token}"}, params=params)


async def _seed_entries(user_id: str, actions: list[str]) -> None:
    """Journal rows for a unique actor, one minute apart, oldest first."""
    async with async_session_factory() as session:
        for i, action in enumerate(actions):
            session.add(
                AuditLogEntry(
                    occurred_at=_BASE_TIME + timedelta(minutes=i),
                    user_id=user_id,
                    username=user_id,
                    action=action,
                    result="success",
                    status_code=200,
                    ip="127.0.0.1",
                    trace_id=f"tr_{user_id}_{i}",
                )
            )
        await session.commit()


def _unique_user() -> str:
    return f"usr_audit_api_{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_manager_reads_journal_newest_first() -> None:
    actor = _unique_user()
    await _seed_entries(actor, ["POST /a", "POST /b", "POST /c"])
    token = await _login("manager", "manager123")

    response = await _request("GET", "/api/v1/audit", token, {"user_id": actor})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [e["action"] for e in body["data"]] == ["POST /c", "POST /b", "POST /a"]
    assert body["meta"]["total"] == 3
    assert body["meta"]["next_cursor"] is None
    assert set(body["data"][0]) >= {
        "id", "occurred_at", "user_id", "username", "action", "target_type", "target_id",
        "result", "status_code", "ip", "trace_id", "details",
    }


@pytest.mark.asyncio
async def test_dispatcher_cannot_read_journal() -> None:
    token = await _login("dispatcher", "dispatcher123")
    response = await _request("GET", "/api/v1/audit", token)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_action_filter_narrows_results() -> None:
    actor = _unique_user()
    await _seed_entries(actor, ["POST /x", "DELETE /y", "POST /x"])
    token = await _login("manager", "manager123")

    response = await _request("GET", "/api/v1/audit", token, {"user_id": actor, "action": "POST /x"})
    body = response.json()
    assert body["meta"]["total"] == 2
    assert {e["action"] for e in body["data"]} == {"POST /x"}


@pytest.mark.asyncio
async def test_period_filter_is_inclusive_on_both_ends() -> None:
    actor = _unique_user()
    await _seed_entries(actor, ["POST /0", "POST /1", "POST /2", "POST /3"])
    token = await _login("manager", "manager123")

    response = await _request(
        "GET", "/api/v1/audit", token,
        {
            "user_id": actor,
            "from": (_BASE_TIME + timedelta(minutes=1)).isoformat(),
            "to": (_BASE_TIME + timedelta(minutes=2)).isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    assert [e["action"] for e in response.json()["data"]] == ["POST /2", "POST /1"]


@pytest.mark.asyncio
async def test_keyset_pagination_returns_every_entry_exactly_once() -> None:
    actor = _unique_user()
    actions = [f"POST /p{i}" for i in range(5)]
    await _seed_entries(actor, actions)
    token = await _login("manager", "manager123")

    seen: list[int] = []
    cursor = None
    pages = 0
    while True:
        params = {"user_id": actor, "limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = (await _request("GET", "/api/v1/audit", token, params)).json()
        seen.extend(e["id"] for e in body["data"])
        pages += 1
        cursor = body["meta"]["next_cursor"]
        if cursor is None:
            break
        assert pages < 10, "pagination did not terminate"

    assert pages == 3
    assert len(seen) == 5
    assert len(set(seen)) == 5, "no entry may repeat across pages"


@pytest.mark.asyncio
async def test_invalid_cursor_and_date_are_400() -> None:
    token = await _login("manager", "manager123")
    bad_cursor = await _request("GET", "/api/v1/audit", token, {"cursor": "not-a-number"})
    bad_date = await _request("GET", "/api/v1/audit", token, {"from": "yesterday"})
    assert bad_cursor.status_code == 400
    assert bad_date.status_code == 400


@pytest.mark.asyncio
async def test_journal_has_no_write_routes() -> None:
    token = await _login("manager", "manager123")
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = await _request(method, "/api/v1/audit", token)
        assert response.status_code == 405, f"{method} /api/v1/audit must not exist"

    schema = app.openapi()
    assert set(schema["paths"]["/api/v1/audit"]) == {"get"}
