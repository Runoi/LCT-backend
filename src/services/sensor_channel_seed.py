"""Load the real sensor channel catalogue CSV into SensorChannel + HierarchyNode.

Reuses `reference_data.SENSOR_TYPES` (by Russian display_name, the exact
values used in the real catalogue) as the only source of sensor_type_id/
value_type classification -- this module does not re-derive it.
"""
import csv
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.hierarchy import Facility, HierarchyNode
from src.models.sensor import SensorChannel
from src.services.reference_data import SENSOR_TYPES

DEFAULT_CSV_PATH = Path("data") / "справочник_каналов_датчиков.csv"

_TYPE_BY_DISPLAY_NAME = {t.display_name: t for t in SENSOR_TYPES}


def _csv_path() -> Path:
    override = os.environ.get("SENSOR_CATALOG_CSV_PATH")
    return Path(override) if override else DEFAULT_CSV_PATH


async def seed_sensor_channel_catalogue(session: AsyncSession, csv_path: Path | None = None) -> None:
    """Seed sensor channels and one hierarchy node per channel.

    Idempotent per source: skips rows whose channel_id already exists,
    so re-running (or running a different fixture) is safe within a
    shared database -- the same lesson as `facility_seed.py`.

    Each channel becomes a HierarchyNode(entity_type="sensor") that is a
    direct child of its facility's root node; building/collector/section
    grouping from the `тег_инженерной_системы` pattern is out of scope
    for this ticket (see PLAN.md).

    Args:
        session: An active async database session.
        csv_path: Optional override path (defaults to the bundled catalogue
            or the SENSOR_CATALOG_CSV_PATH environment variable).
    """
    path = csv_path or _csv_path()
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    source_channel_ids = {row["ид_канала_данных"] for row in rows}
    existing_ids = set(
        (await session.execute(select(SensorChannel.channel_id).where(SensorChannel.channel_id.in_(source_channel_ids))))
        .scalars()
        .all()
    )
    new_rows = [row for row in rows if row["ид_канала_данных"] not in existing_ids]
    if not new_rows:
        return

    facility_root_ids = dict(
        (await session.execute(select(HierarchyNode.facility_id, HierarchyNode.id).where(HierarchyNode.parent_id.is_(None))))
        .all()
    )
    known_facility_ids = set((await session.execute(select(Facility.id))).scalars().all())

    for row in new_rows:
        channel_id = row["ид_канала_данных"]
        sensor_id = f"sensor_{channel_id}"
        type_entry = _TYPE_BY_DISPLAY_NAME.get(row["тип_датчика"])
        facility_id = f"fac_{row['ид_объект']}"

        if type_entry is None or facility_id not in known_facility_ids:
            # unknown sensor type or unknown facility: treat like an orphan
            # rather than guessing -- still recorded, never silently dropped
            session.add(
                SensorChannel(
                    id=sensor_id,
                    channel_id=channel_id,
                    tag=row["тег_инженерной_системы"],
                    sensor_type_id="unknown",
                    system_type="unknown",
                    display_name=row["название_датчика"],
                    facility_id=None,
                    hierarchy_node_id=None,
                )
            )
            continue

        node_id = f"node_{sensor_id}"
        session.add(
            SensorChannel(
                id=sensor_id,
                channel_id=channel_id,
                tag=row["тег_инженерной_системы"],
                sensor_type_id=type_entry.id,
                system_type=type_entry.system_type,
                display_name=row["название_датчика"],
                facility_id=facility_id,
                hierarchy_node_id=node_id,
            )
        )
        session.add(
            HierarchyNode(
                id=node_id,
                parent_id=facility_root_ids.get(facility_id),
                facility_id=facility_id,
                entity_type="sensor",
                entity_id=sensor_id,
                display_name=row["название_датчика"],
            )
        )

    await session.commit()
