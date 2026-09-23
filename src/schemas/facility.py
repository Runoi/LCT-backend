"""Pydantic response models for facility list/detail (ticket 04).

The dynamic fields (forecast, incidents, data_health, priority_score,
source_health) are honest MVP placeholders: the structure the contract
requires is real and stable, but the values are not yet computed from
real sensor/risk data -- that lands with tickets 05 (sensor timeseries)
and 08 (ML predictions / risks). This file owns only the shape.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Location(BaseModel):
    """A GeoJSON Point with an explicit demo-geometry flag.

    Real coordinates will never be provided (see
    `QA_ORGANIZERS_CLARIFICATIONS.md` section 12); this point is
    deterministic (stable per facility_id) but not geographically real.
    """

    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]
    is_demo: bool = True


class Forecast(BaseModel):
    """Forecast summary — independent from current_state and incidents."""

    risk_level: str
    max_probability: float
    active_count: int
    earliest_window_start: datetime | None


class Incidents(BaseModel):
    """Confirmed-incident counters — independent from forecast/current_state."""

    open_count: int
    critical_count: int


class Assets(BaseModel):
    """Counts of the facility's owned equipment/sensors."""

    collector_count: int
    sensor_count: int
    offline_sensor_count: int


class DataHealth(BaseModel):
    """Freshness/coverage of the data backing this facility's other fields."""

    freshness: str
    last_event_at: datetime | None
    coverage: float


class SourceHealthEntry(BaseModel):
    """Status of one upstream data source (see ticket 06 emulation module)."""

    source: str
    display_name: str
    status: str
    last_success_at: datetime | None
    delay_seconds: int | None


class FacilityOut(BaseModel):
    """The complete facility representation, shared by list and detail."""

    id: str
    display_name: str
    facility_type: str
    location: Location
    current_state: str
    forecast: Forecast
    incidents: Incidents
    assets: Assets
    data_health: DataHealth
    priority_score: float
    source_health: list[SourceHealthEntry]
    updated_at: datetime


class FacilityListMeta(BaseModel):
    """Cursor-pagination metadata for the facility list envelope."""

    next_cursor: str | None
    total: int
    generated_at: datetime


class FacilityListEnvelope(BaseModel):
    """The standard {data, meta} envelope for GET /api/v1/facilities."""

    data: list[FacilityOut]
    meta: FacilityListMeta
