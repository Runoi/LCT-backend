"""FastAPI application entrypoint."""
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.audit import router as audit_router
from src.api.auth import router as auth_router
from src.api.config import router as config_router
from src.api.events import router as events_router
from src.api.facilities import router as facilities_router
from src.api.risks import router as risks_router
from src.api.work_orders import router as work_orders_router
from src.api.hierarchy import router as hierarchy_router
from src.api.layout import router as layout_router
from src.api.me import router as me_router
from src.api.sensor_series import router as sensor_series_router
from src.api.sensors import router as sensors_router
from src.api.system import router as system_router
from src.db import async_session_factory, get_session
from src.errors import register_exception_handlers
from src.services.audit_recorder import AuditMiddleware
from src.services.demo_seed import seed_demo_users
from src.services.equipment_registry_provider import generate_equipment_registry
from src.services.event_etl import ingest_event_log
from src.services.event_sync import sync_events
from src.services.ml_predictor_factory import get_predictor
from src.services.risk_sync import sync_risks
from src.services.facility_seed import seed_facility_catalogue
from src.services.ods_journal_provider import generate_ods_journal
from src.services.replay_engine import run_replay_loop
from src.services.sensor_channel_seed import seed_sensor_channel_catalogue
from src.services.work_order_backlog_provider import generate_work_order_backlog


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Seed facilities/sensor channels, ingest the operational window, seed demo users.

    Also starts the SMVU replay engine as a background task (ticket 06) and
    cancels it on shutdown.
    """
    async with async_session_factory() as session:
        await seed_facility_catalogue(session)
        await seed_sensor_channel_catalogue(session)
        await ingest_event_log(session)
        await seed_demo_users(session)
        await generate_ods_journal(session)
        await generate_equipment_registry(session)
        await generate_work_order_backlog(session)
        await sync_events(session)
        await sync_risks(session, get_predictor())

    replay_task = asyncio.create_task(run_replay_loop(async_session_factory))
    try:
        yield
    finally:
        replay_task.cancel()


app = FastAPI(title="Moskollektor Backend", version="0.1.0", lifespan=lifespan)
app.add_middleware(AuditMiddleware)
register_exception_handlers(app)
app.include_router(config_router)
app.include_router(auth_router)
app.include_router(me_router)
app.include_router(facilities_router)
app.include_router(hierarchy_router)
app.include_router(layout_router)
app.include_router(sensors_router)
app.include_router(sensor_series_router)
app.include_router(system_router)
app.include_router(events_router)
app.include_router(risks_router)
app.include_router(work_orders_router)
app.include_router(audit_router)


@app.get("/health")
async def health(
    response: Response, session: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    """Report service liveness including database connectivity.

    Args:
        response: Injected FastAPI response, used to set the status code on failure.
        session: Injected database session (overridable in tests).

    Returns:
        A status payload: {"status": "ok"} when the database is reachable,
        {"status": "unavailable"} with a 503 status otherwise.
    """
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, ConnectionError):
        response.status_code = 503
        return {"status": "unavailable"}
    return {"status": "ok"}
