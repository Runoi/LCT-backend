"""Pydantic response model for a facility's internal node hierarchy."""
from pydantic import BaseModel


class HierarchyNodeOut(BaseModel):
    """One node of a facility's hierarchy tree.

    sensor_count/attention_count/current_state/risk_level are honest MVP
    placeholders (0/0/"unknown"/"unknown") pending ticket 05 (sensor
    timeseries) and ticket 08 (risk); children_count/has_children/path
    are real, computed from the actual adjacency-list data.
    """

    id: str
    parent_id: str | None
    entity_type: str
    entity_id: str
    display_name: str
    path: list[str]
    children_count: int
    sensor_count: int
    attention_count: int
    current_state: str
    risk_level: str
    has_children: bool
