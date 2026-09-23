"""ML Prediction Port (ticket 08, ADR 0006): the contract the backend uses
to obtain a risk forecast, independent of who computes it.

Deliberately NOT shaped like INDASTRICS' `fit/predict/predict_with_intervals`
(ADR 0006) -- one call, a temporal slice of signals in, a forecast out.

`StubPredictor` is the in-process fallback used until a real ML service is
configured (see `src/services/ml_predictor_factory.py`). It is explicitly
a temporary internal-testing component (CONTEXT.md's "Stub Predictor" term),
not the demonstrated model. Deterministic on purpose (no RNG): unlike
ticket 06's fixture scenarios, demo reproducibility here matters more than
imitating randomness.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class PredictionInput:
    """The temporal slice of signals handed to a predictor."""

    target_type: str  # "sensor" (the only target granularity produced in this ticket)
    target_id: str
    risk_type: str
    as_of: datetime
    recent_alarm_count: int
    recent_anomaly_count: int
    window_hours: float


@dataclass(frozen=True)
class PredictionResult:
    """A predictor's forecast for one PredictionInput."""

    probability: float
    lead_min_hours: float
    prediction_window_hours: float
    top_factors: list[str]
    recommendation: str
    model_name: str


class MLPredictor(Protocol):
    """The port every predictor implementation (stub or real) satisfies."""

    async def predict(self, prediction_input: PredictionInput) -> PredictionResult: ...


_LEAD_HORIZON_HOURS_BY_RISK_TYPE: dict[str, tuple[float, float]] = {
    "fire": (2.0, 6.0),
    "flooding": (6.0, 24.0),
    "unauthorized_access": (0.5, 2.0),
    "sensor_failure": (12.0, 48.0),
}
_DEFAULT_LEAD_HORIZON_HOURS = (6.0, 24.0)

_RECOMMENDATION_BY_RISK_TYPE: dict[str, str] = {
    "fire": "Направить группу реагирования для очной проверки очага возгорания",
    "flooding": "Проверить дренажные насосы и уровень воды на объекте",
    "unauthorized_access": "Проверить видеонаблюдение и направить охрану на объект",
    "sensor_failure": "Запланировать техническое обслуживание оборудования",
}
_DEFAULT_RECOMMENDATION = "Проверить состояние оборудования на объекте"

_MODEL_NAME = "stub-v1"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class StubPredictor:
    """Deterministic, non-random fallback predictor.

    Probability is a pure function of the real alarm/anomaly counts in the
    input window -- never uniform noise -- so re-running the same input
    (e.g. in a demo or a test) always yields the same forecast.
    """

    async def predict(self, prediction_input: PredictionInput) -> PredictionResult:
        """Produce a deterministic forecast grounded in real alarm/anomaly volume.

        Args:
            prediction_input: The target and its recent signal counts.

        Returns:
            A PredictionResult whose probability strictly increases with
            recent_alarm_count/recent_anomaly_count.
        """
        probability = _clamp(
            0.15 + 0.12 * prediction_input.recent_alarm_count + 0.18 * prediction_input.recent_anomaly_count,
            0.05,
            0.97,
        )
        lead_hours, horizon_hours = _LEAD_HORIZON_HOURS_BY_RISK_TYPE.get(
            prediction_input.risk_type, _DEFAULT_LEAD_HORIZON_HOURS
        )

        factors: list[str] = []
        if prediction_input.recent_alarm_count:
            factors.append(
                f"{prediction_input.recent_alarm_count} тревожных срабатываний за "
                f"{prediction_input.window_hours:.0f} ч"
            )
        if prediction_input.recent_anomaly_count:
            factors.append(f"{prediction_input.recent_anomaly_count} аномальных показаний за тот же период")
        if not factors:
            factors.append("Недостаточно данных для детального объяснения")

        return PredictionResult(
            probability=round(probability, 4),
            lead_min_hours=lead_hours,
            prediction_window_hours=horizon_hours,
            top_factors=factors[:5],
            recommendation=_RECOMMENDATION_BY_RISK_TYPE.get(prediction_input.risk_type, _DEFAULT_RECOMMENDATION),
            model_name=_MODEL_NAME,
        )
