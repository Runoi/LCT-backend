"""Tests for GET/POST/DELETE /api/v1/system/source-health* (leaf 1.3.2)."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.db import async_session_factory
from src.main import app
from src.models.emulation_providers import SyntheticProviderRun
from src.models.replay import SINGLETON_ID, ReplayState
from src.models.source_health import SourceHealthOverride
from src.services.demo_seed import seed_demo_users
from src.services.source_health import SOURCES


async def _seed_all() -> None:
    async with async_session_factory() as session:
        await seed_demo_users(session)


async def _reset_all_source_marker_state() -> None:
    # ReplayState/SyntheticProviderRun/SourceHealthOverride are global
    # singletons shared with test_replay_engine.py and the provider tests,
    # which deliberately use far-future dates for their own isolation --
    # those leftover rows would otherwise make "unavailable" (no data)
    # assumptions here unpredictable. Reset before asserting a specific
    # computed-from-scratch status.
    async with async_session_factory() as session:
        state = (await session.execute(select(ReplayState).where(ReplayState.id == SINGLETON_ID))).scalar_one_or_none()
        if state is not None:
            await session.delete(state)
        for source, _ in SOURCES:
            run = await session.get(SyntheticProviderRun, source)
            if run is not None:
                await session.delete(run)
            override = await session.get(SourceHealthOverride, source)
            if override is not None:
                await session.delete(override)
        await session.commit()


async def _login(username: str, password: str) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["token"]


async def _get(token: str | None, path: str):
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


async def _post(token: str, path: str, json: dict):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, headers={"Authorization": f"Bearer {token}"}, json=json)


async def _delete(token: str, path: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.delete(path, headers={"Authorization": f"Bearer {token}"})


@pytest.mark.asyncio
async def test_source_health_returns_four_sources() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _get(token, "/api/v1/system/source-health")
    assert response.status_code == 200
    body = response.json()
    sources = {e["source"] for e in body["data"]}
    assert sources == {"smvu", "ods_journal", "equipment_registry", "work_order_system"}
    for entry in body["data"]:
        assert entry["status"] in ("online", "delayed", "unavailable")


@pytest.mark.asyncio
async def test_degrade_then_clear_round_trips() -> None:
    await _seed_all()
    await _reset_all_source_marker_state()
    token = await _login("manager", "manager123")

    degrade = await _post(token, "/api/v1/system/source-health/smvu/degrade", {"status": "online", "duration_seconds": 60})
    assert degrade.status_code == 204

    after_degrade = await _get(token, "/api/v1/system/source-health")
    smvu = next(e for e in after_degrade.json()["data"] if e["source"] == "smvu")
    assert smvu["status"] == "online"

    clear = await _delete(token, "/api/v1/system/source-health/smvu/degrade")
    assert clear.status_code == 204

    after_clear = await _get(token, "/api/v1/system/source-health")
    smvu = next(e for e in after_clear.json()["data"] if e["source"] == "smvu")
    assert smvu["status"] == "unavailable"  # no real data seeded -> reverts to computed


@pytest.mark.asyncio
async def test_degrade_unknown_source_returns_404() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _post(token, "/api/v1/system/source-health/not_a_real_source/degrade", {"status": "online", "duration_seconds": 60})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_degrade_invalid_status_returns_400() -> None:
    await _seed_all()
    token = await _login("manager", "manager123")
    response = await _post(token, "/api/v1/system/source-health/smvu/degrade", {"status": "not_a_real_status", "duration_seconds": 60})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_source_health_requires_authentication() -> None:
    response = await _get(None, "/api/v1/system/source-health")
    assert response.status_code == 401
