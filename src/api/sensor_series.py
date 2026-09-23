"""GET /api/v1/sensors/{sensor_id}/series."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from src.db import async_session_factory
from src.deps.auth import get_current_user
from src.models.auth import User
from src.schemas.sensor_series import CategoricalSeriesOut, NumericSeriesOut
from src.services.scope import resolve_scope
from src.services.sensor_series_query import get_sensor_series

router = APIRouter(prefix="/api/v1", tags=["sensor-series"])


@router.get("/sensors/{sensor_id}/series", response_model=NumericSeriesOut | CategoricalSeriesOut)
async def get_series(
    sensor_id: str,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    granularity: str | None = Query(default=None),
    user: User = Depends(get_current_user),
) -> NumericSeriesOut | CategoricalSeriesOut:
    """Return a sensor's time series, in the format matching its value_type.

    Args:
        sensor_id: The requested sensor id.
        from_: Optional inclusive start of the time range.
        to: Optional inclusive end of the time range.
        granularity: Optional bucket size for numeric downsampling
            (e.g. "5m", "1h", "1d"); ignored for categorical sensors.
        user: The authenticated caller, injected by get_current_user.

    Returns:
        A NumericSeriesOut (points/thresholds/missing_intervals) or a
        CategoricalSeriesOut (intervals), matching the sensor's value_type.

    Raises:
        ApiError: 404 if the sensor does not exist; 403 if out of scope.
    """
    async with async_session_factory() as session:
        scope = await resolve_scope(session, user.id)
        allowed_ids = None if scope["type"] == "all_facilities" else set(scope["facility_ids"])
        return await get_sensor_series(session, sensor_id, allowed_ids, from_, to, granularity)
