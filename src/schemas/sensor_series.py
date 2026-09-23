"""Pydantic response models for GET /sensors/{id}/series (ticket 05).

thresholds is always an empty, present list: no per-sensor-type raw-value
thresholds are calibrated anywhere in this project yet (honest MVP
placeholder, see PLAN.md). missing_intervals uses a fixed >1h gap
heuristic, documented as such rather than derived from real reporting
cadence per channel.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class NumericPoint(BaseModel):
    """One raw or bucket-averaged numeric reading."""

    timestamp: datetime
    value: float
    state: str
    quality: str


class Threshold(BaseModel):
    """A named threshold value (always empty for MVP -- see module docstring)."""

    kind: str
    value: float


class MissingInterval(BaseModel):
    """A gap in the numeric series longer than the MVP heuristic bound."""

    model_config = {"populate_by_name": True}

    from_: datetime = Field(alias="from")
    to: datetime


class NumericSeriesOut(BaseModel):
    """The numeric series response shape."""

    value_type: Literal["numeric"] = "numeric"
    points: list[NumericPoint]
    thresholds: list[Threshold]
    missing_intervals: list[MissingInterval]


class CategoricalInterval(BaseModel):
    """A time range during which the sensor held one categorical value."""

    model_config = {"populate_by_name": True}

    from_: datetime = Field(alias="from")
    to: datetime
    value: str
    state: str


class CategoricalSeriesOut(BaseModel):
    """The categorical series response shape."""

    value_type: Literal["categorical"] = "categorical"
    intervals: list[CategoricalInterval]
