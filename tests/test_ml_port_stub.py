"""Tests for StubPredictor (leaf 1.1.1) -- pure, no DB, no I/O."""
from datetime import datetime, timezone

import pytest

from src.services.ml_port import PredictionInput, StubPredictor


def _input(risk_type: str, alarm_count: int, anomaly_count: int, window_hours: float = 24.0) -> PredictionInput:
    return PredictionInput(
        target_type="sensor",
        target_id="sensor_test",
        risk_type=risk_type,
        as_of=datetime(2034, 1, 1, tzinfo=timezone.utc),
        recent_alarm_count=alarm_count,
        recent_anomaly_count=anomaly_count,
        window_hours=window_hours,
    )


@pytest.mark.asyncio
async def test_same_input_produces_byte_identical_result() -> None:
    predictor = StubPredictor()
    input_ = _input("fire", 3, 1)
    first = await predictor.predict(input_)
    second = await predictor.predict(input_)
    assert first == second


@pytest.mark.asyncio
async def test_probability_increases_monotonically_with_alarm_count() -> None:
    predictor = StubPredictor()
    low = await predictor.predict(_input("fire", 1, 0))
    high = await predictor.predict(_input("fire", 5, 0))
    assert high.probability > low.probability


@pytest.mark.asyncio
async def test_probability_increases_monotonically_with_anomaly_count() -> None:
    predictor = StubPredictor()
    low = await predictor.predict(_input("sensor_failure", 0, 1))
    high = await predictor.predict(_input("sensor_failure", 0, 5))
    assert high.probability > low.probability


@pytest.mark.asyncio
async def test_probability_is_clamped_to_a_sane_range() -> None:
    predictor = StubPredictor()
    result = await predictor.predict(_input("fire", 1000, 1000))
    assert 0.0 < result.probability <= 0.97


@pytest.mark.asyncio
async def test_top_factors_and_recommendation_are_risk_type_specific() -> None:
    predictor = StubPredictor()
    fire = await predictor.predict(_input("fire", 2, 0))
    flood = await predictor.predict(_input("flooding", 2, 0))
    assert fire.recommendation != flood.recommendation
    assert fire.top_factors and flood.top_factors
    assert all(isinstance(f, str) and f for f in fire.top_factors)


@pytest.mark.asyncio
async def test_no_signal_still_produces_a_non_empty_explanatory_factor() -> None:
    predictor = StubPredictor()
    result = await predictor.predict(_input("sensor_failure", 0, 0))
    assert len(result.top_factors) >= 1
    assert result.top_factors[0]


@pytest.mark.asyncio
async def test_unknown_risk_type_falls_back_to_documented_defaults() -> None:
    predictor = StubPredictor()
    result = await predictor.predict(_input("not_a_real_risk_type", 1, 0))
    assert result.recommendation
    assert result.lead_min_hours > 0
    assert result.prediction_window_hours > 0
