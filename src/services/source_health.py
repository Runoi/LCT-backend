"""Source-health computation + artificial degradation (ticket 06).

Status is derived from each provider's own last-success timestamp against
`reference_data.FRESHNESS_BOUNDARIES` (ticket 02's single source of truth
for freshness thresholds -- not re-derived here). An active
`SourceHealthOverride` forces the reported status for its duration; this
is the service's own deterministic control, never a simulated live
external connection (per ticket 06's explicit requirement).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.emulation_providers import SyntheticProviderRun
from src.models.replay import SINGLETON_ID, ReplayState
from src.models.source_health import SourceHealthOverride
from src.services.reference_data import FRESHNESS_BOUNDARIES

SOURCES: tuple[tuple[str, str], ...] = (
    ("smvu", "СМВУ"),
    ("ods_journal", "Журнал ОДС"),
    ("equipment_registry", "Реестр оборудования"),
    ("work_order_system", "Система заявок"),
)
_SOURCE_IDS = {source for source, _ in SOURCES}
_VALID_STATUSES = ("online", "delayed", "unavailable")

_FRESH_MAX_AGE = next(b.max_age_seconds for b in FRESHNESS_BOUNDARIES if b.id == "fresh")
_DELAYED_MAX_AGE = next(b.max_age_seconds for b in FRESHNESS_BOUNDARIES if b.id == "delayed")


class UnknownSourceError(ValueError):
    """Raised when a source id is not one of `SOURCES`."""


class InvalidStatusError(ValueError):
    """Raised when a requested override status is not a valid contract status."""


@dataclass(frozen=True)
class SourceHealthEntryData:
    """One source's computed health, ready to serialize."""

    source: str
    display_name: str
    status: str
    last_success_at: datetime | None
    delay_seconds: int | None


def _status_for_age(age_seconds: float | None) -> str:
    if age_seconds is None:
        return "unavailable"
    if age_seconds <= _FRESH_MAX_AGE:
        return "online"
    if age_seconds <= _DELAYED_MAX_AGE:
        return "delayed"
    return "unavailable"


async def _last_success_at(session: AsyncSession, source: str) -> datetime | None:
    if source == "smvu":
        state = await session.get(ReplayState, SINGLETON_ID)
        return state.last_tick_at if state is not None else None
    run = await session.get(SyntheticProviderRun, source)
    return run.last_run_at if run is not None else None


async def get_source_health(session: AsyncSession, *, now: datetime | None = None) -> list[SourceHealthEntryData]:
    """Compute the current health of every source.

    Args:
        session: An active async database session.
        now: Wall-clock time to evaluate freshness/overrides against
            (defaults to real UTC now; tests pass an explicit value).

    Returns:
        One SourceHealthEntryData per entry in `SOURCES`, in that order.
    """
    now = now or datetime.now(timezone.utc)
    overrides = {
        row.source: row for row in (await session.execute(select(SourceHealthOverride))).scalars().all()
    }

    entries = []
    for source, display_name in SOURCES:
        last_success_at = await _last_success_at(session, source)
        age_seconds = (now - last_success_at).total_seconds() if last_success_at is not None else None

        override = overrides.get(source)
        if override is not None and override.expires_at > now:
            status = override.status
        else:
            status = _status_for_age(age_seconds)

        entries.append(
            SourceHealthEntryData(
                source=source,
                display_name=display_name,
                status=status,
                last_success_at=last_success_at,
                delay_seconds=int(age_seconds) if age_seconds is not None else None,
            )
        )
    return entries


async def set_source_health_override(
    session: AsyncSession, source: str, status: str, duration_seconds: float, *, now: datetime | None = None
) -> None:
    """Force a source's reported status for a bounded duration.

    Args:
        session: An active async database session.
        source: One of the ids in `SOURCES`.
        status: One of "online", "delayed", "unavailable".
        duration_seconds: How long the override stays active.
        now: Wall-clock time the duration is measured from.

    Raises:
        UnknownSourceError: `source` is not a known source id.
        InvalidStatusError: `status` is not a valid contract status.
    """
    if source not in _SOURCE_IDS:
        raise UnknownSourceError(f"Неизвестный источник: {source}")
    if status not in _VALID_STATUSES:
        raise InvalidStatusError(f"Недопустимый статус: {status}")

    now = now or datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=duration_seconds)
    existing = await session.get(SourceHealthOverride, source)
    if existing is not None:
        existing.status = status
        existing.expires_at = expires_at
    else:
        session.add(SourceHealthOverride(source=source, status=status, expires_at=expires_at))
    await session.commit()


async def clear_source_health_override(session: AsyncSession, source: str) -> None:
    """Remove an active override, if any, reverting to computed status.

    Args:
        session: An active async database session.
        source: One of the ids in `SOURCES`.

    Raises:
        UnknownSourceError: `source` is not a known source id.
    """
    if source not in _SOURCE_IDS:
        raise UnknownSourceError(f"Неизвестный источник: {source}")
    existing = await session.get(SourceHealthOverride, source)
    if existing is not None:
        await session.delete(existing)
        await session.commit()
