"""Facility-level risks from the ML service's object models (POST /risk_map).

For each target ("incident" 72h, "failure" 168h) the ML service ranks all
facilities; every facility with `alert` becomes one open Risk with
target_type="facility". A facility that already has an open risk of the
same model with an unfinished window is skipped, so repeated syncs do not
duplicate. Any ML-side problem surfaces as ObjectRiskError and nothing is
committed.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.hierarchy import Facility
from src.models.risk import Risk
from src.services.reference_data import SENSOR_TYPES
from src.services.risk_leveling import (
    compute_data_health,
    compute_priority_score,
    risk_level_for_probability,
    sla_due_at_for_risk_level,
)

OBJECT_TARGETS = ("incident", "failure")
_INCIDENT_RISK_TYPE_BY_SYSTEM_TYPE = {
    "fire_protection": "fire",
    "security": "unauthorized_access",
    "diagnostic": "flooding",
}
_FLOODING_SENSOR_NAMES = {"Состояние насоса", "Датчик затопления"}
_SYSTEM_TYPE_BY_SENSOR_NAME = {sensor.display_name: sensor.system_type for sensor in SENSOR_TYPES}
_DEFAULT_INCIDENT_RISK_TYPE = "unauthorized_access"


class ObjectRiskError(Exception):
    """The ML service's /risk_map could not be used (unreachable, non-200 or malformed)."""


def incident_risk_type(suspect_channels: list[dict]) -> str:
    """Pick a risk_type for an incident alert from the first recognizable suspect channel.

    Args:
        suspect_channels: The ML service's suspect channels, most suspicious first.

    Returns:
        "flooding" for pump/flood sensors, otherwise the risk_type of the
        channel's engineering system, or "unauthorized_access" if none is known.
    """
    for suspect in suspect_channels:
        name = suspect.get("sensor_type")
        if name in _FLOODING_SENSOR_NAMES:
            return "flooding"
        risk_type = _INCIDENT_RISK_TYPE_BY_SYSTEM_TYPE.get(_SYSTEM_TYPE_BY_SENSOR_NAME.get(name, ""))
        if risk_type is not None:
            return risk_type
    return _DEFAULT_INCIDENT_RISK_TYPE


def recommendation_for(target: str, suspect_channels: list[dict]) -> str:
    """Build the dispatcher-facing recommendation text, naming up to three suspect channels."""
    where = ", ".join(f"{s['target_id']} ({s.get('sensor_type') or 'тип неизвестен'})" for s in suspect_channels[:3])
    action = "Проверить оборудование объекта" if target == "failure" else "Проверить объект"
    return f"{action}; в первую очередь каналы: {where}" if where else action


async def fetch_risk_map(client: httpx.AsyncClient, target: str, as_of: datetime) -> dict:
    """Request the ML service's facility ranking for one target.

    Args:
        client: HTTP client pointed at ML_PREDICTOR_URL.
        target: "incident" or "failure".
        as_of: Forecast time.

    Returns:
        The decoded response with `horizon_hours` and `objects`.

    Raises:
        ObjectRiskError: On transport error, non-200 status or malformed body.
    """
    try:
        response = await client.post("/risk_map", json={"as_of": as_of.isoformat(), "target": target})
    except httpx.HTTPError as exc:
        raise ObjectRiskError(f"risk_map request failed: {exc}") from exc
    if response.status_code != 200:
        raise ObjectRiskError(f"risk_map returned {response.status_code}: {response.text}")
    try:
        data = response.json()
        float(data["horizon_hours"])
        list(data["objects"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ObjectRiskError(f"malformed risk_map response: {response.text}") from exc
    return data


async def _has_open_risk(session: AsyncSession, facility_id: str, model: str, now: datetime) -> bool:
    found = await session.execute(
        select(Risk.id)
        .where(
            Risk.target_type == "facility",
            Risk.target_id == facility_id,
            Risk.model == model,
            Risk.decision_status == "open",
            Risk.prediction_window_end > now,
        )
        .limit(1)
    )
    return found.scalar_one_or_none() is not None


def _parse_alert_row(row: dict) -> tuple[str, str, float, list[str], list[dict]]:
    # Битая строка ответа ML не должна ронять старт backend: превращаем в ObjectRiskError.
    try:
        return (
            f"fac_{row['object_id']}",
            str(row["model_name"]),
            float(row["probability"]),
            [str(factor["text"]) for factor in row.get("top_factors") or []],
            list(row.get("suspect_channels") or []),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ObjectRiskError(f"malformed risk_map row: {row!r}") from exc


async def sync_object_risks(session: AsyncSession, client: httpx.AsyncClient, *, now: datetime | None = None) -> int:
    """Create facility risks for every object the ML service alerts on.

    Args:
        session: An active async database session.
        client: HTTP client pointed at ML_PREDICTOR_URL.
        now: Forecast time; defaults to the current UTC time.

    Returns:
        The number of Risk rows created.

    Raises:
        ObjectRiskError: The ML service failed or answered malformed data;
            nothing is committed in that case.
    """
    now = now or datetime.now(timezone.utc)
    created_count = 0
    for target in OBJECT_TARGETS:
        data = await fetch_risk_map(client, target, now)
        horizon_hours = float(data["horizon_hours"])
        for row in data["objects"]:
            if row.get("status") != "ok" or not row.get("alert"):
                continue
            facility_id, model_name, probability, factor_texts, suspects = _parse_alert_row(row)
            if await session.get(Facility, facility_id) is None:
                continue
            if await _has_open_risk(session, facility_id, model_name, now):
                continue
            risk_type = "sensor_failure" if target == "failure" else incident_risk_type(suspects)
            risk_level, threshold = risk_level_for_probability(probability)
            sla_due_at = sla_due_at_for_risk_level(risk_level, now)
            risk_id = f"risk_{uuid4().hex[:20]}"
            session.add(
                Risk(
                    id=risk_id,
                    forecast_id=risk_id,
                    risk_type=risk_type,
                    target_type="facility",
                    target_id=facility_id,
                    facility_id=facility_id,
                    as_of=now,
                    lead_min_hours=0.0,
                    horizon_hours=horizon_hours,
                    prediction_window_start=now,
                    prediction_window_end=now + timedelta(hours=horizon_hours),
                    probability=probability,
                    threshold=threshold,
                    risk_level=risk_level,
                    priority_score=compute_priority_score(probability, now, sla_due_at, now=now),
                    decision_status="open",
                    sla_due_at=sla_due_at,
                    data_health=compute_data_health(now, now=now),
                    model=model_name,
                    top_factors=factor_texts,
                    recommendation=recommendation_for(target, suspects),
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            created_count += 1
    await session.commit()
    return created_count
