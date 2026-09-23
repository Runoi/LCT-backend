"""Fixture-scenario library for controlled demonstration (ticket 06, ADR 0005).

Not a source-health degradation control (see `src/services/source_health.py`
for that, kept separate to avoid a forward dependency) -- these 16
scenarios exclusively generate SensorReading rows with `origin="fixture"`,
layered on top of the SMVU replay background stream. Each scenario is a
scripted, chronological sequence of steps against real `SENSOR_TYPES` ids
(`reference_data.py`); a step's channel is resolved to a real, existing
channel at the target facility, deterministically (lowest channel_id),
never randomly. A subset of scenarios add RNG jitter to step timing --
the organizers explicitly recommended generating the "fire" scenario with
a random-number generator (see `QA_ORGANIZERS_CLARIFICATIONS.md` section
6) -- reproducibility comes from the caller-supplied `seed`, not from the
absence of RNG.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from random import Random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.sensor import SensorChannel, SensorReading


class ScenarioActivationError(Exception):
    """Raised when a scenario cannot be activated as requested."""


@dataclass(frozen=True)
class ScenarioStep:
    """One scripted event within a scenario."""

    offset_seconds: float
    sensor_type_id: str
    raw_value: str
    is_alarm: bool = True
    numeric_value: float | None = None


@dataclass(frozen=True)
class FixtureScenario:
    """A named, reproducible incident scenario."""

    id: str
    display_name: str
    category: str
    description: str
    steps: tuple[ScenarioStep, ...]
    jitter_seconds: float = 0.0


def _step(offset_seconds: float, sensor_type_id: str, raw_value: str, is_alarm: bool = True) -> ScenarioStep:
    return ScenarioStep(offset_seconds=offset_seconds, sensor_type_id=sensor_type_id, raw_value=raw_value, is_alarm=is_alarm)


SCENARIOS: tuple[FixtureScenario, ...] = (
    # fire
    FixtureScenario(
        id="fire_smoke_only",
        display_name="Задымление",
        category="fire",
        description="Срабатывание датчика дыма без дальнейшей эскалации",
        steps=(_step(0, "smoke_detector", "Дым обнаружен"),),
    ),
    FixtureScenario(
        id="fire_smoke_and_heat",
        display_name="Дым и повышение температуры",
        category="fire",
        description="Дым, затем тепловой датчик подтверждает возгорание",
        steps=(_step(0, "smoke_detector", "Дым обнаружен"), _step(15, "heat_detector", "Превышение температуры")),
    ),
    FixtureScenario(
        id="fire_manual_call",
        display_name="Ручной вызов пожарной тревоги",
        category="fire",
        description="Человек нажимает ручной извещатель",
        steps=(_step(0, "manual_call_point", "Активирован"),),
    ),
    FixtureScenario(
        id="fire_full_escalation",
        display_name="Полная эскалация пожара",
        category="fire",
        description="Дым -> тепло -> ручной вызов; тайминг генерируется RNG (рекомендация организаторов)",
        steps=(
            _step(0, "smoke_detector", "Дым обнаружен"),
            _step(20, "heat_detector", "Превышение температуры"),
            _step(45, "manual_call_point", "Активирован"),
        ),
        jitter_seconds=5.0,
    ),
    # flooding
    FixtureScenario(
        id="flood_sensor_trigger",
        display_name="Подтопление",
        category="flooding",
        description="Срабатывание датчика затопления",
        steps=(_step(0, "flood_sensor", "Подтопление"),),
    ),
    FixtureScenario(
        id="flood_with_pump_response",
        display_name="Подтопление с реакцией насоса",
        category="flooding",
        description="Датчик затопления, затем авария откачивающего насоса",
        steps=(_step(0, "flood_sensor", "Подтопление"), _step(10, "pump_state", "Авария")),
    ),
    FixtureScenario(
        id="flood_slow_rise",
        display_name="Медленное нарастание подтопления",
        category="flooding",
        description="Влажно -> подтопление, с RNG-джиттером времени эскалации",
        steps=(
            _step(0, "flood_sensor", "Влажно", is_alarm=False),
            _step(600, "flood_sensor", "Подтопление"),
        ),
        jitter_seconds=60.0,
    ),
    FixtureScenario(
        id="flood_ups_backup_engaged",
        display_name="Подтопление с переходом на резервное питание",
        category="flooding",
        description="Датчик затопления, затем ИБП переходит на батарею",
        steps=(_step(0, "flood_sensor", "Подтопление"), _step(30, "ups_state", "Работа от батареи")),
    ),
    # unauthorized_access
    FixtureScenario(
        id="access_door_forced",
        display_name="Несанкционированное открытие двери",
        category="unauthorized_access",
        description="Контакт двери переходит в открытое состояние",
        steps=(_step(0, "door_contact", "Открыто"),),
    ),
    FixtureScenario(
        id="access_motion_after_hours",
        display_name="Движение в нерабочее время",
        category="unauthorized_access",
        description="Датчик движения фиксирует активность",
        steps=(_step(0, "motion_detector", "Движение обнаружено"),),
    ),
    FixtureScenario(
        id="access_glass_break",
        display_name="Разбитие стекла",
        category="unauthorized_access",
        description="Срабатывание датчика разбития стекла",
        steps=(_step(0, "glass_break_sensor", "Разбитие обнаружено"),),
    ),
    FixtureScenario(
        id="access_full_intrusion",
        display_name="Полная последовательность проникновения",
        category="unauthorized_access",
        description="Дверь -> движение -> состояние охраны, с RNG-джиттером тайминга",
        steps=(
            _step(0, "door_contact", "Открыто"),
            _step(5, "motion_detector", "Движение обнаружено"),
            _step(10, "security_state", "Тревога"),
        ),
        jitter_seconds=3.0,
    ),
    # sensor_failure / equipment
    FixtureScenario(
        id="equip_pump_fault",
        display_name="Авария насоса",
        category="sensor_failure",
        description="Насос переходит в аварийное состояние",
        steps=(_step(0, "pump_state", "Авария"),),
    ),
    FixtureScenario(
        id="equip_fan_offline",
        display_name="Отключение вентилятора",
        category="sensor_failure",
        description="Вентилятор переходит в отключённое состояние",
        steps=(_step(0, "fan_state", "Отключен"),),
    ),
    FixtureScenario(
        id="equip_ups_battery_low",
        display_name="Низкий заряд ИБП",
        category="sensor_failure",
        description="ИБП сигнализирует о низком заряде батареи",
        steps=(_step(0, "ups_state", "Низкий заряд батареи"),),
    ),
    FixtureScenario(
        id="equip_uir_r_fault",
        display_name="Неисправность УИР-Р",
        category="sensor_failure",
        description="Устройство искрозащиты реле переходит в состояние неисправности",
        steps=(_step(0, "uir_r_state", "Неисправность"),),
    ),
)

_SCENARIOS_BY_ID: dict[str, FixtureScenario] = {s.id: s for s in SCENARIOS}


def get_scenario(scenario_id: str) -> FixtureScenario | None:
    """Look up a scenario by id.

    Args:
        scenario_id: The scenario id.

    Returns:
        The FixtureScenario, or None if unknown.
    """
    return _SCENARIOS_BY_ID.get(scenario_id)


async def _resolve_channel_id(session: AsyncSession, facility_id: str, sensor_type_id: str) -> str:
    channel = (
        await session.execute(
            select(SensorChannel)
            .where(SensorChannel.facility_id == facility_id, SensorChannel.sensor_type_id == sensor_type_id)
            .order_by(SensorChannel.channel_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if channel is None:
        raise ScenarioActivationError(
            f"Объект {facility_id} не имеет канала типа {sensor_type_id}, сценарий недоступен"
        )
    return channel.channel_id


async def activate_scenario(
    session: AsyncSession,
    scenario_id: str,
    facility_id: str,
    *,
    seed: int = 42,
    now: datetime | None = None,
) -> int:
    """Activate a fixture scenario against a real facility.

    Args:
        session: An active async database session.
        scenario_id: The scenario to activate.
        facility_id: The facility whose real channels the scenario's steps
            resolve against.
        seed: RNG seed for scenarios with jitter -- same seed + same `now`
            always produces byte-identical generated readings.
        now: The wall-clock time step offsets are relative to (defaults to
            real UTC now).

    Returns:
        The number of readings inserted (one per scenario step).

    Raises:
        ScenarioActivationError: Unknown scenario_id, or the facility lacks
            a channel of a sensor type the scenario requires.
    """
    scenario = get_scenario(scenario_id)
    if scenario is None:
        raise ScenarioActivationError(f"Неизвестный сценарий: {scenario_id}")

    now = now or datetime.now(timezone.utc)
    rng = Random(seed)

    for i, step in enumerate(scenario.steps):
        channel_id = await _resolve_channel_id(session, facility_id, step.sensor_type_id)
        jitter = rng.uniform(-scenario.jitter_seconds, scenario.jitter_seconds) if scenario.jitter_seconds else 0.0
        occurred_at = now + timedelta(seconds=step.offset_seconds + jitter)
        session.add(
            SensorReading(
                channel_id=channel_id,
                occurred_at=occurred_at,
                is_alarm=step.is_alarm,
                raw_value=step.raw_value,
                numeric_value=step.numeric_value,
                is_anomaly=False,
                source_event_id=f"fixture_{scenario_id}_{facility_id}_{i}_{seed}",
                origin="fixture",
            )
        )

    await session.commit()
    return len(scenario.steps)
