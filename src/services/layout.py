"""Schematic (never real-coordinate) GeoJSON layout for a facility's tree.

Per `QA_ORGANIZERS_CLARIFICATIONS.md` section 12, real coordinates will
never be provided; a schematic layout is explicitly recommended. This
places each hierarchy node on a deterministic grid (row = depth in the
tree, column = order among siblings at that depth) so the same facility
always renders the same layout.
"""
from collections import defaultdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.hierarchy_query import get_facility_hierarchy

_SPACING = 1.0


async def get_facility_layout(session: AsyncSession, facility_id: str) -> dict[str, Any]:
    """Build a schematic GeoJSON FeatureCollection, one Point per node.

    Args:
        session: An active async database session.
        facility_id: The facility whose tree to lay out.

    Returns:
        A GeoJSON FeatureCollection dict (empty features list if the
        facility has no hierarchy nodes yet).
    """
    nodes = await get_facility_hierarchy(session, facility_id)

    depth_counters: dict[int, int] = defaultdict(int)
    features = []
    for node in nodes:
        depth = len(node.path) - 1
        column = depth_counters[depth]
        depth_counters[depth] += 1
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(column * _SPACING, 3), round(depth * _SPACING, 3)],
                },
                "properties": {
                    "id": node.id,
                    "parent_id": node.parent_id,
                    "entity_type": node.entity_type,
                    "entity_id": node.entity_id,
                    "display_name": node.display_name,
                    "is_demo": True,
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}
