"""Branch-level check: what the audit middleware records is what an auditor reads back."""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from src.db import async_session_factory
from src.main import app
from src.services.demo_seed import seed_demo_users
from src.services.facility_seed import seed_facility_catalogue


async def _call(method: str, path: str, *, token: str | None = None, json: dict | None = None, params=None):
    transport = ASGITransport(app=app, client=("192.0.2.10", 40000))
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers, json=json, params=params)


async def _login(username: str, password: str) -> str:
    response = await _call("POST", "/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


@pytest.mark.asyncio
async def test_dispatcher_actions_are_readable_by_the_manager() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_demo_users(session)
    started_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()

    failed_login = await _call("POST", "/api/v1/auth/login", json={"username": "dispatcher", "password": "nope"})
    assert failed_login.status_code == 401

    dispatcher = await _login("dispatcher", "dispatcher123")
    denied = await _call(
        "POST", "/api/v1/system/scenarios/fire_smoke_only/activate", token=dispatcher, json={"facility_id": "fac_5122"}
    )
    assert denied.status_code == 403
    created = await _call(
        "POST", "/api/v1/work-orders", token=dispatcher,
        json={
            "mode": "draft", "source_risk_id": None, "facility_id": "fac_5122",
            "target_entity_type": "facility", "target_entity_id": "fac_5122", "work_type": "inspection",
            "priority": "low", "due_at": datetime(2052, 1, 1, tzinfo=timezone.utc).isoformat(),
            "description": "flow test", "comment": None,
        },
    )
    assert created.status_code == 201, created.text

    manager = await _login("manager", "manager123")
    journal = await _call(
        "GET", "/api/v1/audit", token=manager, params={"user_id": "usr_dispatcher", "from": started_at}
    )
    assert journal.status_code == 200, journal.text
    entries = journal.json()["data"]
    assert [(e["action"], e["result"]) for e in entries] == [
        ("POST /api/v1/work-orders", "success"),
        ("POST /api/v1/system/scenarios/{scenario_id}/activate", "denied"),
        ("POST /api/v1/auth/login", "success"),
    ]
    assert entries[0]["target_type"] == "work_order"
    assert entries[0]["target_id"] == created.json()["id"]
    assert entries[1]["trace_id"] == denied.headers["X-Trace-Id"]
    assert all(e["ip"] == "192.0.2.10" for e in entries)

    failed = await _call(
        "GET", "/api/v1/audit", token=manager,
        params={"action": "POST /api/v1/auth/login", "from": started_at},
    )
    failed_entries = [e for e in failed.json()["data"] if e["trace_id"] == failed_login.headers["X-Trace-Id"]]
    assert len(failed_entries) == 1
    assert failed_entries[0]["username"] == "dispatcher"
    assert failed_entries[0]["user_id"] is None
    assert failed_entries[0]["result"] == "denied"

    total_before = (await _call("GET", "/api/v1/audit", token=manager, params={"from": started_at})).json()["meta"]["total"]
    total_after = (await _call("GET", "/api/v1/audit", token=manager, params={"from": started_at})).json()["meta"]["total"]
    assert total_after == total_before, "reading the journal must not add journal entries"
