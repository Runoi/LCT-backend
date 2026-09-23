"""Tests for GET /api/v1/sensors/{sensor_id}/series (numeric)."""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from src.db import async_session_factory
from src.main import app
from src.models.sensor import SensorChannel, SensorReading
from src.services.demo_seed import seed_demo_users
from src.services.facility_seed import seed_facility_catalogue
from src.services.sensor_channel_seed import seed_sensor_channel_catalogue


async def _seed_all() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_sensor_channel_catalogue(session)
        await seed_demo_users(session)


async def _seed_numeric_test_channel(suffix: str, facility_id: str):
    # A dedicated, non-catalogue channel: a real catalogue channel can
    # already carry real readings from test_event_etl.py's ingest of the
    # real operational-window file once the whole suite shares one
    # database, which would silently corrupt these bucket/gap assertions.
    channel_id = f"test_series_{suffix}"
    sensor_id = f"sensor_{channel_id}"
    async with async_session_factory() as session:
        session.add(
            SensorChannel(
                id=sensor_id,
                channel_id=channel_id,
                tag="",
                sensor_type_id="temperature_sensor",
                system_type="temperature",
                display_name=f"Test numeric sensor {suffix}",
                facility_id=facility_id,
                hierarchy_node_id=f"node_{facility_id}",
            )
        )
        await session.commit()
    return sensor_id, channel_id


async def _add_readings(channel_id: str, readings: list[tuple[datetime, float]]) -> None:
    async with async_session_factory() as session:
        for occurred_at, value in readings:
            session.add(
                SensorReading(
                    channel_id=channel_id,
                    occurred_at=occurred_at,
                    is_alarm=False,
                    raw_value=str(value),
                    numeric_value=value,
                    is_anomaly=False,
                    source_event_id=f"evt_{occurred_at.isoformat()}_{value}",
                )
            )
        await session.commit()


async def _login(username: str, password: str) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["token"]


async def _get_series(token: str, sensor_id: str, **params):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(
            f"/api/v1/sensors/{sensor_id}/series", headers={"Authorization": f"Bearer {token}"}, params=params
        )


@pytest.mark.asyncio
async def test_raw_points_returned_in_chronological_order() -> None:
    await _seed_all()
    sensor_id, channel_id = await _seed_numeric_test_channel("1", "fac_5122")
    base = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
    await _add_readings(channel_id, [(base, 20.0), (base + timedelta(minutes=10), 21.0), (base + timedelta(minutes=20), 22.0)])

    token = await _login("dispatcher", "dispatcher123")
    response = await _get_series(token, sensor_id)
    assert response.status_code == 200
    body = response.json()
    assert body["value_type"] == "numeric"
    assert [p["value"] for p in body["points"]] == [20.0, 21.0, 22.0]
    assert body["thresholds"] == []


@pytest.mark.asyncio
async def test_granularity_bucketing_averages_correctly() -> None:
    await _seed_all()
    sensor_id, channel_id = await _seed_numeric_test_channel("2", "fac_5122")
    base = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
    # two readings in the same 1h bucket, one in the next
    await _add_readings(
        channel_id,
        [(base, 10.0), (base + timedelta(minutes=30), 20.0), (base + timedelta(hours=1, minutes=5), 100.0)],
    )

    token = await _login("dispatcher", "dispatcher123")
    response = await _get_series(token, sensor_id, granularity="1h")
    body = response.json()
    assert len(body["points"]) == 2
    assert body["points"][0]["value"] == 15.0  # average of 10.0 and 20.0
    assert body["points"][1]["value"] == 100.0


@pytest.mark.asyncio
async def test_gap_over_one_hour_appears_in_missing_intervals() -> None:
    await _seed_all()
    sensor_id, channel_id = await _seed_numeric_test_channel("3", "fac_5339")
    base = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
    await _add_readings(channel_id, [(base, 20.0), (base + timedelta(hours=2), 21.0)])

    token = await _login("dispatcher", "dispatcher123")
    response = await _get_series(token, sensor_id)
    body = response.json()
    assert len(body["missing_intervals"]) == 1


@pytest.mark.asyncio
async def test_series_for_out_of_scope_sensor_returns_403() -> None:
    await _seed_all()
    sensor_id, _ = await _seed_numeric_test_channel("4", "fac_20")
    token = await _login("dispatcher", "dispatcher123")
    response = await _get_series(token, sensor_id)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_series_for_nonexistent_sensor_returns_404() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _get_series(token, "sensor_does_not_exist")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_invalid_granularity_returns_400() -> None:
    await _seed_all()
    sensor_id, _ = await _seed_numeric_test_channel("5", "fac_5122")
    token = await _login("manager", "manager123")
    response = await _get_series(token, sensor_id, granularity="not-a-duration")
    assert response.status_code == 400
