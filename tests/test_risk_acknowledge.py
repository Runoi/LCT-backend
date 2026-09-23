"""Tests for POST /api/v1/risks/{risk_id}/acknowledge (leaf 1.3.2.1)."""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.db import async_session_factory
from src.main import app
from src.models.auth import User, UserPermission, UserScope, UserScopeFacility
from src.models.risk import Risk, RiskDecision
from src.services.auth_service import hash_password
from src.services.demo_seed import seed_demo_users
from src.services.facility_seed import seed_facility_catalogue


async def _seed_all() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_demo_users(session)


async def _seed_read_only_user() -> None:
    """A user with risk.read but NOT risk.acknowledge -- a real 403 case."""
    async with async_session_factory() as session:
        if await session.get(User, "usr_risk_read_only") is not None:
            return
        session.add(
            User(
                id="usr_risk_read_only",
                username="risk_read_only",
                password_hash=hash_password("readonly123"),
                display_name="Read-only (test)",
                role="test",
            )
        )
        session.add(UserPermission(user_id="usr_risk_read_only", permission="risk.read"))
        session.add(UserScope(user_id="usr_risk_read_only", scope_type="all_facilities"))
        await session.commit()


async def _add_risk(risk_id: str, facility_id: str | None, *, version: int = 1) -> None:
    as_of = datetime(2040, 1, 1, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        session.add(
            Risk(
                id=risk_id,
                forecast_id=risk_id,
                risk_type="fire",
                target_type="sensor",
                target_id=f"sensor_{risk_id}",
                facility_id=facility_id,
                as_of=as_of,
                lead_min_hours=2.0,
                horizon_hours=6.0,
                prediction_window_start=as_of + timedelta(hours=2),
                prediction_window_end=as_of + timedelta(hours=8),
                probability=0.6,
                threshold=0.3,
                risk_level="high",
                priority_score=50.0,
                decision_status="open",
                sla_due_at=as_of + timedelta(hours=1),
                data_health="fresh",
                model="test",
                top_factors=["f"],
                recommendation="r",
                version=version,
                created_at=as_of,
                updated_at=as_of,
            )
        )
        await session.commit()


async def _login(username: str, password: str) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["token"]


async def _acknowledge(token: str, risk_id: str, expected_version: int):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            f"/api/v1/risks/{risk_id}/acknowledge",
            headers={"Authorization": f"Bearer {token}"},
            json={"expected_version": expected_version},
        )


@pytest.mark.asyncio
async def test_acknowledge_succeeds_increments_version_and_journals() -> None:
    await _seed_all()
    await _add_risk("risk_ack_success", "fac_5122")
    token = await _login("manager", "manager123")

    response = await _acknowledge(token, "risk_ack_success", 1)
    assert response.status_code == 200
    body = response.json()
    assert body["decision_status"] == "acknowledged"
    assert body["version"] == 2

    async with async_session_factory() as session:
        decisions = (
            await session.execute(select(RiskDecision).where(RiskDecision.risk_id == "risk_ack_success"))
        ).scalars().all()
    assert len(decisions) == 1
    assert decisions[0].decision == "acknowledged"


@pytest.mark.asyncio
async def test_stale_expected_version_returns_409_with_current_state() -> None:
    await _seed_all()
    await _add_risk("risk_ack_conflict", "fac_5122")
    token = await _login("manager", "manager123")

    first = await _acknowledge(token, "risk_ack_conflict", 1)
    assert first.status_code == 200

    stale_retry = await _acknowledge(token, "risk_ack_conflict", 1)  # still using the old version
    assert stale_retry.status_code == 409
    current = stale_retry.json()["error"]["details"]["current"]
    assert current["version"] == 2
    assert current["decision_status"] == "acknowledged"


@pytest.mark.asyncio
async def test_caller_without_risk_acknowledge_permission_gets_403() -> None:
    await _seed_all()
    await _seed_read_only_user()
    await _add_risk("risk_ack_no_permission", None)
    token = await _login("risk_read_only", "readonly123")

    response = await _acknowledge(token, "risk_ack_no_permission", 1)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_caller_outside_facility_scope_gets_403() -> None:
    await _seed_all()
    await _add_risk("risk_ack_out_of_scope", "fac_20")  # not assigned to dispatcher
    token = await _login("dispatcher", "dispatcher123")

    response = await _acknowledge(token, "risk_ack_out_of_scope", 1)
    assert response.status_code == 403
