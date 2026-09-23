"""ORM models for sensor channels and their readings (ticket 05).

sensor_type_id references `src/services/reference_data.py::SENSOR_TYPES`
ids (plus the synthetic "unknown" id for orphaned channels) -- that
module stays the single source of truth for numeric/categorical
classification; this schema does not duplicate it.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SensorChannel(Base):
    """A monitored sensor channel, optionally linked to a facility/node.

    facility_id/hierarchy_node_id are nullable: an event referencing a
    channel_id absent from the catalogue creates an orphaned SensorChannel
    with sensor_type_id="unknown" and both left null, rather than being
    silently dropped (see ticket 05 criterion on unknown channels).
    """

    __tablename__ = "sensor_channels"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    channel_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    tag: Mapped[str] = mapped_column(String)
    sensor_type_id: Mapped[str] = mapped_column(String)
    system_type: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    facility_id: Mapped[str | None] = mapped_column(ForeignKey("facilities.id"), nullable=True)
    hierarchy_node_id: Mapped[str | None] = mapped_column(ForeignKey("hierarchy_nodes.id"), nullable=True)


class SensorReading(Base):
    """One raw event-log row, normalized (see `src/services/event_parser.py`)."""

    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[str] = mapped_column(String, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    is_alarm: Mapped[bool] = mapped_column(Boolean)
    raw_value: Mapped[str] = mapped_column(String)
    numeric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    source_event_id: Mapped[str] = mapped_column(String)
    # "historical" (ticket 05 ETL), "replay" (ticket 06 SMVU replay), or "fixture" (ticket 06 scenario).
    origin: Mapped[str] = mapped_column(String, default="historical")


class EtlIngestedSource(Base):
    """Marks a source file as fully ingested, for whole-file idempotency."""

    __tablename__ = "etl_ingested_sources"

    source_path: Mapped[str] = mapped_column(String, primary_key=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    row_count: Mapped[int] = mapped_column(Integer)
