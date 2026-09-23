"""Pydantic response models for the reference/config bundle."""
from typing import Literal, Optional

from pydantic import BaseModel


class SensorType(BaseModel):
    """One sensor type from the equipment/channel catalogue."""

    id: str
    display_name: str
    system_type: str
    value_type: Literal["numeric", "categorical"]


class UnitOfMeasure(BaseModel):
    """A unit of measurement used by numeric sensor readings."""

    id: str
    display_name: str
    symbol: str


class RiskType(BaseModel):
    """A predictable incident/failure category."""

    id: str
    display_name: str


class RiskLevelThreshold(BaseModel):
    """A risk level and the probability range that determines it."""

    id: str
    display_name: str
    min_probability: float
    max_probability: float


class RejectReason(BaseModel):
    """A reason code selectable when rejecting a risk forecast."""

    id: str
    display_name: str
    requires_comment: bool


class WorkType(BaseModel):
    """A category of maintenance/repair work order."""

    id: str
    display_name: str


class WorkOrderStatus(BaseModel):
    """A status in the work order lifecycle."""

    id: str
    display_name: str


class DecisionStatus(BaseModel):
    """A status in the risk-decision workflow (ticket 08)."""

    id: str
    display_name: str


class SlaParam(BaseModel):
    """The target response time for a given risk level."""

    risk_level: str
    response_minutes: int


class FreshnessBoundary(BaseModel):
    """A data-freshness bucket and the age (in seconds) it covers up to."""

    id: str
    display_name: str
    max_age_seconds: Optional[int]


class ReferenceConfig(BaseModel):
    """The complete reference/config bundle the frontend must not hardcode."""

    sensor_states: list[str]
    sensor_types: list[SensorType]
    units: list[UnitOfMeasure]
    risk_types: list[RiskType]
    risk_levels: list[RiskLevelThreshold]
    reject_reasons: list[RejectReason]
    work_types: list[WorkType]
    work_order_statuses: list[WorkOrderStatus]
    decision_statuses: list[DecisionStatus]
    sla_params: list[SlaParam]
    freshness_boundaries: list[FreshnessBoundary]
