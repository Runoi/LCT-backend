"""Tests for the ML predictor factory + HTTP implementation (leaf 1.1.2).

HttpMLPredictor is exercised against httpx.MockTransport -- a real ASGI/
network round-trip through httpx's request/response machinery, but no
real external service.
"""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from src.services import ml_predictor_factory
from src.services.ml_port import PredictionInput, StubPredictor
from src.services.ml_predictor_http import HttpMLPredictor, MLPredictorError


def _input() -> PredictionInput:
    return PredictionInput(
        target_type="sensor",
        target_id="sensor_x",
        risk_type="fire",
        as_of=datetime(2034, 1, 1, tzinfo=timezone.utc),
        recent_alarm_count=2,
        recent_anomaly_count=0,
        window_hours=24.0,
    )


def test_get_predictor_returns_stub_when_url_unset(monkeypatch) -> None:
    monkeypatch.setattr(ml_predictor_factory, "get_settings", lambda: SimpleNamespace(ml_predictor_url=None))
    assert isinstance(ml_predictor_factory.get_predictor(), StubPredictor)


def test_get_predictor_returns_http_when_url_set(monkeypatch) -> None:
    monkeypatch.setattr(
        ml_predictor_factory, "get_settings", lambda: SimpleNamespace(ml_predictor_url="http://ml.example.test")
    )
    assert isinstance(ml_predictor_factory.get_predictor(), HttpMLPredictor)


@pytest.mark.asyncio
async def test_predict_round_trips_the_documented_contract() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "probability": 0.42,
                "lead_min_hours": 2.0,
                "prediction_window_hours": 6.0,
                "top_factors": ["f1", "f2"],
                "recommendation": "rec",
                "model_name": "real-v1",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ml.test")
    try:
        result = await HttpMLPredictor(client).predict(_input())
    finally:
        await client.aclose()

    assert result.probability == 0.42
    assert result.model_name == "real-v1"
    assert result.top_factors == ["f1", "f2"]
    assert captured["json"]["risk_type"] == "fire"
    assert captured["json"]["recent_alarm_count"] == 2
    assert captured["json"]["as_of"] == "2034-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_non_2xx_response_raises_ml_predictor_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ml.test")
    try:
        with pytest.raises(MLPredictorError):
            await HttpMLPredictor(client).predict(_input())
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_malformed_response_raises_ml_predictor_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"probability": 0.5})  # missing required fields

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ml.test")
    try:
        with pytest.raises(MLPredictorError):
            await HttpMLPredictor(client).predict(_input())
    finally:
        await client.aclose()
