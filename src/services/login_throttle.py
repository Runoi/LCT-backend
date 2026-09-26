"""Brute-force protection for the login endpoint.

Failed attempts are counted per username and per client IP inside a
sliding window. Reaching either limit locks further attempts until the
oldest failure inside the window ages out. Attempts refused by the lock
are not counted, so the lock ends predictably instead of extending itself.
"""
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from src.config import get_settings
from src.models.login_failure import LoginFailure


@dataclass(frozen=True)
class LockoutPolicy:
    """Limits of the lockout: N per username, M per IP within a window."""

    max_per_username: int
    max_per_ip: int
    window: timedelta


def policy_from_settings() -> LockoutPolicy:
    """Build the lockout policy from the environment-driven settings."""
    settings = get_settings()
    return LockoutPolicy(
        max_per_username=settings.login_max_failures_per_username,
        max_per_ip=settings.login_max_failures_per_ip,
        window=timedelta(seconds=settings.login_failure_window_seconds),
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _unlock_at(
    session: AsyncSession,
    column: InstrumentedAttribute,
    value: str,
    limit: int,
    window_start: datetime,
    window: timedelta,
) -> datetime | None:
    times = (
        await session.execute(
            select(LoginFailure.occurred_at)
            .where(column == value, LoginFailure.occurred_at > window_start)
            .order_by(LoginFailure.occurred_at)
        )
    ).scalars().all()
    if len(times) < limit:
        return None
    # Блокировка снимается, когда из окна выпадает столько старых неудач, что их становится меньше лимита.
    return times[len(times) - limit] + window


async def seconds_until_unlocked(
    session: AsyncSession,
    username: str,
    ip: str | None,
    *,
    now: datetime | None = None,
    policy: LockoutPolicy | None = None,
) -> int | None:
    """Tell whether a login attempt must be refused, and for how long.

    Args:
        session: An active async database session.
        username: The submitted login (existing or not -- treated the same).
        ip: The client IP, or None when unknown (then only the username limit applies).
        now: Evaluation time; defaults to the current UTC time.
        policy: Limits to apply; defaults to the configured policy.

    Returns:
        Whole seconds until attempts are allowed again, or None if not locked.
    """
    now = now or _utcnow()
    policy = policy or policy_from_settings()
    window_start = now - policy.window

    candidates = [
        await _unlock_at(
            session, LoginFailure.username, username, policy.max_per_username, window_start, policy.window
        )
    ]
    if ip is not None:
        candidates.append(
            await _unlock_at(session, LoginFailure.ip, ip, policy.max_per_ip, window_start, policy.window)
        )

    unlock_times = [t for t in candidates if t is not None and t > now]
    if not unlock_times:
        return None
    return max(1, math.ceil((max(unlock_times) - now).total_seconds()))


async def record_failure(
    session: AsyncSession,
    username: str,
    ip: str | None,
    *,
    now: datetime | None = None,
    policy: LockoutPolicy | None = None,
) -> None:
    """Store one failed attempt and purge attempts that left every window.

    Args:
        session: An active async database session.
        username: The submitted login.
        ip: The client IP, if known.
        now: Attempt time; defaults to the current UTC time.
        policy: Limits in force (used for the purge horizon).
    """
    now = now or _utcnow()
    policy = policy or policy_from_settings()
    await session.execute(delete(LoginFailure).where(LoginFailure.occurred_at <= now - policy.window))
    session.add(LoginFailure(username=username, ip=ip, occurred_at=now))
    await session.commit()


async def clear_username_failures(session: AsyncSession, username: str) -> None:
    """Forget a username's failed attempts after a successful login.

    Per-IP failures are intentionally kept: one valid account must not reset
    an attacker's budget for guessing other accounts from the same address.

    Args:
        session: An active async database session.
        username: The login that just succeeded.
    """
    await session.execute(delete(LoginFailure).where(LoginFailure.username == username))
    await session.commit()
