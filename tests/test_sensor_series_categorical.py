"""Tests for GET /api/v1/sensors/{sensor_id}/series (categorical)."""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from src.db import async_session_factory
from src.main import app
from src.models.sensor import SensorChannel, SensorReading
from src.services.demo_seed import seed_demo_users
from src.services.facility_seed import seed_facility_catalogue
from src.services.sensor_channel_seed import seed_sensor_channel_catalogue
from src.services.sensor_series_query import value_type_for


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


async def _seed_all() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_sensor_channel_catalogue(session)
        await seed_demo_users(session)


async def _seed_categorical_test_channel(suffix: str, facility_id: str):
    # A dedicated, non-catalogue channel -- never one of the real door_contact
    # channels, which can already carry real readings from test_event_etl.py's
    # ingest of the real operational-window file once the whole suite shares
    # one database, which would silently corrupt these interval assertions.
    channel_id = f"test_series_cat_{suffix}"
    sensor_id = f"sensor_{channel_id}"
    async with async_session_factory() as session:
        session.add(
            SensorChannel(
                id=sensor_id,
                channel_id=channel_id,
                tag="",
                sensor_type_id="door_contact",
                system_type="security",
                display_name=f"Test categorical sensor {suffix}",
                facility_id=facility_id,
                hierarchy_node_id=f"node_{facility_id}",
            )
        )
        await session.commit()
    return sensor_id, channel_id


async def _add_readings(channel_id: str, readings: list[tuple[datetime, str]]) -> None:
    async with async_session_factory() as session:
        for occurred_at, value in readings:
            session.add(
                SensorReading(
                    channel_id=channel_id,
                    occurred_at=occurred_at,
                    is_alarm=False,
                    raw_value=value,
                    numeric_value=None,
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
async def test_consecutive_identical_values_merge_into_one_interval() -> None:
    await _seed_all()
    sensor_id, channel_id = await _seed_categorical_test_channel("1", "fac_5339")
    base = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
    await _add_readings(
        channel_id,
        [
            (base, "Не замкнут"),
            (base + timedelta(minutes=5), "Не замкнут"),
            (base + timedelta(minutes=10), "Не замкнут"),
        ],
    )

    token = await _login("dispatcher", "dispatcher123")
    response = await _get_series(token, sensor_id)
    assert response.status_code == 200
    body = response.json()
    assert body["value_type"] == "categorical"
    assert len(body["intervals"]) == 1
    assert body["intervals"][0]["value"] == "Не замкнут"
    assert _parse(body["intervals"][0]["from"]) == base
    assert _parse(body["intervals"][0]["to"]) == base + timedelta(minutes=10)


@pytest.mark.asyncio
async def test_value_change_starts_a_new_interval() -> None:
    await _seed_all()
    sensor_id, channel_id = await _seed_categorical_test_channel("2", "fac_5339")
    base = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
    await _add_readings(
        channel_id,
        [
            (base, "Не замкнут"),
            (base + timedelta(minutes=5), "Замкнут"),
            (base + timedelta(minutes=10), "Замкнут"),
        ],
    )

    token = await _login("dispatcher", "dispatcher123")
    response = await _get_series(token, sensor_id)
    body = response.json()
    assert len(body["intervals"]) == 2
    assert body["intervals"][0]["value"] == "Не замкнут"
    assert body["intervals"][1]["value"] == "Замкнут"
    assert _parse(body["intervals"][1]["to"]) == base + timedelta(minutes=10)


@pytest.mark.asyncio
async def test_dispatch_matches_sensor_types_for_numeric_and_categorical_samples() -> None:
    assert value_type_for("temperature_sensor") == "numeric"
    assert value_type_for("gas_sensor") == "numeric"
    assert value_type_for("door_contact") == "categorical"
    assert value_type_for("smoke_detector") == "categorical"
    assert value_type_for("unknown") == "categorical"


@pytest.mark.asyncio
async def test_categorical_series_for_out_of_scope_sensor_returns_403() -> None:
    await _seed_all()
    sensor_id, _ = await _seed_categorical_test_channel("3", "fac_20")
    token = await _login("dispatcher", "dispatcher123")
    response = await _get_series(token, sensor_id)
    assert response.status_code == 403
