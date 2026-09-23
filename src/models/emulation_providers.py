"""Synthetic external-source providers (ticket 06): ОДС journal, equipment
registry, external work-order backlog. All grounded in real per-facility
data from ticket 05 (see the respective `src/services/*_provider.py`
generators), never uniform random noise.

`SyntheticProviderRun` is the shared idempotency marker AND the
`last_success_at` source for `src/services/source_health.py` -- the same
pattern as `EtlIngestedSource` in ticket 05.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class SyntheticProviderRun(Base):
    """Idempotency + freshness marker for one synthetic provider's seed run."""

    __tablename__ = "synthetic_provider_runs"

    provider: Mapped[str] = mapped_column(String, primary_key=True)
    last_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    row_count: Mapped[int] = mapped_column(Integer)


class OdsJournalEntry(Base):
    """A synthetic ОДС (dispatch desk) journal entry.

    Per QA_ORGANIZERS_CLARIFICATIONS.md section 6, the real ОДС journal has
    no key linkage to sensor event data -- this table is deliberately its
    own entity, not a foreign key onto SensorReading.
    """

    __tablename__ = "ods_journal_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"))
    system_type: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    description: Mapped[str] = mapped_column(String)


class EquipmentRegistryItem(Base):
    """A synthetic equipment-registry entry, one per (facility, system_type)
    actually present in the real sensor-channel catalogue -- fully
    deterministic, no RNG at all.
    """

    __tablename__ = "equipment_registry_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"))
    system_type: Mapped[str] = mapped_column(String)
    channel_count: Mapped[int] = mapped_column(Integer)
    display_name: Mapped[str] = mapped_column(String)
    install_year: Mapped[int] = mapped_column(Integer)
    last_inspected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExternalWorkOrderRecord(Base):
    """A synthetic historical work-order backlog entry.

    Distinct from ticket 09's future `WorkOrder` domain table: this is
    background realism/source-health data only, never exposed through the
    `/work-orders` API.
    """

    __tablename__ = "external_work_order_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"))
    category: Mapped[str] = mapped_column(String)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String)
