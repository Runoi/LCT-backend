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
