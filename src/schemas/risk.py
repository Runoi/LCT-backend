"""Pydantic response models for GET /api/v1/risks[...] (ticket 08)."""
from datetime import datetime

from pydantic import BaseModel


class RiskTarget(BaseModel):
    """What this forecast is about -- always a sensor in this ticket's scope."""

    type: str
    id: str
    facility_id: str | None


class PredictionWindow(BaseModel):
    """The forecast's predicted incident window (as_of + lead_min_hours .. + horizon_hours)."""

    start: datetime
    end: datetime


class RiskOut(BaseModel):
    """The full risk forecast card."""

    id: str
    forecast_id: str
    risk_type: str
    target: RiskTarget
    as_of: datetime
    lead_min_hours: float
    horizon_hours: float
    prediction_window: PredictionWindow
    probability: float
    threshold: float
    risk_level: str
    priority_score: float
    decision_status: str
    sla_due_at: datetime
    data_health: str
    model: str
    top_factors: list[str]
    recommendation: str
    version: int
    created_at: datetime
    updated_at: datetime


class RiskListMeta(BaseModel):
    """Cursor-pagination metadata for the risk list envelope."""

    next_cursor: str | None
    total: int
    generated_at: datetime


class RiskListEnvelope(BaseModel):
    """The standard {data, meta} envelope for GET /api/v1/risks."""

    data: list[RiskOut]
    meta: RiskListMeta


class AcknowledgeRequest(BaseModel):
    """Body for POST /api/v1/risks/{risk_id}/acknowledge."""

    expected_version: int


class DeferRequest(BaseModel):
    """Body for POST /api/v1/risks/{risk_id}/defer."""

    expected_version: int


class RejectRequest(BaseModel):
    """Body for POST /api/v1/risks/{risk_id}/reject.

    reason_code is Optional at the schema level -- its presence is a
    domain rule (contract: "reject requires reason_code"), enforced as a
    422 DOMAIN_VALIDATION_ERROR by the endpoint, not a 400 structural
    validation error.
    """

    expected_version: int
    reason_code: str | None = None
    comment: str | None = None
