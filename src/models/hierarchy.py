"""ORM models for facilities and their internal node hierarchy (ticket 04).

HierarchyNode is a plain adjacency list (`parent_id` self-reference) so
depth is never hardcoded — see `BACKEND_REQUIREMENTS_FROM_FRONTEND_TZ.md`
section 6.2. `Facility.district_id` reuses the `District` table from
`src/models/auth.py` per `docs/adr/0007-leaf-rows-are-facilities-level2-are-districts.md`.
"""
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Facility(Base):
    """A top-level monitored facility (leaf row of the object catalogue)."""

    __tablename__ = "facilities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    facility_type: Mapped[str] = mapped_column(String)
    district_id: Mapped[str | None] = mapped_column(ForeignKey("districts.id"), nullable=True)


class HierarchyNode(Base):
    """One node in a facility's internal structure (adjacency list, any depth)."""

    __tablename__ = "hierarchy_nodes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("hierarchy_nodes.id"), nullable=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
