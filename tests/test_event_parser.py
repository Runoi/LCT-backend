"""Tests for the pure event-log row parser (no database required)."""
import csv
from pathlib import Path

import pytest

from src.services.event_parser import EventParseError, is_sentinel_value, parse_boolean, parse_event_row

FIXTURE_QUOTED = Path(__file__).parent / "fixtures" / "event_log_variants.csv"
FIXTURE_TF_UNQUOTED = Path(__file__).parent / "fixtures" / "event_log_variants_tf_unquoted.csv"


def _read_rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize(("raw", "expected"), [("true", True), ("false", False), ("t", True), ("f", False),
                                                ("TRUE", True), ("F", False)])
def test_parse_boolean_handles_both_encodings(raw: str, expected: bool) -> None:
    assert parse_boolean(raw) is expected


def test_parse_boolean_rejects_unknown_value() -> None:
    with pytest.raises(EventParseError):
        parse_boolean("maybe")


def test_is_sentinel_value_detects_epoch_default() -> None:
    assert is_sentinel_value("01.01.1970 03:00:00") is True
    assert is_sentinel_value("28") is False
    assert is_sentinel_value("Норма") is False


def test_quoted_header_true_false_rows_parse() -> None:
    rows = _read_rows(FIXTURE_QUOTED)
    normal = parse_event_row(rows[0], value_type="numeric")
    assert normal.numeric_value == 28.0
    assert normal.is_anomaly is False
    assert normal.is_alarm is False

    alarm = parse_event_row(rows[1], value_type="numeric")
    assert alarm.is_alarm is True


def test_unquoted_header_t_f_rows_parse() -> None:
    rows = _read_rows(FIXTURE_TF_UNQUOTED)
    off = parse_event_row(rows[0], value_type="numeric")
    assert off.is_alarm is False
    assert off.numeric_value == 28.0

    on = parse_event_row(rows[1], value_type="numeric")
    assert on.is_alarm is True
    assert on.numeric_value == 29.0


def test_epoch_sentinel_is_anomaly_regardless_of_value_type() -> None:
    rows = _read_rows(FIXTURE_QUOTED)
    sentinel_row = next(r for r in rows if r["ид_события"] == "9000003")

    as_numeric = parse_event_row(sentinel_row, value_type="numeric")
    assert as_numeric.is_anomaly is True
    assert as_numeric.numeric_value is None

    as_categorical = parse_event_row(sentinel_row, value_type="categorical")
    assert as_categorical.is_anomaly is True


def test_vendor_numeric_sentinel_code_is_anomaly() -> None:
    rows = _read_rows(FIXTURE_QUOTED)
    row = next(r for r in rows if r["ид_события"] == "9000004")
    reading = parse_event_row(row, value_type="numeric")
    assert reading.is_anomaly is True
    assert reading.numeric_value is None


def test_non_numeric_value_for_numeric_type_is_anomaly() -> None:
    rows = _read_rows(FIXTURE_QUOTED)
    row = next(r for r in rows if r["ид_события"] == "9000005")  # "Снято с охраны" is not a number
    reading = parse_event_row(row, value_type="numeric")
    assert reading.is_anomaly is True
    assert reading.numeric_value is None


def test_categorical_value_is_never_anomaly_just_because_its_text() -> None:
    rows = _read_rows(FIXTURE_QUOTED)
    row = next(r for r in rows if r["ид_события"] == "9000005")
    reading = parse_event_row(row, value_type="categorical")
    assert reading.is_anomaly is False
    assert reading.raw_value == "Снято с охраны"
