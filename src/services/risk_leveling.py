"""Pure risk-level/priority/data-health derivation (ticket 08).

Reuses reference_data.py's RISK_LEVELS/SLA_PARAMS/FRESHNESS_BOUNDARIES
(ticket 02) as the single source of truth for thresholds -- never
re-declares them here.
"""
from datetime import datetime, timedelta, timezone

from src.services.reference_data import FRESHNESS_BOUNDARIES, RISK_LEVELS, SLA_PARAMS

_PROBABILITY_WEIGHT = 70.0
_URGENCY_WEIGHT = 30.0


def risk_level_for_probability(probability: float) -> tuple[str, float]:
    """Map a probability to its RISK_LEVELS bucket.

    Args:
        probability: A value in [0, 1].

    Returns:
        (risk_level_id, threshold) where threshold is that bucket's
        min_probability -- the value the API exposes as `threshold`.
    """
    for level in RISK_LEVELS:
        if level.min_probability <= probability < level.max_probability:
            return level.id, level.min_probability
    last = RISK_LEVELS[-1]
    return last.id, last.min_probability


def sla_due_at_for_risk_level(risk_level: str, as_of: datetime) -> datetime:
    """Compute the SLA deadline for a risk level, reusing SLA_PARAMS.

    Args:
        risk_level: A RISK_LEVELS id.
        as_of: The forecast's snapshot time.

    Returns:
        as_of + that risk level's documented response_minutes.
    """
    param = next(p for p in SLA_PARAMS if p.risk_level == risk_level)
    return as_of + timedelta(minutes=param.response_minutes)


def compute_priority_score(probability: float, as_of: datetime, sla_due_at: datetime, *, now: datetime | None = None) -> float:
    """Compute a ranking score independent of probability alone.

    Args:
        probability: The forecast's probability.
        as_of: The forecast's snapshot time.
        sla_due_at: The SLA deadline for this forecast's risk level.
        now: Wall-clock time to evaluate urgency against (tests pass an
            explicit value; production uses real UTC now).

    Returns:
        probability*70 + urgency*30, where urgency in [0, 1] grows as
        `now` approaches `sla_due_at` -- two forecasts with equal
        probability but different SLA urgency rank differently.
    """
    now = now or datetime.now(timezone.utc)
    total_seconds = (sla_due_at - as_of).total_seconds()
    elapsed_seconds = (now - as_of).total_seconds()
    urgency = 0.0 if total_seconds <= 0 else max(0.0, min(1.0, elapsed_seconds / total_seconds))
    return round(probability * _PROBABILITY_WEIGHT + urgency * _URGENCY_WEIGHT, 2)


def compute_data_health(as_of: datetime, *, now: datetime | None = None) -> str:
    """Bucket a forecast's data freshness, reusing FRESHNESS_BOUNDARIES.

    Args:
        as_of: The forecast's snapshot time.
        now: Wall-clock time to evaluate age against.

    Returns:
        A FRESHNESS_BOUNDARIES id.
    """
    now = now or datetime.now(timezone.utc)
    age_seconds = (now - as_of).total_seconds()
    for boundary in FRESHNESS_BOUNDARIES:
        if boundary.max_age_seconds is not None and age_seconds <= boundary.max_age_seconds:
            return boundary.id
    return FRESHNESS_BOUNDARIES[-1].id
