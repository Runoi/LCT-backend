"""Pure, DB-free parsing of one event-log row (no I/O, no imports of models).

Handles the two real-world quirks confirmed against the actual dataset
(see `BACKEND_REQUIREMENTS.md` section 12.4 and
`QA_ORGANIZERS_CLARIFICATIONS.md` section 4):

- the boolean "тревожное" column is `true/false` in some files and
  `t/f` in others;
- "значение_датчика" sometimes holds a vendor sentinel (the Unix-epoch
  default `01.01.1970 ...`, or an out-of-range numeric code) instead of
  a real reading -- these must be flagged as anomalies, never treated
  as valid data.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_MSK = timezone(timedelta(hours=3))

_BOOLEAN_MAP = {"true": True, "false": False, "t": True, "f": False}

# Vendor-specific sentinel codes seen in the real dataset for numeric
# channels (QA_ORGANIZERS_CLARIFICATIONS.md section 4): out-of-range
# placeholder values, not real readings.
_NUMERIC_SENTINEL_VALUES = {-100.0, 255.0, -3276.0, -127.0}


class EventParseError(ValueError):
    """Raised when a row cannot be parsed at all (malformed, not just anomalous)."""


@dataclass(frozen=True)
class ParsedReading:
    """One normalized event-log row, ready to persist as a SensorReading."""

    channel_id: str
    occurred_at: datetime
    is_alarm: bool
    raw_value: str
    numeric_value: float | None
    is_anomaly: bool
    source_event_id: str


def parse_boolean(raw: str) -> bool:
    """Parse either boolean encoding used across the dataset's files.

    Args:
        raw: The raw "тревожное" column value ("true"/"false"/"t"/"f",
            any casing).

    Returns:
        The boolean value.

    Raises:
        EventParseError: If the value matches neither encoding.
    """
    normalized = raw.strip().lower()
    if normalized not in _BOOLEAN_MAP:
        raise EventParseError(f"unrecognized boolean encoding: {raw!r}")
    return _BOOLEAN_MAP[normalized]


def is_sentinel_value(raw_value: str) -> bool:
    """Check for the Unix-epoch-default sentinel, regardless of sensor type.

    Args:
        raw_value: The raw "значение_датчика" column value.

    Returns:
        True if this looks like the `01.01.1970 ...` default-clock artifact.
    """
    return raw_value.strip().startswith("01.01.1970")


def parse_event_row(row: dict[str, str], value_type: str) -> ParsedReading:
    """Normalize one event-log row into a ParsedReading.

    Args:
        row: A dict with keys ид_события, ид_канала_данных, дата, время,
            тревожное, значение_датчика (exactly as csv.DictReader yields,
            regardless of whether the source file quoted its header).
        value_type: "numeric", "categorical", or "unknown" (from the
            channel's sensor_type_id via reference_data.SENSOR_TYPES) --
            determines whether a numeric parse is attempted at all.

    Returns:
        The normalized ParsedReading. Sentinel/unparseable numeric values
        are flagged via is_anomaly=True with numeric_value=None; they are
        never silently coerced into a plausible-looking number.
    """
    raw_value = row["значение_датчика"]
    occurred_at = datetime.strptime(f"{row['дата']} {row['время']}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=_MSK)
    is_alarm = parse_boolean(row["тревожное"])

    numeric_value: float | None = None
    is_anomaly = False

    if is_sentinel_value(raw_value):
        is_anomaly = True
    elif value_type == "numeric":
        try:
            parsed = float(raw_value)
        except ValueError:
            is_anomaly = True
        else:
            if parsed in _NUMERIC_SENTINEL_VALUES:
                is_anomaly = True
            else:
                numeric_value = parsed

    return ParsedReading(
        channel_id=row["ид_канала_данных"],
        occurred_at=occurred_at,
        is_alarm=is_alarm,
        raw_value=raw_value,
        numeric_value=numeric_value,
        is_anomaly=is_anomaly,
        source_event_id=row["ид_события"],
    )
