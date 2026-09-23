"""Synthetic equipment registry generator (ticket 06).

Fully deterministic -- no RNG at all: one registry item per (facility_id,
system_type) actually present in the real sensor-channel catalogue
(ticket 05), with a stable pseudo install_year derived by hashing the
facility_id+system_type key (never random per run).
"""
import hashlib
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.emulation_providers import EquipmentRegistryItem, SyntheticProviderRun
from src.models.sensor import SensorChannel

PROVIDER = "equipment_registry"

_SYSTEM_DISPLAY_NAMES = {
    "fire_protection": "Пожарная защита",
    "dispatch_control": "Диспетчерский контроль",
    "security": "Охрана",
    "temperature": "Температурный контроль",
    "gas_protection": "Газовая защита",
    "diagnostic": "Диагностика",
    "unknown": "Неизвестная система",
}

_INSTALL_YEAR_BASE = 2005
_INSTALL_YEAR_SPAN = 15


def _stable_install_year(key: str) -> int:
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    return _INSTALL_YEAR_BASE + (int(digest[:8], 16) % _INSTALL_YEAR_SPAN)


async def generate_equipment_registry(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Seed one deterministic equipment-registry item per real (facility, system_type), idempotently.

    Args:
        session: An active async database session.
        now: Wall-clock time recorded as this run's last_run_at.

    Returns:
        The number of items inserted (0 if already seeded).
    """
    already_run = await session.get(SyntheticProviderRun, PROVIDER)
    if already_run is not None:
        return 0

    now = now or datetime.now(timezone.utc)
    groups = (
        await session.execute(
            select(SensorChannel.facility_id, SensorChannel.system_type, func.count(SensorChannel.id))
            .where(SensorChannel.facility_id.isnot(None))
            .group_by(SensorChannel.facility_id, SensorChannel.system_type)
        )
    ).all()

    for facility_id, system_type, channel_count in groups:
        key = f"{facility_id}:{system_type}"
        session.add(
            EquipmentRegistryItem(
                id=f"eq_{key}",
                facility_id=facility_id,
                system_type=system_type,
                channel_count=channel_count,
                display_name=f"Группа: {_SYSTEM_DISPLAY_NAMES.get(system_type, system_type)}",
                install_year=_stable_install_year(key),
                last_inspected_at=None,
            )
        )

    session.add(SyntheticProviderRun(provider=PROVIDER, last_run_at=now, row_count=len(groups)))
    await session.commit()
    return len(groups)
