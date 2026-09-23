"""Numeric/categorical series queries for GET /sensors/{id}/series (ticket 05).

value_type dispatch reuses `reference_data.SENSOR_TYPES` (single source of
truth, same as sensor_query.py) -- never re-derived here.
"""
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.errors import ApiError
from src.models.sensor import SensorChannel, SensorReading
from src.schemas.sensor_series import (
    CategoricalInterval,
    CategoricalSeriesOut,
    MissingInterval,
    NumericPoint,
    NumericSeriesOut,
    Threshold,
)
from src.services.reference_data import SENSOR_TYPES

_VALUE_TYPE_BY_ID = {t.id: t.value_type for t in SENSOR_TYPES}
_MISSING_GAP_THRESHOLD = timedelta(hours=1)  # MVP heuristic -- see schema module docstring
_GRANULARITY_PATTERN = re.compile(r"^(\d+)([smhd])$")
_GRANULARITY_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def value_type_for(sensor_type_id: str) -> str:
    """Resolve a sensor_type_id to "numeric" or "categorical"."""
    return _VALUE_TYPE_BY_ID.get(sensor_type_id, "categorical")


def parse_granularity_seconds(granularity: str | None) -> int | None:
    """Parse a granularity string like "5m"/"1h"/"1d" into seconds.

    Args:
        granularity: The raw query parameter, or None.

    Returns:
        The bucket size in seconds, or None if no granularity was given.

    Raises:
        ApiError: 400 if the string does not match `<int><s|m|h|d>`.
    """
    if granularity is None:
        return None
    match = _GRANULARITY_PATTERN.match(granularity.strip().lower())
    if match is None:
        raise ApiError(400, "VALIDATION_ERROR", "granularity must look like '5m', '1h', '1d'")
    amount, unit = match.groups()
    return int(amount) * _GRANULARITY_UNIT_SECONDS[unit]


async def _load_readings(
    session: AsyncSession, channel_id: str, from_ts: datetime | None, to_ts: datetime | None
) -> list[SensorReading]:
    stmt = select(SensorReading).where(SensorReading.channel_id == channel_id).order_by(SensorReading.occurred_at)
    if from_ts is not None:
        stmt = stmt.where(SensorReading.occurred_at >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(SensorReading.occurred_at <= to_ts)
    return (await session.execute(stmt)).scalars().all()


def _bucket_start(ts: datetime, bucket_seconds: int) -> datetime:
    epoch_seconds = int(ts.timestamp())
    floored = epoch_seconds - (epoch_seconds % bucket_seconds)
    return datetime.fromtimestamp(floored, tz=ts.tzinfo)


def _build_numeric_series(readings: list[SensorReading], granularity_seconds: int | None) -> NumericSeriesOut:
    missing_intervals: list[MissingInterval] = []
    for prev, curr in zip(readings, readings[1:]):
        if curr.occurred_at - prev.occurred_at > _MISSING_GAP_THRESHOLD:
            missing_intervals.append(MissingInterval(from_=prev.occurred_at, to=curr.occurred_at))

    if granularity_seconds is None:
        points = [
            NumericPoint(
                timestamp=r.occurred_at,
                value=r.numeric_value if r.numeric_value is not None else 0.0,
                state="alarm" if r.is_alarm else "normal",
                quality="anomaly" if r.is_anomaly else "good",
            )
            for r in readings
        ]
        return NumericSeriesOut(points=points, thresholds=[], missing_intervals=missing_intervals)

    buckets: dict[datetime, list[float]] = {}
    for r in readings:
        if r.numeric_value is None:
            continue
        bucket = _bucket_start(r.occurred_at, granularity_seconds)
        buckets.setdefault(bucket, []).append(r.numeric_value)

    points = [
        NumericPoint(timestamp=bucket, value=sum(values) / len(values), state="normal", quality="good")
        for bucket, values in sorted(buckets.items())
    ]
    return NumericSeriesOut(points=points, thresholds=[], missing_intervals=missing_intervals)


def _build_categorical_series(readings: list[SensorReading]) -> CategoricalSeriesOut:
    intervals: list[CategoricalInterval] = []
    for reading in readings:
        if intervals and intervals[-1].value == reading.raw_value:
            intervals[-1] = CategoricalInterval(
                from_=intervals[-1].from_,
                to=reading.occurred_at,
                value=intervals[-1].value,
                state="alarm" if reading.is_alarm else "normal",
            )
        else:
            intervals.append(
                CategoricalInterval(
                    from_=reading.occurred_at,
                    to=reading.occurred_at,
                    value=reading.raw_value,
                    state="alarm" if reading.is_alarm else "normal",
                )
            )
    return CategoricalSeriesOut(intervals=intervals)


async def get_sensor_series(
    session: AsyncSession,
    sensor_id: str,
    allowed_facility_ids: set[str] | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    granularity: str | None,
) -> NumericSeriesOut | CategoricalSeriesOut:
    """Fetch a sensor's series, dispatching numeric vs categorical format.

    Args:
        session: An active async database session.
        sensor_id: The requested sensor id.
        allowed_facility_ids: None for all_facilities scope, else the exact
            set of facility ids the caller may see.
        from_ts: Optional inclusive start of the time range.
        to_ts: Optional inclusive end of the time range.
        granularity: Optional bucket size (numeric only; e.g. "5m").

    Returns:
        A NumericSeriesOut or CategoricalSeriesOut depending on the
        sensor's value_type.

    Raises:
        ApiError: 404 if the sensor does not exist; 403 if out of scope.
    """
    channel = (await session.execute(select(SensorChannel).where(SensorChannel.id == sensor_id))).scalar_one_or_none()
    if channel is None:
        raise ApiError(404, "NOT_FOUND", "Датчик не найден")
    if allowed_facility_ids is not None:
        if channel.facility_id is None or channel.facility_id not in allowed_facility_ids:
            raise ApiError(403, "SENSOR_ACCESS_DENIED", "Недостаточно прав для просмотра датчика")

    readings = await _load_readings(session, channel.channel_id, from_ts, to_ts)
    value_type = value_type_for(channel.sensor_type_id)

    if value_type == "numeric":
        granularity_seconds = parse_granularity_seconds(granularity)
        return _build_numeric_series(readings, granularity_seconds)
    return _build_categorical_series(readings)
