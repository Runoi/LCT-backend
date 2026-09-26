"""Tests for the fixture-scenario library (leaf 1.1.2)."""
import pytest
from sqlalchemy import func, select

from src.db import async_session_factory
from src.models.sensor import SensorChannel, SensorReading
from src.services.facility_seed import seed_facility_catalogue
from src.services.fixture_scenarios import (
    SCENARIOS,
    ScenarioActivationError,
    activate_scenario,
    get_scenario,
)
from src.services.reference_data import SENSOR_TYPES
from src.services.sensor_channel_seed import seed_sensor_channel_catalogue

_REAL_SENSOR_TYPE_IDS = {t.id for t in SENSOR_TYPES}
_VALID_CATEGORIES = {"fire", "flooding", "unauthorized_access", "sensor_failure"}


async def _seed_all() -> None:
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_sensor_channel_catalogue(session)


async def _any_facility_with_type(sensor_type_id: str) -> str | None:
    async with async_session_factory() as session:
        return (
            await session.execute(
                select(SensorChannel.facility_id)
                .where(SensorChannel.sensor_type_id == sensor_type_id, SensorChannel.facility_id.isnot(None))
                .limit(1)
            )
        ).scalar_one_or_none()


async def _any_facility_with_all_types(sensor_type_ids: list[str]) -> str | None:
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(SensorChannel.facility_id)
                .where(SensorChannel.sensor_type_id.in_(sensor_type_ids), SensorChannel.facility_id.isnot(None))
                .group_by(SensorChannel.facility_id)
                .having(func.count(func.distinct(SensorChannel.sensor_type_id)) == len(set(sensor_type_ids)))
                .limit(1)
            )
        ).scalar_one_or_none()
        return rows


def test_library_has_16_scenarios_four_per_category() -> None:
    assert len(SCENARIOS) == 16
    ids = [s.id for s in SCENARIOS]
    assert len(ids) == len(set(ids)), "scenario ids must be unique"
    by_category: dict[str, int] = {}
    for s in SCENARIOS:
        assert s.category in _VALID_CATEGORIES
        by_category[s.category] = by_category.get(s.category, 0) + 1
    assert by_category == {"fire": 4, "flooding": 4, "unauthorized_access": 4, "sensor_failure": 4}


def test_every_scenario_step_uses_a_real_sensor_type() -> None:
    for scenario in SCENARIOS:
        assert len(scenario.steps) >= 1
        for step in scenario.steps:
            assert step.sensor_type_id in _REAL_SENSOR_TYPE_IDS, f"{scenario.id}: unknown sensor_type {step.sensor_type_id}"


@pytest.mark.asyncio
async def test_activate_single_step_scenario_inserts_one_fixture_reading() -> None:
    await _seed_all()
    facility_id = await _any_facility_with_type("smoke_detector")
    assert facility_id is not None, "expected at least one real facility with a smoke_detector channel"

    async with async_session_factory() as session:
        count = await activate_scenario(session, "fire_smoke_only", facility_id, seed=1)
    assert count == 1

    # Scoped to this call's seed (source_event_id ends with "_<seed>"): other tests
    # activate the same scenario on the same facility in the shared test database.
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(SensorReading).where(SensorReading.source_event_id.like(f"fixture_fire_smoke_only_{facility_id}_%_1"))
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].origin == "fixture"
    assert rows[0].is_alarm is True


@pytest.mark.asyncio
async def test_activate_multi_step_scenario_when_facility_has_all_required_types() -> None:
    await _seed_all()
    scenario = get_scenario("fire_smoke_and_heat")
    required_types = [step.sensor_type_id for step in scenario.steps]
    facility_id = await _any_facility_with_all_types(required_types)
    if facility_id is None:
        pytest.skip("no real facility carries every sensor type this scenario needs")

    async with async_session_factory() as session:
        count = await activate_scenario(session, "fire_smoke_and_heat", facility_id, seed=7)
    assert count == 2

    async with async_session_factory() as session:
        rows = (
            await session.execute(select(SensorReading).where(SensorReading.source_event_id.like(f"fixture_fire_smoke_and_heat_{facility_id}_%")))
        ).scalars().all()
    assert len(rows) == 2
    offsets = sorted((r.occurred_at for r in rows))
    assert (offsets[1] - offsets[0]).total_seconds() == pytest.approx(15.0)


@pytest.mark.asyncio
async def test_unknown_scenario_id_raises() -> None:
    await _seed_all()
    async with async_session_factory() as session:
        with pytest.raises(ScenarioActivationError):
            await activate_scenario(session, "does_not_exist", "fac_5122")


@pytest.mark.asyncio
async def test_facility_missing_required_sensor_type_raises() -> None:
    await _seed_all()
    async with async_session_factory() as session:
        with pytest.raises(ScenarioActivationError):
            await activate_scenario(session, "fire_smoke_only", "fac_definitely_does_not_exist_999")
