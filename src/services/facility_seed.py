"""Load the real facility catalogue CSV into District/Facility/HierarchyNode.

See `docs/adr/0007-leaf-rows-are-facilities-level2-are-districts.md`:
level-3 (leaf) rows become Facility records, level-2 rows become District
records (the same District table ticket 03 uses for scope), the single
level-1 root is not exposed.
"""
import csv
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.auth import District
from src.models.hierarchy import Facility, HierarchyNode

DEFAULT_CSV_PATH = Path("data") / "справочник_объектов_диспетчер.csv"


def _csv_path() -> Path:
    override = os.environ.get("FACILITY_CATALOG_CSV_PATH")
    return Path(override) if override else DEFAULT_CSV_PATH


async def seed_facility_catalogue(session: AsyncSession, csv_path: Path | None = None) -> None:
    """Seed districts, facilities, and each facility's root hierarchy node.

    Idempotent per source: checks whether this specific CSV's facility ids
    are already present (not "any Facility exists anywhere"), so seeding
    two different catalogue files into the same database does not block
    the second one -- e.g. the real catalogue and a small test fixture
    can both be loaded into the same test database independently.

    Args:
        session: An active async database session.
        csv_path: Optional override path to the catalogue CSV (defaults to
            the bundled `data/справочник_объектов_диспетчер.csv`, or the
            `FACILITY_CATALOG_CSV_PATH` environment variable).
    """
    path = csv_path or _csv_path()
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    facility_ids_in_source = {f"fac_{row['ид_объект']}" for row in rows if row["иерархия_уровень"] == "3"}
    if facility_ids_in_source:
        existing = (
            await session.execute(select(Facility.id).where(Facility.id.in_(facility_ids_in_source)))
        ).scalars().all()
        if set(existing) == facility_ids_in_source:
            return

    for row in rows:
        level = row["иерархия_уровень"]
        object_id = row["ид_объект"]
        display_name = row["диспетчерское_название_объекта"]

        if level == "2":
            session.add(District(id=f"dist_{object_id}", name=display_name))
        elif level == "3":
            facility_id = f"fac_{object_id}"
            session.add(
                Facility(
                    id=facility_id,
                    display_name=display_name,
                    facility_type=row["вид_объекта"],
                    district_id=f"dist_{row['родитель']}",
                )
            )
            session.add(
                HierarchyNode(
                    id=f"node_{facility_id}",
                    parent_id=None,
                    facility_id=facility_id,
                    entity_type="facility",
                    entity_id=facility_id,
                    display_name=display_name,
                )
            )
        # level "1" (the single organization root) is intentionally not exposed

    await session.commit()
