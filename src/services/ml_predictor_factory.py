"""Picks the ML Prediction Port implementation from config alone (ticket 08).

The only integration point the ML team needs: set ML_PREDICTOR_URL to their
deployed service's root URL and the backend switches over with no code
change or redeploy of backend logic.
"""
import httpx

from src.config import get_settings
from src.services.ml_port import MLPredictor, StubPredictor
from src.services.ml_predictor_http import HttpMLPredictor

_HTTP_TIMEOUT_SECONDS = 10.0
_OBJECT_RISK_TIMEOUT_SECONDS = 60.0


def get_predictor() -> MLPredictor:
    """Return the configured predictor implementation.

    Returns:
        A StubPredictor when ML_PREDICTOR_URL is unset (default, safe for
        local/demo use); an HttpMLPredictor pointed at ML_PREDICTOR_URL
        otherwise.
    """
    url = get_settings().ml_predictor_url
    if not url:
        return StubPredictor()
    client = httpx.AsyncClient(base_url=url, timeout=_HTTP_TIMEOUT_SECONDS)
    return HttpMLPredictor(client)


def get_object_risk_client() -> httpx.AsyncClient | None:
    """Return an HTTP client for the ML service's /risk_map, or None when ML_PREDICTOR_URL is unset.

    The timeout is longer than for /predict: /risk_map ranks all facilities (about a second on real data).
    """
    url = get_settings().ml_predictor_url
    return httpx.AsyncClient(base_url=url, timeout=_OBJECT_RISK_TIMEOUT_SECONDS) if url else None
