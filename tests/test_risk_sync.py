"""Tests for sync_risks (leaf 1.2.2).

Uses a dedicated, non-catalogue Facility/SensorChannel and a recording
test-double predictor, so assertions are scoped to this file's own data
regardless of what real ETL/replay alarms also share this database.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.db import async_session_factory
from src.models.event import Event
from src.models.hierarchy import Facility
from src.models.risk import Risk
from src.models.sensor import SensorChannel, SensorReading
from src.services.ml_port import PredictionInput, PredictionResult
from src.services.ml_predictor_http import MLPredictorError
from src.services.risk_sync import risk_type_for_system_type, sync_risks


class _RecordingPredictor:
    def __init__(self, result: PredictionResult) -> None:
        self.result = result
        self.calls: list[PredictionInput] = []

    async def predict(self, prediction_input: PredictionInput) -> PredictionResult:
        self.calls.append(prediction_input)
        return self.result


def _fixed_result() -> PredictionResult:
    return PredictionResult(
        probability=0.5,
        lead_min_hours=2.0,
        prediction_window_hours=6.0,
        top_factors=["test factor"],
        recommendation="test recommendation",
        model_name="test-model",
    )


async def _seed_channel(suffix: str, facility_id: str, system_type: str = "fire_protection") -> str:
    channel_id = f"risk_sync_test_{suffix}"
    async with async_session_factory() as session:
        if await session.get(Facility, facility_id) is None:
            session.add(Facility(id=facility_id, display_name=facility_id, facility_type="test", district_id=None))
        if await session.get(SensorChannel, f"sensor_{channel_id}") is None:
            session.add(
                SensorChannel(
                    id=f"sensor_{channel_id}",
                    channel_id=channel_id,
                    tag="",
                    sensor_type_id="smoke_detector",
                    system_type=system_type,
                    display_name=channel_id,
                    facility_id=facility_id,
                    hierarchy_node_id=None,
                )
            )
        await session.commit()
    return channel_id


async def _add_reading(channel_id: str, occurred_at: datetime, suffix: str) -> None:
    async with async_session_factory() as session:
        session.add(
            SensorReading(
                channel_id=channel_id,
                occurred_at=occurred_at,
                is_alarm=True,
                raw_value="x",
                numeric_value=None,
                is_anomaly=False,
                source_event_id=f"risk_sync_test_{suffix}",
                origin="historical",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_one_group_produces_one_risk_and_links_all_its_events() -> None:
    channel_id = await _seed_channel("group", "fac_risk_sync_group")
    sensor_id = f"sensor_{channel_id}"
    base = datetime(2036, 1, 1, tzinfo=timezone.utc)
    for i in range(3):
        await _add_reading(channel_id, base + timedelta(minutes=i), f"group_{i}")

    predictor = _RecordingPredictor(_fixed_result())
    async with async_session_factory() as session:
        created = await sync_risks(session, predictor, now=base + timedelta(hours=1))

    assert created >= 1  # at least this test's own group (others may share the DB)
    assert len(predictor.calls) >= 1
    my_call = next(c for c in predictor.calls if c.target_id == sensor_id)
    assert my_call.risk_type == "fire"
    assert my_call.recent_alarm_count == 3
    assert my_call.recent_anomaly_count == 0

    async with async_session_factory() as session:
        risks = (await session.execute(select(Risk).where(Risk.target_id == sensor_id))).scalars().all()
        events = (await session.execute(select(Event).where(Event.sensor_id == sensor_id))).scalars().all()

    assert len(risks) == 1
    assert len(events) == 3
    assert all(e.related_risk_id == risks[0].id for e in events)
    assert risks[0].risk_type == "fire"
    assert risks[0].facility_id == "fac_risk_sync_group"
    assert risks[0].model == "test-model"
    assert risks[0].top_factors == ["test factor"]


@pytest.mark.asyncio
async def test_second_sync_does_not_create_a_duplicate_risk_for_the_same_group() -> None:
    channel_id = await _seed_channel("idempotent", "fac_risk_sync_idempotent")
    sensor_id = f"sensor_{channel_id}"
    await _add_reading(channel_id, datetime(2036, 2, 1, tzinfo=timezone.utc), "idempotent")

    predictor = _RecordingPredictor(_fixed_result())
    async with async_session_factory() as session:
        await sync_risks(session, predictor, now=datetime(2036, 2, 1, 1, tzinfo=timezone.utc))
    async with async_session_factory() as session:
        await sync_risks(session, predictor, now=datetime(2036, 2, 1, 2, tzinfo=timezone.utc))

    async with async_session_factory() as session:
        risks = (await session.execute(select(Risk).where(Risk.target_id == sensor_id))).scalars().all()
    assert len(risks) == 1


@pytest.mark.asyncio
async def test_risk_type_mapping_table() -> None:
    assert risk_type_for_system_type("fire_protection") == "fire"
    assert risk_type_for_system_type("security") == "unauthorized_access"
    assert risk_type_for_system_type("diagnostic") == "flooding"
    assert risk_type_for_system_type("dispatch_control") == "sensor_failure"
    assert risk_type_for_system_type("temperature") == "sensor_failure"
    assert risk_type_for_system_type("gas_protection") == "sensor_failure"
    assert risk_type_for_system_type("unknown") == "sensor_failure"


@pytest.mark.asyncio
async def test_security_system_type_maps_to_unauthorized_access_risk() -> None:
    channel_id = await _seed_channel("security", "fac_risk_sync_security", system_type="security")
    sensor_id = f"sensor_{channel_id}"
    await _add_reading(channel_id, datetime(2036, 3, 1, tzinfo=timezone.utc), "security")

    predictor = _RecordingPredictor(_fixed_result())
    async with async_session_factory() as session:
        await sync_risks(session, predictor, now=datetime(2036, 3, 1, 1, tzinfo=timezone.utc))

    async with async_session_factory() as session:
        risk = (await session.execute(select(Risk).where(Risk.target_id == sensor_id))).scalar_one()
    assert risk.risk_type == "unauthorized_access"


class _FailingForSensorPredictor:
    """Answers like the real ML service: 422-style error for one channel, a prediction for the rest."""

    def __init__(self, failing_sensor_id: str) -> None:
        self.failing_sensor_id = failing_sensor_id

    async def predict(self, prediction_input: PredictionInput) -> PredictionResult:
        if prediction_input.target_id == self.failing_sensor_id:
            raise MLPredictorError('ML predictor returned 422: {"status": "insufficient_data"}')
        return _fixed_result()


@pytest.mark.asyncio
async def test_ml_error_for_one_channel_skips_only_that_channel() -> None:
    failing = await _seed_channel("ml_error_failing", "fac_risk_sync_ml_error")
    healthy = await _seed_channel("ml_error_healthy", "fac_risk_sync_ml_error")
    base = datetime(2036, 3, 1, tzinfo=timezone.utc)
    await _add_reading(failing, base, "ml_error_failing")
    await _add_reading(healthy, base + timedelta(minutes=1), "ml_error_healthy")

    predictor = _FailingForSensorPredictor(f"sensor_{failing}")
    async with async_session_factory() as session:
        await sync_risks(session, predictor, now=base + timedelta(hours=1))

    async with async_session_factory() as session:
        failing_risks = (await session.execute(select(Risk).where(Risk.target_id == f"sensor_{failing}"))).scalars().all()
        healthy_risks = (await session.execute(select(Risk).where(Risk.target_id == f"sensor_{healthy}"))).scalars().all()
    assert failing_risks == [], "a channel the ML service rejects must not get a risk"
    assert len(healthy_risks) == 1, "the ML error must not stop other channels"

    # Курсор сдвинулся: повторная синхронизация не долбит ML тем же каналом по кругу.
    async with async_session_factory() as session:
        await sync_risks(session, predictor, now=base + timedelta(hours=2))
    async with async_session_factory() as session:
        again = (await session.execute(select(Risk).where(Risk.target_id == f"sensor_{healthy}"))).scalars().all()
    assert len(again) == 1
