"""Round-trip tests for Risk/RiskDecision (leaf 1.2.1)."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from src.db import async_session_factory
from src.models.auth import User
from src.models.risk import Risk, RiskDecision


async def _seed_user(user_id: str) -> None:
    async with async_session_factory() as session:
        if await session.get(User, user_id) is None:
            session.add(User(id=user_id, username=user_id, password_hash="x", display_name=user_id, role="test"))
            await session.commit()


@pytest.mark.asyncio
async def test_risk_round_trip_with_top_factors_json() -> None:
    now = datetime(2035, 1, 1, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        session.add(
            Risk(
                id="risk_schema_test_1",
                forecast_id="risk_schema_test_1",
                risk_type="fire",
                target_type="sensor",
                target_id="sensor_schema_test",
                facility_id=None,
                as_of=now,
                lead_min_hours=2.0,
                horizon_hours=6.0,
                prediction_window_start=now,
                prediction_window_end=now,
                probability=0.5,
                threshold=0.3,
                risk_level="medium",
                priority_score=42.0,
                decision_status="open",
                sla_due_at=now,
                data_health="fresh",
                model="stub-v1",
                top_factors=["factor one", "factor two"],
                recommendation="do something",
                version=1,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        risk = await session.get(Risk, "risk_schema_test_1")
    assert risk.top_factors == ["factor one", "factor two"]
    assert risk.facility_id is None
    assert risk.version == 1


@pytest.mark.asyncio
async def test_risk_decision_round_trip_with_nullable_reason_and_comment() -> None:
    await _seed_user("usr_risk_schema_test")
    now = datetime(2035, 1, 1, tzinfo=timezone.utc)

    async with async_session_factory() as session:
        session.add(
            RiskDecision(
                id="riskdec_schema_test_1",
                risk_id="risk_schema_test_1",
                user_id="usr_risk_schema_test",
                decision="deferred",
                reason_code=None,
                comment=None,
                decided_at=now,
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        decisions = (
            await session.execute(select(RiskDecision).where(RiskDecision.risk_id == "risk_schema_test_1"))
        ).scalars().all()
    assert len(decisions) == 1
    assert decisions[0].reason_code is None
    assert decisions[0].comment is None
    assert decisions[0].decision == "deferred"
