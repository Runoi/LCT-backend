"""Tests for GET /api/v1/config."""
import re

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app

SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")


@pytest.mark.asyncio
async def test_config_returns_full_reference_bundle() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/config")

    assert response.status_code == 200
    body = response.json()

    assert "data" in body and "meta" in body
    assert "generated_at" in body["meta"]

    data = body["data"]
    for field in (
        "sensor_states",
        "sensor_types",
        "units",
        "risk_types",
        "risk_levels",
        "reject_reasons",
        "work_types",
        "work_order_statuses",
        "decision_statuses",
        "sla_params",
        "freshness_boundaries",
    ):
        assert field in data, f"missing reference category: {field}"
        assert len(data[field]) > 0, f"empty reference category: {field}"

    assert len(data["sensor_types"]) >= 19
    assert set(data["sensor_states"]) == {
        "normal", "warning", "alarm", "fault",
        "offline", "maintenance", "disabled", "unknown",
    }


@pytest.mark.asyncio
async def test_config_enum_ids_are_snake_case() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/config")

    data = response.json()["data"]
    id_bearing_lists = [
        "sensor_types", "units", "risk_types", "risk_levels",
        "reject_reasons", "work_types", "work_order_statuses", "decision_statuses",
    ]
    for field in id_bearing_lists:
        for item in data[field]:
            assert SNAKE_CASE.match(item["id"]), f"{field} id not snake_case: {item['id']}"
    for state in data["sensor_states"]:
        assert SNAKE_CASE.match(state), f"sensor_states value not snake_case: {state}"
