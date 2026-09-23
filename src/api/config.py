"""GET /api/v1/config — the reference/config bundle endpoint."""
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from src.schemas.reference import ReferenceConfig
from src.services.reference_data import get_reference_config

router = APIRouter(prefix="/api/v1", tags=["config"])


class ConfigMeta(BaseModel):
    """Envelope metadata for the config bundle response."""

    generated_at: datetime


class ConfigEnvelope(BaseModel):
    """Standard {data, meta} envelope wrapping the reference config."""

    data: ReferenceConfig
    meta: ConfigMeta


@router.get("/config", response_model=ConfigEnvelope)
async def get_config() -> ConfigEnvelope:
    """Return the reference/config bundle the frontend must not hardcode.

    Returns:
        The reference data (sensor types, states, risk levels/thresholds,
        reject reasons, work types, work order statuses, SLA params,
        freshness boundaries) wrapped in the standard response envelope.
    """
    return ConfigEnvelope(
        data=get_reference_config(),
        meta=ConfigMeta(generated_at=datetime.now(timezone.utc)),
    )
