import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import delete, select

from src.db import async_session_factory
from src.models.hierarchy import Facility
from src.models.risk import Risk
from src.services.object_risk_sync import ObjectRiskError, incident_risk_type, sync_object_risks

NOW = datetime(2037, 3, 1, tzinfo=timezone.utc)


def _row(object_id: str, alert: bool, probability: float, suspects: list[dict], model: str = "hgb-object-test") -> dict:
    return {
        "status": "ok",
        "object_id": object_id,
        "alert": alert,
        "probability": probability,
        "model_name": model,
        "top_factors": [{"text": f"factor of {object_id}", "contribution_log_odds": 1.0}],
        "suspect_channels": suspects,
    }


def _ml_service(tag: str, calls: list[dict], status: int = 200) -> httpx.AsyncClient:
    maps = {
        "incident": {
            "horizon_hours": 72,
            "objects": [
                _row(f"{tag}_smoke", True, 0.9, [{"target_id": "sensor_1", "sensor_type": "Датчик дыма"}]),
                _row(f"{tag}_pump", True, 0.7, [{"target_id": "sensor_2", "sensor_type": "Состояние насоса"}]),
                _row(f"{tag}_quiet", False, 0.2, []),
                _row(f"{tag}_missing", True, 0.8, []),
                {"status": "insufficient_data", "reason": "no_eligible_channels", "object_id": f"{tag}_smoke"},
            ],
        },
        "failure": {"horizon_hours": 168, "objects": [_row(f"{tag}_quiet", True, 0.62, [{"target_id": "sensor_3", "sensor_type": "ИБП"}], "hgb-failure-test")]},
    }

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if status != 200:
            return httpx.Response(status, text="boom")
        return httpx.Response(200, json=maps[body["target"]])

    return httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://ml")


async def _seed_facilities(tag: str) -> None:
    async with async_session_factory() as session:
        await session.execute(delete(Risk).where(Risk.target_id.like(f"fac_{tag}_%")))
        for suffix in ("smoke", "pump", "quiet"):
            facility_id = f"fac_{tag}_{suffix}"
            if await session.get(Facility, facility_id) is None:
                session.add(Facility(id=facility_id, display_name=facility_id, facility_type="test", district_id=None))
        await session.commit()


async def _risks(tag: str) -> list[Risk]:
    async with async_session_factory() as session:
        rows = await session.execute(select(Risk).where(Risk.target_id.like(f"fac_{tag}_%")).order_by(Risk.target_id, Risk.risk_type))
        return list(rows.scalars().all())


def test_incident_risk_type_takes_first_mapped_suspect() -> None:
    assert incident_risk_type([{"sensor_type": "ИБП"}, {"sensor_type": "КД Дверь"}]) == "unauthorized_access"
    assert incident_risk_type([{"sensor_type": "Датчик затопления"}]) == "flooding"
    assert incident_risk_type([{"sensor_type": "Тепловой датчик"}]) == "fire"
    assert incident_risk_type([{"sensor_type": None}]) == "unauthorized_access"


@pytest.mark.asyncio
async def test_alerted_objects_become_facility_risks() -> None:
    tag = "ors_alerts"
    await _seed_facilities(tag)
    calls: list[dict] = []
    async with _ml_service(tag, calls) as client, async_session_factory() as session:
        created = await sync_object_risks(session, client, now=NOW)

    assert created == 3
    assert [c["target"] for c in calls] == ["incident", "failure"]
    assert all(c["as_of"] == NOW.isoformat() for c in calls)
    risks = {(r.target_id, r.risk_type): r for r in await _risks(tag)}
    assert set(risks) == {(f"fac_{tag}_smoke", "fire"), (f"fac_{tag}_pump", "flooding"), (f"fac_{tag}_quiet", "sensor_failure")}
    smoke = risks[(f"fac_{tag}_smoke", "fire")]
    assert (smoke.target_type, smoke.facility_id, smoke.probability, smoke.horizon_hours) == ("facility", f"fac_{tag}_smoke", 0.9, 72.0)
    assert smoke.prediction_window_end - smoke.prediction_window_start == timedelta(hours=72)
    assert smoke.top_factors == [f"factor of {tag}_smoke"]
    assert "sensor_1" in smoke.recommendation
    assert risks[(f"fac_{tag}_quiet", "sensor_failure")].horizon_hours == 168.0


@pytest.mark.asyncio
async def test_second_sync_skips_objects_with_an_open_risk() -> None:
    tag = "ors_repeat"
    await _seed_facilities(tag)
    async with _ml_service(tag, []) as client, async_session_factory() as session:
        assert await sync_object_risks(session, client, now=NOW) == 3
    async with _ml_service(tag, []) as client, async_session_factory() as session:
        assert await sync_object_risks(session, client, now=NOW + timedelta(hours=1)) == 0
    async with _ml_service(tag, []) as client, async_session_factory() as session:
        assert await sync_object_risks(session, client, now=NOW + timedelta(hours=80)) == 2
    assert len(await _risks(tag)) == 5


@pytest.mark.asyncio
async def test_ml_error_raises_and_writes_nothing() -> None:
    tag = "ors_error"
    await _seed_facilities(tag)
    async with _ml_service(tag, [], status=500) as client, async_session_factory() as session:
        with pytest.raises(ObjectRiskError):
            await sync_object_risks(session, client, now=NOW)
    assert await _risks(tag) == []


@pytest.mark.asyncio
async def test_malformed_alert_row_raises_object_risk_error_and_writes_nothing() -> None:
    tag = "ors_malformed"
    await _seed_facilities(tag)

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        broken = {"status": "ok", "object_id": f"{tag}_smoke", "alert": True, "model_name": "m"}  # no probability
        return httpx.Response(200, json={"horizon_hours": 72, "objects": [broken]} if body["target"] == "incident" else {"horizon_hours": 168, "objects": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://ml")
    async with client, async_session_factory() as session:
        with pytest.raises(ObjectRiskError):
            await sync_object_risks(session, client, now=NOW)
    assert await _risks(tag) == []
