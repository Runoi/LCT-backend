"""Tests for POST /api/v1/risks/{risk_id}/reject and .../defer (leaf 1.3.2.2)."""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.db import async_session_factory
from src.main import app
from src.models.risk import Risk, RiskDecision
from src.services.demo_seed import seed_demo_users
from src.services.facility_seed import seed_facility_catalogue


async def _seed_all() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_demo_users(session)


async def _add_risk(risk_id: str, facility_id: str | None) -> None:
    as_of = datetime(2041, 1, 1, tzinfo=timezone.utc)
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
                version=1,
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


async def _reject(token: str, risk_id: str, body: dict):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            f"/api/v1/risks/{risk_id}/reject", headers={"Authorization": f"Bearer {token}"}, json=body
        )


async def _defer(token: str, risk_id: str, body: dict):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            f"/api/v1/risks/{risk_id}/defer", headers={"Authorization": f"Bearer {token}"}, json=body
        )


@pytest.mark.asyncio
async def test_reject_without_reason_code_is_422() -> None:
    await _seed_all()
    await _add_risk("risk_reject_no_reason", "fac_5122")
    token = await _login("manager", "manager123")
    response = await _reject(token, "risk_reject_no_reason", {"expected_version": 1})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_other_without_comment_is_422() -> None:
    await _seed_all()
    await _add_risk("risk_reject_other_no_comment", "fac_5122")
    token = await _login("manager", "manager123")
    response = await _reject(
        token, "risk_reject_other_no_comment", {"expected_version": 1, "reason_code": "other"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_with_other_and_comment_succeeds() -> None:
    await _seed_all()
    await _add_risk("risk_reject_other_with_comment", "fac_5122")
    token = await _login("manager", "manager123")
    response = await _reject(
        token, "risk_reject_other_with_comment",
        {"expected_version": 1, "reason_code": "other", "comment": "ложное срабатывание из-за пыли"},
    )
    assert response.status_code == 200
    assert response.json()["decision_status"] == "rejected"

    async with async_session_factory() as session:
        decision = (
            await session.execute(
                select(RiskDecision).where(RiskDecision.risk_id == "risk_reject_other_with_comment")
            )
        ).scalar_one()
    assert decision.reason_code == "other"
    assert decision.comment == "ложное срабатывание из-за пыли"


@pytest.mark.asyncio
async def test_reject_with_valid_non_other_reason_needs_no_comment() -> None:
    await _seed_all()
    await _add_risk("risk_reject_false_alarm", "fac_5122")
    token = await _login("manager", "manager123")
    response = await _reject(
        token, "risk_reject_false_alarm", {"expected_version": 1, "reason_code": "false_alarm"}
    )
    assert response.status_code == 200
    assert response.json()["decision_status"] == "rejected"


@pytest.mark.asyncio
async def test_defer_succeeds_without_reason_code() -> None:
    await _seed_all()
    await _add_risk("risk_defer_success", "fac_5122")
    token = await _login("manager", "manager123")
    response = await _defer(token, "risk_defer_success", {"expected_version": 1})
    assert response.status_code == 200
    assert response.json()["decision_status"] == "deferred"


@pytest.mark.asyncio
async def test_dispatcher_lacks_risk_resolve_and_gets_403_on_reject_and_defer() -> None:
    await _seed_all()
    await _add_risk("risk_dispatcher_reject", "fac_5122")
    await _add_risk("risk_dispatcher_defer", "fac_5122")
    token = await _login("dispatcher", "dispatcher123")

    reject_response = await _reject(
        token, "risk_dispatcher_reject", {"expected_version": 1, "reason_code": "false_alarm"}
    )
    assert reject_response.status_code == 403

    defer_response = await _defer(token, "risk_dispatcher_defer", {"expected_version": 1})
    assert defer_response.status_code == 403
