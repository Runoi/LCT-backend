"""Tests for pure risk-level/priority/data-health derivation (leaf 1.2.1)."""
from datetime import datetime, timedelta, timezone

from src.services.reference_data import RISK_LEVELS
from src.services.risk_leveling import (
    compute_data_health,
    compute_priority_score,
    risk_level_for_probability,
    sla_due_at_for_risk_level,
)


def test_risk_level_matches_reference_data_boundaries_exactly() -> None:
    for level in RISK_LEVELS:
        risk_level, threshold = risk_level_for_probability(level.min_probability)
        assert risk_level == level.id
        assert threshold == level.min_probability

    # just below the top of the last (critical) bucket
    risk_level, _ = risk_level_for_probability(0.999)
    assert risk_level == RISK_LEVELS[-1].id


def test_sla_due_at_uses_documented_sla_params() -> None:
    as_of = datetime(2035, 1, 1, tzinfo=timezone.utc)
    due = sla_due_at_for_risk_level("critical", as_of)
    assert due > as_of
    due_low = sla_due_at_for_risk_level("low", as_of)
    assert due < due_low  # critical has a tighter SLA than low


def test_priority_score_increases_as_sla_deadline_approaches_for_equal_probability() -> None:
    as_of = datetime(2035, 1, 1, tzinfo=timezone.utc)
    sla_due_at = as_of + timedelta(hours=4)

    far_from_deadline = compute_priority_score(0.5, as_of, sla_due_at, now=as_of + timedelta(hours=1))
    near_deadline = compute_priority_score(0.5, as_of, sla_due_at, now=as_of + timedelta(hours=3, minutes=55))
    assert near_deadline > far_from_deadline


def test_priority_score_is_not_just_probability() -> None:
    as_of = datetime(2035, 1, 1, tzinfo=timezone.utc)
    sla_due_at = as_of + timedelta(hours=4)
    score = compute_priority_score(0.5, as_of, sla_due_at, now=as_of)
    assert score != 0.5 * 100  # not a simple rescale of probability alone


def test_data_health_buckets_match_freshness_boundaries() -> None:
    as_of = datetime(2035, 1, 1, tzinfo=timezone.utc)
    assert compute_data_health(as_of, now=as_of) == "fresh"
    assert compute_data_health(as_of, now=as_of + timedelta(minutes=10)) == "delayed"
    assert compute_data_health(as_of, now=as_of + timedelta(minutes=30)) == "stale"
    assert compute_data_health(as_of, now=as_of + timedelta(hours=2)) == "unavailable"
