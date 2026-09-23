"""Pydantic models for GET /api/v1/system/* (ticket 06)."""
from datetime import datetime

from pydantic import BaseModel, Field


class SourceHealthEntryOut(BaseModel):
    """Status of one upstream data source."""

    source: str
    display_name: str
    status: str
    last_success_at: datetime | None
    delay_seconds: int | None


class SourceHealthMeta(BaseModel):
    """Envelope metadata for the source-health response."""

    generated_at: datetime


class SourceHealthEnvelope(BaseModel):
    """The standard {data, meta} envelope for GET /api/v1/system/source-health."""

    data: list[SourceHealthEntryOut]
    meta: SourceHealthMeta


class DegradeRequest(BaseModel):
    """Body for POST /api/v1/system/source-health/{source}/degrade."""

    status: str
    duration_seconds: float = Field(gt=0)


class ScenarioOut(BaseModel):
    """One fixture scenario's metadata (no step details -- those are internal)."""

    id: str
    display_name: str
    category: str
    description: str


class ScenarioListEnvelope(BaseModel):
    """The standard {data} envelope for GET /api/v1/system/scenarios."""

    data: list[ScenarioOut]


class ActivateScenarioRequest(BaseModel):
    """Body for POST /api/v1/system/scenarios/{scenario_id}/activate."""

    facility_id: str
    seed: int = 42


class ActivateScenarioResult(BaseModel):
    """Result of a scenario activation."""

    scenario_id: str
    facility_id: str
    readings_inserted: int
