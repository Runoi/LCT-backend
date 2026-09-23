"""GET/POST /api/v1/system/* -- source-health status and the fixture-scenario/degradation demo controls (ticket 06)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from src.db import async_session_factory
from src.deps.auth import get_current_user
from src.errors import ApiError
from src.models.auth import User
from src.schemas.system import (
    ActivateScenarioRequest,
    ActivateScenarioResult,
    DegradeRequest,
    ScenarioListEnvelope,
    ScenarioOut,
    SourceHealthEntryOut,
    SourceHealthEnvelope,
    SourceHealthMeta,
)
from src.services.fixture_scenarios import SCENARIOS, ScenarioActivationError, activate_scenario
from src.services.source_health import (
    InvalidStatusError,
    UnknownSourceError,
    clear_source_health_override,
    get_source_health,
    set_source_health_override,
)

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/source-health", response_model=SourceHealthEnvelope)
async def get_source_health_endpoint(_: User = Depends(get_current_user)) -> SourceHealthEnvelope:
    """Return the current health of every emulated external source."""
    async with async_session_factory() as session:
        entries = await get_source_health(session)
    return SourceHealthEnvelope(
        data=[
            SourceHealthEntryOut(
                source=e.source, display_name=e.display_name, status=e.status,
                last_success_at=e.last_success_at, delay_seconds=e.delay_seconds,
            )
            for e in entries
        ],
        meta=SourceHealthMeta(generated_at=datetime.now(timezone.utc)),
    )


@router.post("/source-health/{source}/degrade", status_code=204)
async def degrade_source(source: str, body: DegradeRequest, _: User = Depends(get_current_user)) -> None:
    """Force a source's reported status for a bounded duration (demo/test control)."""
    async with async_session_factory() as session:
        try:
            await set_source_health_override(session, source, body.status, body.duration_seconds)
        except UnknownSourceError as exc:
            raise ApiError(404, "NOT_FOUND", str(exc)) from exc
        except InvalidStatusError as exc:
            raise ApiError(400, "VALIDATION_ERROR", str(exc)) from exc


@router.delete("/source-health/{source}/degrade", status_code=204)
async def clear_source_degradation(source: str, _: User = Depends(get_current_user)) -> None:
    """Clear an active override, reverting to the computed status."""
    async with async_session_factory() as session:
        try:
            await clear_source_health_override(session, source)
        except UnknownSourceError as exc:
            raise ApiError(404, "NOT_FOUND", str(exc)) from exc


@router.get("/scenarios", response_model=ScenarioListEnvelope)
async def list_scenarios(_: User = Depends(get_current_user)) -> ScenarioListEnvelope:
    """List the fixture-scenario library available for controlled demonstration."""
    return ScenarioListEnvelope(
        data=[
            ScenarioOut(id=s.id, display_name=s.display_name, category=s.category, description=s.description)
            for s in SCENARIOS
        ]
    )


@router.post("/scenarios/{scenario_id}/activate", response_model=ActivateScenarioResult)
async def activate_scenario_endpoint(
    scenario_id: str, body: ActivateScenarioRequest, _: User = Depends(get_current_user)
) -> ActivateScenarioResult:
    """Activate a fixture scenario against a real facility."""
    async with async_session_factory() as session:
        try:
            count = await activate_scenario(session, scenario_id, body.facility_id, seed=body.seed)
        except ScenarioActivationError as exc:
            raise ApiError(422, "DOMAIN_VALIDATION_ERROR", str(exc)) from exc
    return ActivateScenarioResult(scenario_id=scenario_id, facility_id=body.facility_id, readings_inserted=count)
