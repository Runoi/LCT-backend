"""Recursive-CTE traversal of a facility's hierarchy_nodes (any depth)."""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.schemas.hierarchy import HierarchyNodeOut

_RECURSIVE_TREE_SQL = text(
    """
    WITH RECURSIVE tree AS (
        SELECT id, parent_id, facility_id, entity_type, entity_id, display_name
        FROM hierarchy_nodes
        WHERE facility_id = :facility_id AND parent_id IS NULL
        UNION ALL
        SELECT c.id, c.parent_id, c.facility_id, c.entity_type, c.entity_id, c.display_name
        FROM hierarchy_nodes c
        JOIN tree t ON c.parent_id = t.id
    )
    SELECT id, parent_id, entity_type, entity_id, display_name FROM tree
    """
)


async def get_facility_hierarchy(session: AsyncSession, facility_id: str) -> list[HierarchyNodeOut]:
    """Fetch every node in a facility's tree, at whatever depth it has.

    Args:
        session: An active async database session.
        facility_id: The facility whose tree to fetch.

    Returns:
        All nodes as HierarchyNodeOut, each with computed path/children_count/
        has_children; empty list if the facility has no nodes at all.
    """
    rows = (await session.execute(_RECURSIVE_TREE_SQL, {"facility_id": facility_id})).mappings().all()

    by_id = {row["id"]: dict(row) for row in rows}
    children_count: dict[str, int] = {row_id: 0 for row_id in by_id}
    for row in rows:
        if row["parent_id"] is not None and row["parent_id"] in children_count:
            children_count[row["parent_id"]] += 1

    def _path(node_id: str) -> list[str]:
        chain: list[str] = []
        current: str | None = node_id
        while current is not None:
            chain.append(current)
            current = by_id[current]["parent_id"]
        return list(reversed(chain))

    return [
        HierarchyNodeOut(
            id=row["id"],
            parent_id=row["parent_id"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            display_name=row["display_name"],
            path=_path(row["id"]),
            children_count=children_count[row["id"]],
            sensor_count=0,
            attention_count=0,
            current_state="unknown",
            risk_level="unknown",
            has_children=children_count[row["id"]] > 0,
        )
        for row in rows
    ]
