"""Access control on /api/v1/system/* demo controls: system.manage + facility scope."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from src.db import async_session_factory
from src.main import app
from src.models.auth import User, UserPermission, UserScope, UserScopeFacility
from src.models.sensor import SensorChannel, SensorReading
from src.services.auth_service import hash_password
from src.services.demo_seed import seed_demo_users
from src.services.facility_seed import seed_facility_catalogue
from src.services.sensor_channel_seed import seed_sensor_channel_catalogue

_SCOPED_OPERATOR_ID = "usr_test_scoped_operator"


async def _seed_all() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_sensor_channel_catalogue(session)
        await seed_demo_users(session)


async def _two_smoke_facilities() -> tuple[str, str]:
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(SensorChannel.facility_id)
                .where(SensorChannel.sensor_type_id == "smoke_detector", SensorChannel.facility_id.isnot(None))
                .distinct()
                .order_by(SensorChannel.facility_id)
                .limit(2)
            )
        ).scalars().all()
    assert len(rows) == 2, "need two facilities with a smoke detector for scope tests"
    return rows[0], rows[1]


async def _seed_scoped_operator(facility_id: str) -> None:
    """A user holding system.manage but scoped to a single facility."""
    async with async_session_factory() as session:
        if await session.get(User, _SCOPED_OPERATOR_ID) is not None:
            return
        session.add(
            User(
                id=_SCOPED_OPERATOR_ID,
                username=_SCOPED_OPERATOR_ID,
                password_hash=hash_password("password123"),
                display_name="scoped operator",
                role="test",
            )
        )
        session.add(UserPermission(user_id=_SCOPED_OPERATOR_ID, permission="system.manage"))
        session.add(UserScope(user_id=_SCOPED_OPERATOR_ID, scope_type="assigned_facilities"))
        session.add(UserScopeFacility(user_id=_SCOPED_OPERATOR_ID, facility_id=facility_id))
        await session.commit()


async def _login(username: str, password: str) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["token"]


async def _request(method: str, token: str, path: str, json: dict | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers={"Authorization": f"Bearer {token}"}, json=json)


async def _fixture_reading_count(facility_id: str) -> int:
    async with async_session_factory() as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(SensorReading)
                .where(
                    SensorReading.origin == "fixture",
                    SensorReading.source_event_id.like(f"fixture_%_{facility_id}_%"),
                )
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_dispatcher_cannot_degrade_source() -> None:
    await _seed_all()
    token = await _login("dispatcher", "dispatcher123")
    response = await _request(
        "POST", token, "/api/v1/system/source-health/smvu/degrade", {"status": "delayed", "duration_seconds": 60}
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_dispatcher_cannot_clear_degradation() -> None:
    await _seed_all()
    token = await _login("dispatcher", "dispatcher123")
    response = await _request("DELETE", token, "/api/v1/system/source-health/smvu/degrade")
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_dispatcher_cannot_activate_scenario_even_in_own_scope() -> None:
    await _seed_all()
    token = await _login("dispatcher", "dispatcher123")
    before = await _fixture_reading_count("fac_5122")
    response = await _request(
        "POST", token, "/api/v1/system/scenarios/fire_smoke_only/activate", {"facility_id": "fac_5122"}
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    assert await _fixture_reading_count("fac_5122") == before, "denied request must not write readings"


@pytest.mark.asyncio
async def test_scoped_operator_denied_outside_scope_and_nothing_written() -> None:
    await _seed_all()
    own_facility, foreign_facility = await _two_smoke_facilities()
    await _seed_scoped_operator(own_facility)
    token = await _login(_SCOPED_OPERATOR_ID, "password123")

    before = await _fixture_reading_count(foreign_facility)
    response = await _request(
        "POST", token, "/api/v1/system/scenarios/fire_smoke_only/activate", {"facility_id": foreign_facility, "seed": 7}
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FACILITY_ACCESS_DENIED"
    assert await _fixture_reading_count(foreign_facility) == before, "out-of-scope activation must write nothing"


@pytest.mark.asyncio
async def test_scoped_operator_can_activate_in_own_scope() -> None:
    await _seed_all()
    own_facility, _ = await _two_smoke_facilities()
    await _seed_scoped_operator(own_facility)
    token = await _login(_SCOPED_OPERATOR_ID, "password123")

    before = await _fixture_reading_count(own_facility)
    response = await _request(
        "POST", token, "/api/v1/system/scenarios/fire_smoke_only/activate", {"facility_id": own_facility, "seed": 11}
    )
    assert response.status_code == 200, response.text
    assert response.json()["readings_inserted"] == 1
    assert await _fixture_reading_count(own_facility) == before + 1


@pytest.mark.asyncio
async def test_dispatcher_can_still_read_source_health_and_scenarios() -> None:
    await _seed_all()
    token = await _login("dispatcher", "dispatcher123")
    health = await _request("GET", token, "/api/v1/system/source-health")
    scenarios = await _request("GET", token, "/api/v1/system/scenarios")
    assert health.status_code == 200, health.text
    assert scenarios.status_code == 200, scenarios.text


@pytest.mark.asyncio
async def test_seed_tops_up_missing_manager_permission() -> None:
    await _seed_all()
    async with async_session_factory() as session:
        await session.execute(
            delete(UserPermission).where(
                UserPermission.user_id == "usr_manager", UserPermission.permission == "system.manage"
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        await seed_demo_users(session)

    async with async_session_factory() as session:
        granted = (
            await session.execute(
                select(UserPermission.permission).where(UserPermission.user_id == "usr_manager")
            )
        ).scalars().all()
    assert "system.manage" in granted, "seed must restore a catalogue permission missing from the manager"
