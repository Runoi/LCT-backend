"""Idempotent demo user seeding for the hackathon MVP.

The dispatcher's assigned facility_ids (`fac_5122`, `fac_5339`) are real
leaf-level ids from `data/справочник_объектов_диспетчер.csv` (see
`docs/adr/0007-leaf-rows-are-facilities-level2-are-districts.md`), chosen
so that once ticket 04 seeds the real facility catalogue, this demo
dispatcher's scope filters against real, existing facilities end to end.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.auth import User, UserPermission, UserScope, UserScopeFacility
from src.services.auth_service import hash_password
from src.services.permissions import PERMISSIONS

_DISPATCHER_PERMISSIONS = frozenset(
    {
        "facility.read.assigned",
        "sensor.read",
        "risk.read",
        "risk.acknowledge",
        "work_order.read",
        "work_order.create_draft",
    }
)
_DISPATCHER_FACILITY_IDS = ("fac_5122", "fac_5339")


async def seed_demo_users(session: AsyncSession) -> None:
    """Insert the two documented demo users if they do not already exist.

    Checks specifically for the "manager"/"dispatcher" usernames rather
    than "any row in users" so this stays idempotent even when other
    tests or code paths have already inserted unrelated user rows into
    the same database.

    Args:
        session: An active async database session.
    """
    existing = (
        await session.execute(select(User).where(User.username.in_(["manager", "dispatcher"])))
    ).scalars().all()
    if existing:
        return

    manager = User(
        id="usr_manager",
        username="manager",
        password_hash=hash_password("manager123"),
        display_name="Руководитель (демо)",
        role="Руководитель",
    )
    dispatcher = User(
        id="usr_dispatcher",
        username="dispatcher",
        password_hash=hash_password("dispatcher123"),
        display_name="Диспетчер объекта (демо)",
        role="Диспетчер объекта",
    )
    session.add_all([manager, dispatcher])

    for permission in PERMISSIONS:
        session.add(UserPermission(user_id="usr_manager", permission=permission))
    for permission in _DISPATCHER_PERMISSIONS:
        session.add(UserPermission(user_id="usr_dispatcher", permission=permission))

    session.add(UserScope(user_id="usr_manager", scope_type="all_facilities"))
    session.add(UserScope(user_id="usr_dispatcher", scope_type="assigned_facilities"))
    for facility_id in _DISPATCHER_FACILITY_IDS:
        session.add(UserScopeFacility(user_id="usr_dispatcher", facility_id=facility_id))

    await session.commit()
