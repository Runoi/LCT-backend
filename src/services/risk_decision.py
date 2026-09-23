"""Shared risk-decision logic: optimistic concurrency + append-only journal (ticket 08)."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.errors import ApiError
from src.models.auth import User
from src.models.risk import Risk, RiskDecision
from src.services.risk_query import to_risk_out


async def apply_decision(
    session: AsyncSession,
    risk: Risk,
    user: User,
    decision: str,
    expected_version: int,
    *,
    reason_code: str | None = None,
    comment: str | None = None,
    now: datetime | None = None,
) -> Risk:
    """Apply a decision to a risk with optimistic concurrency.

    Args:
        session: An active async database session.
        risk: The risk row (already scope/permission-checked by the caller).
        user: The deciding user.
        decision: One of "acknowledged", "rejected", "deferred".
        expected_version: The version the caller last saw.
        reason_code: The reject reason (only meaningful for "rejected";
            validated by the caller, not here).
        comment: The free-text comment (only meaningful for "rejected"
            with reason_code="other"; validated by the caller).
        now: Wall-clock time to record (defaults to real UTC now).

    Returns:
        The updated Risk.

    Raises:
        ApiError: 409 CONFLICT if expected_version does not match the
            risk's current version -- `details.current` carries the
            risk's current (not stale) serialized state.
    """
    now = now or datetime.now(timezone.utc)

    if risk.version != expected_version:
        raise ApiError(
            409,
            "CONFLICT",
            "Версия прогноза устарела, обновите карточку",
            details={"current": to_risk_out(risk).model_dump(mode="json")},
        )

    risk.decision_status = decision
    risk.version += 1
    risk.updated_at = now

    session.add(
        RiskDecision(
            id=f"riskdec_{uuid4().hex[:20]}",
            risk_id=risk.id,
            user_id=user.id,
            decision=decision,
            reason_code=reason_code,
            comment=comment,
            decided_at=now,
        )
    )
    await session.commit()
    await session.refresh(risk)
    return risk
