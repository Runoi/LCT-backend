"""Tests for GET /api/v1/risks/{risk_id} (leaf 1.3.1.2)."""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from src.db import async_session_factory
from src.main import app
from src.models.risk import Risk
from src.services.demo_seed import seed_demo_users
from src.services.facility_seed import seed_facility_catalogue


async def _seed_all() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_demo_users(session)


async def _add_risk(risk_id: str, facility_id: str | None) -> None:
    as_of = datetime(2038, 1, 1, tzinfo=timezone.utc)
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
                probability=0.62,
                threshold=0.3,
                risk_level="high",
                priority_score=55.5,
                decision_status="open",
                sla_due_at=as_of + timedelta(hours=1),
                data_health="fresh",
                model="stub-v1",
                top_factors=["3 тревожных срабатывания за 2 ч"],
                recommendation="do something",
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


async def _get_detail(token: str, risk_id: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(f"/api/v1/risks/{risk_id}", headers={"Authorization": f"Bearer {token}"})


@pytest.mark.asyncio
async def test_detail_includes_every_documented_field_with_nested_shape() -> None:
    await _seed_all()
    await _add_risk("risk_detail_full", "fac_5122")
    token = await _login("manager", "manager123")

    response = await _get_detail(token, "risk_detail_full")
    assert response.status_code == 200
    body = response.json()

    for field in (
        "id", "forecast_id", "risk_type", "target", "as_of", "lead_min_hours", "horizon_hours",
        "prediction_window", "probability", "threshold", "risk_level", "priority_score",
        "decision_status", "sla_due_at", "data_health", "model", "top_factors", "recommendation",
        "version", "created_at", "updated_at",
    ):
        assert field in body, f"missing field: {field}"

    assert body["target"] == {"type": "sensor", "id": "sensor_risk_detail_full", "facility_id": "fac_5122"}
    assert set(body["prediction_window"].keys()) == {"start", "end"}
    assert body["version"] == 1


@pytest.mark.asyncio
async def test_detail_for_nonexistent_risk_returns_404() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _get_detail(token, "risk_does_not_exist")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_detail_for_out_of_scope_risk_returns_403_without_leaking_data() -> None:
    await _seed_all()
    await _add_risk("risk_detail_out_of_scope", "fac_20")  # not assigned to dispatcher
    token = await _login("dispatcher", "dispatcher123")
    response = await _get_detail(token, "risk_detail_out_of_scope")
    assert response.status_code == 403
    assert "fac_20" not in response.text
