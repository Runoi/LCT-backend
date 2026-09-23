"""Tests for GET /api/v1/risks (leaf 1.3.1.1).

Risk rows are inserted directly (not via sync_risks) for precise control
over priority_score/prediction_window_start/as_of -- this is a unit-style
test of the list endpoint's sort/filter/scope logic, not of sync_risks
(covered separately in test_risk_sync.py).
"""
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


async def _add_risk(
    risk_id: str,
    facility_id: str | None,
    priority_score: float,
    prediction_window_start: datetime,
    *,
    risk_type: str = "fire",
    risk_level: str = "medium",
    decision_status: str = "open",
    as_of: datetime | None = None,
) -> None:
    as_of = as_of or datetime(2037, 1, 1, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        session.add(
            Risk(
                id=risk_id,
                forecast_id=risk_id,
                risk_type=risk_type,
                target_type="sensor",
                target_id=f"sensor_{risk_id}",
                facility_id=facility_id,
                as_of=as_of,
                lead_min_hours=1.0,
                horizon_hours=1.0,
                prediction_window_start=prediction_window_start,
                prediction_window_end=prediction_window_start + timedelta(hours=1),
                probability=0.5,
                threshold=0.3,
                risk_level=risk_level,
                priority_score=priority_score,
                decision_status=decision_status,
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


async def _get(token: str | None, **params):
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/v1/risks", headers=headers, params=params)


@pytest.mark.asyncio
async def test_default_sort_is_priority_desc_then_window_start_asc() -> None:
    await _seed_all()
    base = datetime(2037, 2, 1, tzinfo=timezone.utc)
    await _add_risk("risk_sort_low", "fac_5122", 10.0, base)
    await _add_risk("risk_sort_high", "fac_5122", 30.0, base)
    await _add_risk("risk_sort_mid_later", "fac_5122", 20.0, base + timedelta(hours=2))
    await _add_risk("risk_sort_mid_earlier", "fac_5122", 20.0, base + timedelta(hours=1))

    token = await _login("manager", "manager123")
    response = await _get(token, facility_id="fac_5122")
    ids = [r["id"] for r in response.json()["data"] if r["id"].startswith("risk_sort_")]
    assert ids == ["risk_sort_high", "risk_sort_mid_earlier", "risk_sort_mid_later", "risk_sort_low"]


@pytest.mark.asyncio
async def test_filters_narrow_correctly() -> None:
    await _seed_all()
    base = datetime(2037, 3, 1, tzinfo=timezone.utc)
    await _add_risk("risk_filter_fire", "fac_5122", 10.0, base, risk_type="fire", risk_level="high", decision_status="open")
    await _add_risk("risk_filter_flood", "fac_5122", 10.0, base, risk_type="flooding", risk_level="low", decision_status="acknowledged")

    token = await _login("manager", "manager123")
    # Other test files sharing this database (test_risk_acknowledge.py,
    # test_risk_reject_defer.py, etc.) also create fac_5122/risk_level=high/
    # decision_status=acknowledged rows -- scope every assertion to this
    # test's own "risk_filter_" ids, never an exact-set equality over the
    # whole shared table.
    def _mine(body: dict) -> set[str]:
        return {r["id"] for r in body["data"] if r["id"].startswith("risk_filter_")}

    by_type = await _get(token, facility_id="fac_5122", risk_type="flooding")
    assert _mine(by_type.json()) == {"risk_filter_flood"}

    by_level = await _get(token, facility_id="fac_5122", risk_level="high")
    assert _mine(by_level.json()) == {"risk_filter_fire"}

    by_status = await _get(token, facility_id="fac_5122", decision_status="acknowledged")
    assert _mine(by_status.json()) == {"risk_filter_flood"}


@pytest.mark.asyncio
async def test_date_range_filtering_on_as_of() -> None:
    await _seed_all()
    base = datetime(2037, 4, 1, tzinfo=timezone.utc)
    await _add_risk("risk_daterange_early", "fac_5122", 10.0, base, as_of=datetime(2037, 4, 1, tzinfo=timezone.utc))
    await _add_risk("risk_daterange_late", "fac_5122", 10.0, base, as_of=datetime(2037, 4, 10, tzinfo=timezone.utc))

    token = await _login("manager", "manager123")
    response = await _get(
        token, facility_id="fac_5122",
        **{"from": "2037-04-05T00:00:00+00:00", "to": "2037-04-15T00:00:00+00:00"},
    )
    assert {r["id"] for r in response.json()["data"]} == {"risk_daterange_late"}


@pytest.mark.asyncio
async def test_scope_excludes_risks_outside_assigned_facilities() -> None:
    await _seed_all()
    base = datetime(2037, 5, 1, tzinfo=timezone.utc)
    await _add_risk("risk_scope_assigned", "fac_5122", 10.0, base)
    await _add_risk("risk_scope_unassigned", "fac_20", 10.0, base)

    dispatcher_token = await _login("dispatcher", "dispatcher123")
    response = await _get(dispatcher_token)
    ids = {r["id"] for r in response.json()["data"]}
    assert "risk_scope_assigned" in ids
    assert "risk_scope_unassigned" not in ids


@pytest.mark.asyncio
async def test_risks_requires_authentication() -> None:
    response = await _get(None)
    assert response.status_code == 401
