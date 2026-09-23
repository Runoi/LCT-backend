"""Static reference/config data: the single source of truth for every
enum, threshold, and boundary the frontend must not hardcode.

Sensor types and engineering-system groupings are taken from the real
sensor-channel catalogue (`справочник_каналов_датчиков.csv`, 19 sensor
types across 6 engineering systems). Everything else (risk levels,
freshness boundaries, SLA params) is this service's own MVP baseline,
documented here rather than duplicated inline at the call site.
"""
from src.schemas.reference import (
    DecisionStatus,
    FreshnessBoundary,
    ReferenceConfig,
    RejectReason,
    RiskLevelThreshold,
    RiskType,
    SensorType,
    SlaParam,
    UnitOfMeasure,
    WorkOrderStatus,
    WorkType,
)

SENSOR_STATES: list[str] = [
    "normal",
    "warning",
    "alarm",
    "fault",
    "offline",
    "maintenance",
    "disabled",
    "unknown",
]

SENSOR_TYPES: list[SensorType] = [
    SensorType(id="smoke_detector", display_name="Датчик дыма", system_type="fire_protection", value_type="categorical"),
    SensorType(id="phase_state", display_name="Состояние фазы", system_type="dispatch_control", value_type="categorical"),
    SensorType(id="door_contact", display_name="КД Дверь", system_type="security", value_type="categorical"),
    SensorType(id="motion_detector", display_name="Датчик движения", system_type="security", value_type="categorical"),
    SensorType(id="switch_state", display_name="Переключатель", system_type="dispatch_control", value_type="categorical"),
    SensorType(id="uir_r_state", display_name="Состояние УИР-Р", system_type="dispatch_control", value_type="categorical"),
    SensorType(id="temperature_sensor", display_name="Датчик температуры", system_type="temperature", value_type="numeric"),
    SensorType(id="gas_sensor", display_name="Газовый датчик", system_type="gas_protection", value_type="numeric"),
    SensorType(id="heat_detector", display_name="Тепловой датчик", system_type="fire_protection", value_type="categorical"),
    SensorType(id="av_contact", display_name="КД АВ", system_type="security", value_type="categorical"),
    SensorType(id="fan_state", display_name="Состояние вентилятора", system_type="dispatch_control", value_type="categorical"),
    SensorType(id="pump_state", display_name="Состояние насоса", system_type="dispatch_control", value_type="categorical"),
    SensorType(id="manual_call_point", display_name="Ручной извещатель", system_type="fire_protection", value_type="categorical"),
    SensorType(id="ups_state", display_name="ИБП", system_type="dispatch_control", value_type="categorical"),
    SensorType(id="hatch_contact", display_name="КД Люк", system_type="security", value_type="categorical"),
    SensorType(id="security_state", display_name="Состояние охраны", system_type="security", value_type="categorical"),
    SensorType(id="glass_break_sensor", display_name="Стекло", system_type="security", value_type="categorical"),
    SensorType(id="flood_sensor", display_name="Датчик затопления", system_type="diagnostic", value_type="categorical"),
    SensorType(id="hatch_9section", display_name="9-секционный люк", system_type="security", value_type="categorical"),
]

UNITS: list[UnitOfMeasure] = [
    UnitOfMeasure(id="celsius", display_name="Градус Цельсия", symbol="°C"),
    UnitOfMeasure(id="ppm", display_name="Частей на миллион", symbol="ppm"),
]

RISK_TYPES: list[RiskType] = [
    RiskType(id="sensor_failure", display_name="Отказ датчика/оборудования"),
    RiskType(id="fire", display_name="Пожар"),
    RiskType(id="flooding", display_name="Подтопление"),
    RiskType(id="unauthorized_access", display_name="Несанкционированный доступ"),
]

RISK_LEVELS: list[RiskLevelThreshold] = [
    RiskLevelThreshold(id="low", display_name="Низкий", min_probability=0.0, max_probability=0.3),
    RiskLevelThreshold(id="medium", display_name="Средний", min_probability=0.3, max_probability=0.6),
    RiskLevelThreshold(id="high", display_name="Высокий", min_probability=0.6, max_probability=0.85),
    RiskLevelThreshold(id="critical", display_name="Критический", min_probability=0.85, max_probability=1.0),
]

REJECT_REASONS: list[RejectReason] = [
    RejectReason(id="false_alarm", display_name="Ложное срабатывание", requires_comment=False),
    RejectReason(id="already_resolved", display_name="Уже устранено", requires_comment=False),
    RejectReason(id="duplicate", display_name="Дубликат", requires_comment=False),
    RejectReason(id="monitoring", display_name="Наблюдение", requires_comment=False),
    RejectReason(id="other", display_name="Другое", requires_comment=True),
]

WORK_TYPES: list[WorkType] = [
    WorkType(id="inspection", display_name="Осмотр"),
    WorkType(id="repair", display_name="Ремонт"),
    WorkType(id="replacement", display_name="Замена оборудования"),
    WorkType(id="maintenance", display_name="Плановое обслуживание"),
]

WORK_ORDER_STATUSES: list[WorkOrderStatus] = [
    WorkOrderStatus(id="draft", display_name="Черновик"),
    WorkOrderStatus(id="ready", display_name="Готово к назначению"),
    WorkOrderStatus(id="assigned", display_name="Назначено"),
    WorkOrderStatus(id="in_progress", display_name="В работе"),
    WorkOrderStatus(id="completed", display_name="Завершено"),
    WorkOrderStatus(id="cancelled", display_name="Отменено"),
    WorkOrderStatus(id="integration_error", display_name="Ошибка интеграции"),
]

DECISION_STATUSES: list[DecisionStatus] = [
    DecisionStatus(id="open", display_name="Открыт"),
    DecisionStatus(id="acknowledged", display_name="Подтверждён"),
    DecisionStatus(id="rejected", display_name="Отклонён"),
    DecisionStatus(id="deferred", display_name="Отложен"),
]

SLA_PARAMS: list[SlaParam] = [
    SlaParam(risk_level="low", response_minutes=24 * 60),
    SlaParam(risk_level="medium", response_minutes=4 * 60),
    SlaParam(risk_level="high", response_minutes=60),
    SlaParam(risk_level="critical", response_minutes=15),
]

FRESHNESS_BOUNDARIES: list[FreshnessBoundary] = [
    FreshnessBoundary(id="fresh", display_name="Актуально", max_age_seconds=5 * 60),
    FreshnessBoundary(id="delayed", display_name="Задержка", max_age_seconds=15 * 60),
    FreshnessBoundary(id="stale", display_name="Устарело", max_age_seconds=60 * 60),
    FreshnessBoundary(id="unavailable", display_name="Недоступно", max_age_seconds=None),
]


def get_reference_config() -> ReferenceConfig:
    """Build the complete reference/config bundle.

    Returns:
        A ReferenceConfig covering every enum/threshold the API contract
        requires the backend (not the frontend) to own.
    """
    return ReferenceConfig(
        sensor_states=SENSOR_STATES,
        sensor_types=SENSOR_TYPES,
        units=UNITS,
        risk_types=RISK_TYPES,
        risk_levels=RISK_LEVELS,
        reject_reasons=REJECT_REASONS,
        work_types=WORK_TYPES,
        work_order_statuses=WORK_ORDER_STATUSES,
        decision_statuses=DECISION_STATUSES,
        sla_params=SLA_PARAMS,
        freshness_boundaries=FRESHNESS_BOUNDARIES,
    )
