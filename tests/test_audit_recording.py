"""The audit middleware journals every mutating API request (TZ section 11)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from src.db import async_session_factory
from src.main import app
from src.models.audit import AuditLogEntry
from src.models.risk import Risk
from src.models.sensor import SensorChannel
from src.services import audit_recorder
from src.services.demo_seed import seed_demo_users
from src.services.facility_seed import seed_facility_catalogue
from src.services.sensor_channel_seed import seed_sensor_channel_catalogue

_CLIENT_IP = "10.20.30.40"


async def _seed_all() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_sensor_channel_catalogue(session)
        await seed_demo_users(session)


async def _call(method: str, path: str, *, token: str | None = None, json: dict | None = None):
    transport = ASGITransport(app=app, client=(_CLIENT_IP, 50000))
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers, json=json)


async def _login(username: str, password: str) -> str:
    response = await _call("POST", "/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


async def _entries_for(response) -> list[AuditLogEntry]:
    trace_id = response.headers["X-Trace-Id"]
    async with async_session_factory() as session:
        return list(
            (await session.execute(select(AuditLogEntry).where(AuditLogEntry.trace_id == trace_id))).scalars().all()
        )


async def _single_entry(response) -> AuditLogEntry:
    entries = await _entries_for(response)
    assert len(entries) == 1, f"expected exactly one journal entry, got {len(entries)}"
    return entries[0]


async def _add_risk(risk_id: str) -> None:
    as_of = datetime(2041, 1, 1, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        session.add(
            Risk(
                id=risk_id, forecast_id=risk_id, risk_type="fire", target_type="sensor",
                target_id=f"sensor_{risk_id}", facility_id="fac_5122", as_of=as_of,
                lead_min_hours=2.0, horizon_hours=6.0,
                prediction_window_start=as_of + timedelta(hours=2),
                prediction_window_end=as_of + timedelta(hours=8),
                probability=0.6, threshold=0.3, risk_level="high", priority_score=50.0,
                decision_status="open", sla_due_at=as_of + timedelta(hours=1), data_health="fresh",
                model="test", top_factors=["f"], recommendation="r", version=1,
                created_at=as_of, updated_at=as_of,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_failed_login_is_journaled_with_submitted_username() -> None:
    await _seed_all()
    username = f"audit_nobody_{uuid.uuid4().hex[:8]}"
    response = await _call("POST", "/api/v1/auth/login", json={"username": username, "password": "wrong"})
    assert response.status_code == 401

    entry = await _single_entry(response)
    assert entry.action == "POST /api/v1/auth/login"
    assert entry.username == username
    assert entry.user_id is None
    assert entry.result == "denied"
    assert entry.status_code == 401
    assert entry.ip == _CLIENT_IP
    assert entry.trace_id == response.json()["error"]["trace_id"], "error body and journal must share trace_id"


@pytest.mark.asyncio
async def test_successful_login_is_journaled_with_user_id() -> None:
    await _seed_all()
    response = await _call("POST", "/api/v1/auth/login", json={"username": "manager", "password": "manager123"})
    assert response.status_code == 200

    entry = await _single_entry(response)
    assert entry.user_id == "usr_manager"
    assert entry.username == "manager"
    assert entry.result == "success"
    assert entry.status_code == 200


@pytest.mark.asyncio
async def test_risk_acknowledge_is_journaled_with_risk_target() -> None:
    await _seed_all()
    risk_id = f"risk_audit_{uuid.uuid4().hex[:8]}"
    await _add_risk(risk_id)
    token = await _login("manager", "manager123")

    response = await _call("POST", f"/api/v1/risks/{risk_id}/acknowledge", token=token, json={"expected_version": 1})
    assert response.status_code == 200, response.text

    entry = await _single_entry(response)
    assert entry.action == "POST /api/v1/risks/{risk_id}/acknowledge"
    assert (entry.target_type, entry.target_id) == ("risk", risk_id)
    assert entry.user_id == "usr_manager"
    assert entry.result == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "body"),
    [
        ("reject", {"expected_version": 1, "reason_code": "false_alarm"}),
        ("defer", {"expected_version": 1}),
    ],
)
async def test_risk_reject_and_defer_are_journaled(decision: str, body: dict) -> None:
    await _seed_all()
    risk_id = f"risk_audit_{decision}_{uuid.uuid4().hex[:8]}"
    await _add_risk(risk_id)
    token = await _login("manager", "manager123")

    response = await _call("POST", f"/api/v1/risks/{risk_id}/{decision}", token=token, json=body)
    assert response.status_code == 200, response.text

    entry = await _single_entry(response)
    assert entry.action == f"POST /api/v1/risks/{{risk_id}}/{decision}"
    assert (entry.target_type, entry.target_id) == ("risk", risk_id)
    assert entry.result == "success"


@pytest.mark.asyncio
async def test_work_order_creation_targets_the_created_order() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    body = {
        "mode": "draft", "source_risk_id": None, "facility_id": "fac_5122",
        "target_entity_type": "sensor", "target_entity_id": "sensor_audit", "work_type": "inspection",
        "priority": "medium", "due_at": datetime(2051, 1, 1, tzinfo=timezone.utc).isoformat(),
        "description": "audit test", "comment": None,
    }
    response = await _call("POST", "/api/v1/work-orders", token=token, json=body)
    assert response.status_code == 201, response.text

    entry = await _single_entry(response)
    assert entry.action == "POST /api/v1/work-orders"
    assert (entry.target_type, entry.target_id) == ("work_order", response.json()["id"])
    assert entry.details == {"facility_id": "fac_5122"}


@pytest.mark.asyncio
async def test_scenario_activation_records_facility_in_details() -> None:
    await _seed_all()
    async with async_session_factory() as session:
        facility_id = (
            await session.execute(
                select(SensorChannel.facility_id)
                .where(SensorChannel.sensor_type_id == "smoke_detector", SensorChannel.facility_id.isnot(None))
                .limit(1)
            )
        ).scalar_one()
    token = await _login("manager", "manager123")

    response = await _call(
        "POST", "/api/v1/system/scenarios/fire_smoke_only/activate", token=token,
        json={"facility_id": facility_id, "seed": 3},
    )
    assert response.status_code == 200, response.text

    entry = await _single_entry(response)
    assert (entry.target_type, entry.target_id) == ("scenario", "fire_smoke_only")
    assert entry.details == {"facility_id": facility_id}


@pytest.mark.asyncio
async def test_degrade_and_clear_are_journaled_against_the_source() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")

    degrade = await _call(
        "POST", "/api/v1/system/source-health/ods_journal/degrade", token=token,
        json={"status": "delayed", "duration_seconds": 30},
    )
    clear = await _call("DELETE", "/api/v1/system/source-health/ods_journal/degrade", token=token)
    assert (degrade.status_code, clear.status_code) == (204, 204)

    degrade_entry = await _single_entry(degrade)
    clear_entry = await _single_entry(clear)
    assert degrade_entry.action == "POST /api/v1/system/source-health/{source}/degrade"
    assert clear_entry.action == "DELETE /api/v1/system/source-health/{source}/degrade"
    for entry in (degrade_entry, clear_entry):
        assert (entry.target_type, entry.target_id) == ("source", "ods_journal")
        assert entry.result == "success"


@pytest.mark.asyncio
async def test_permission_denial_is_journaled_as_denied() -> None:
    await _seed_all()
    token = await _login("dispatcher", "dispatcher123")
    response = await _call(
        "POST", "/api/v1/system/source-health/smvu/degrade", token=token,
        json={"status": "delayed", "duration_seconds": 30},
    )
    assert response.status_code == 403

    entry = await _single_entry(response)
    assert entry.user_id == "usr_dispatcher"
    assert entry.result == "denied"
    assert entry.status_code == 403


@pytest.mark.asyncio
async def test_get_requests_are_not_journaled() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _call("GET", "/api/v1/me", token=token)
    assert response.status_code == 200
    assert "X-Trace-Id" in response.headers
    assert await _entries_for(response) == []


@pytest.mark.asyncio
async def test_journal_never_contains_password_or_token() -> None:
    await _seed_all()
    secret_password = f"Secret-{uuid.uuid4().hex}"
    await _call("POST", "/api/v1/auth/login", json={"username": "manager", "password": secret_password})
    token = await _login("manager", "manager123")
    await _call(
        "POST", "/api/v1/system/source-health/smvu/degrade", token=token,
        json={"status": "delayed", "duration_seconds": 30},
    )

    async with async_session_factory() as session:
        entries = (await session.execute(select(AuditLogEntry))).scalars().all()
    serialized = " ".join(
        repr((e.user_id, e.username, e.action, e.target_type, e.target_id, e.ip, e.trace_id, e.details))
        for e in entries
    )
    assert entries, "journal should not be empty here"
    assert secret_password not in serialized
    assert token not in serialized


@pytest.mark.asyncio
async def test_journal_write_failure_does_not_break_the_response(monkeypatch: pytest.MonkeyPatch) -> None:
    await _seed_all()

    async def _broken_write(_: AuditLogEntry) -> None:
        raise SQLAlchemyError("simulated journal outage")

    monkeypatch.setattr(audit_recorder, "write_audit_entry", _broken_write)
    response = await _call("POST", "/api/v1/auth/login", json={"username": "manager", "password": "manager123"})
    assert response.status_code == 200, response.text
    assert response.json()["token"]
