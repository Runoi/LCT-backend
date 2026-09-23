"""Materialize Risk rows from not-yet-evaluated Event rows (ticket 08).

Groups Events by sensor_id, calls the injected predictor once per group,
creates one Risk, and links every event in the group back via
related_risk_id -- the real write path ticket 07 left as a placeholder.
Idempotent via RiskSyncState.last_synced_event_id (mirrors
event_sync.py's own high-water-mark pattern).
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.event import Event
from src.models.risk import SINGLETON_ID, Risk, RiskSyncState
from src.models.sensor import SensorChannel
from src.services.event_sync import sync_events
from src.services.ml_port import MLPredictor, PredictionInput
from src.services.risk_leveling import (
    compute_data_health,
    compute_priority_score,
    risk_level_for_probability,
    sla_due_at_for_risk_level,
)

_BATCH_SIZE = 2000

_RISK_TYPE_BY_SYSTEM_TYPE: dict[str, str] = {
    "fire_protection": "fire",
    "security": "unauthorized_access",
    "diagnostic": "flooding",  # flood_sensor's system_type (reference_data.py)
}
_DEFAULT_RISK_TYPE = "sensor_failure"  # dispatch_control/temperature/gas_protection/unknown


def risk_type_for_system_type(system_type: str) -> str:
    """Map a channel's engineering system to a RISK_TYPES id.

    Args:
        system_type: SensorChannel.system_type.

    Returns:
        The mapped risk_type id, or "sensor_failure" (the general
        equipment-failure category) for any system_type not explicitly
        mapped.
    """
    return _RISK_TYPE_BY_SYSTEM_TYPE.get(system_type, _DEFAULT_RISK_TYPE)


async def sync_risks(session: AsyncSession, predictor: MLPredictor, *, now: datetime | None = None) -> int:
    """Materialize Risk rows from newly-alarmed Events, one per sensor group.

    Args:
        session: An active async database session.
        predictor: The MLPredictor to call once per sensor group.
        now: Wall-clock time recorded as as_of/created_at/updated_at
            (defaults to real UTC now; tests pass an explicit value).

    Returns:
        The number of Risk rows created.
    """
    await sync_events(session, now=now)
    now = now or datetime.now(timezone.utc)

    state = (
        await session.execute(select(RiskSyncState).where(RiskSyncState.id == SINGLETON_ID))
    ).scalar_one_or_none()
    if state is None:
        state = RiskSyncState(id=SINGLETON_ID, last_synced_event_id="")
        session.add(state)

    created_count = 0
    while True:
        rows = (
            await session.execute(
                select(Event)
                .where(Event.id > state.last_synced_event_id, Event.related_risk_id.is_(None))
                .order_by(Event.id)
                .limit(_BATCH_SIZE)
            )
        ).scalars().all()
        if not rows:
            break

        groups: dict[str, list[Event]] = defaultdict(list)
        for event in rows:
            groups[event.sensor_id].append(event)

        for sensor_id, group_events in groups.items():
            channel = (
                await session.execute(select(SensorChannel).where(SensorChannel.id == sensor_id))
            ).scalar_one_or_none()
            if channel is None:
                # channel gone since the event was synced -- skip this
                # group rather than fail the whole batch over stale data.
                continue

            risk_type = risk_type_for_system_type(channel.system_type)
            alarm_count = sum(1 for e in group_events if e.state == "alarm")
            anomaly_count = sum(1 for e in group_events if e.state == "fault")
            occurred_ats = [e.occurred_at for e in group_events]
            window_hours = max((max(occurred_ats) - min(occurred_ats)).total_seconds() / 3600.0, 1.0)

            prediction = await predictor.predict(
                PredictionInput(
                    target_type="sensor",
                    target_id=sensor_id,
                    risk_type=risk_type,
                    as_of=now,
                    recent_alarm_count=alarm_count,
                    recent_anomaly_count=anomaly_count,
                    window_hours=window_hours,
                )
            )

            risk_level, threshold = risk_level_for_probability(prediction.probability)
            sla_due_at = sla_due_at_for_risk_level(risk_level, now)
            priority_score = compute_priority_score(prediction.probability, now, sla_due_at, now=now)
            data_health = compute_data_health(now, now=now)
            window_start = now + timedelta(hours=prediction.lead_min_hours)
            window_end = window_start + timedelta(hours=prediction.prediction_window_hours)
            risk_id = f"risk_{uuid4().hex[:20]}"

            session.add(
                Risk(
                    id=risk_id,
                    forecast_id=risk_id,
                    risk_type=risk_type,
                    target_type="sensor",
                    target_id=sensor_id,
                    facility_id=channel.facility_id,
                    as_of=now,
                    lead_min_hours=prediction.lead_min_hours,
                    horizon_hours=prediction.prediction_window_hours,
                    prediction_window_start=window_start,
                    prediction_window_end=window_end,
                    probability=prediction.probability,
                    threshold=threshold,
                    risk_level=risk_level,
                    priority_score=priority_score,
                    decision_status="open",
                    sla_due_at=sla_due_at,
                    data_health=data_health,
                    model=prediction.model_name,
                    top_factors=prediction.top_factors,
                    recommendation=prediction.recommendation,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            for event in group_events:
                event.related_risk_id = risk_id
            created_count += 1

        state.last_synced_event_id = rows[-1].id
        await session.commit()

        if len(rows) < _BATCH_SIZE:
            break

    return created_count
