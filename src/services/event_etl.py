"""Stream the real operational-window event log into SensorReading.

Uses `event_parser.parse_event_row` as its only parsing logic (see
`docs/adr/0003-etl-produces-timeseries-not-ml-features.md`: this ETL
produces raw timeseries, not ML features). Streams the CSV row by row
via `csv.DictReader` -- never materializes the file as a Python list --
and commits in batches to keep memory bounded regardless of file size.
"""
import csv
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.sensor import EtlIngestedSource, SensorChannel, SensorReading
from src.services.event_parser import parse_event_row
from src.services.reference_data import SENSOR_TYPES

DEFAULT_CSV_PATH = Path("data") / "журнал_событий_пример.csv"
_BATCH_SIZE = 2000

_VALUE_TYPE_BY_SENSOR_TYPE_ID = {t.id: t.value_type for t in SENSOR_TYPES}


def _csv_path() -> Path:
    override = os.environ.get("EVENT_LOG_CSV_PATH")
    return Path(override) if override else DEFAULT_CSV_PATH


def _value_type_for(sensor_type_id: str) -> str:
    # "unknown" (orphaned/unrecognized channels) is treated as categorical:
    # we cannot safely assume a numeric channel without a real classification.
    return _VALUE_TYPE_BY_SENSOR_TYPE_ID.get(sensor_type_id, "categorical")


async def ingest_event_log(session: AsyncSession, csv_path: Path | None = None) -> int:
    """Stream-ingest the operational-window event log, idempotently.

    Args:
        session: An active async database session.
        csv_path: Optional override path (defaults to the bundled
            `data/журнал_событий_пример.csv` or EVENT_LOG_CSV_PATH).

    Returns:
        The number of rows ingested (0 if this exact source was already
        fully ingested).
    """
    path = csv_path or _csv_path()
    source_key = str(path)

    already_ingested = (
        await session.execute(select(EtlIngestedSource).where(EtlIngestedSource.source_path == source_key))
    ).scalar_one_or_none()
    if already_ingested is not None:
        return 0

    channel_types: dict[str, str] = dict(
        (await session.execute(select(SensorChannel.channel_id, SensorChannel.sensor_type_id))).all()
    )
    orphans_created: set[str] = set()
    row_count = 0
    batch: list[SensorReading] = []

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)  # a streaming iterator, not a list
        for row in reader:
            channel_id = row["ид_канала_данных"]
            if channel_id not in channel_types and channel_id not in orphans_created:
                session.add(
                    SensorChannel(
                        id=f"sensor_{channel_id}",
                        channel_id=channel_id,
                        tag="",
                        sensor_type_id="unknown",
                        system_type="unknown",
                        display_name=f"Неизвестный канал {channel_id}",
                        facility_id=None,
                        hierarchy_node_id=None,
                    )
                )
                orphans_created.add(channel_id)
                channel_types[channel_id] = "unknown"

            value_type = _value_type_for(channel_types[channel_id])
            reading = parse_event_row(row, value_type=value_type)
            batch.append(
                SensorReading(
                    channel_id=reading.channel_id,
                    occurred_at=reading.occurred_at,
                    is_alarm=reading.is_alarm,
                    raw_value=reading.raw_value,
                    numeric_value=reading.numeric_value,
                    is_anomaly=reading.is_anomaly,
                    source_event_id=reading.source_event_id,
                )
            )
            row_count += 1

            if len(batch) >= _BATCH_SIZE:
                session.add_all(batch)
                await session.commit()
                batch = []

    if batch:
        session.add_all(batch)
        await session.commit()

    session.add(EtlIngestedSource(source_path=source_key, row_count=row_count))
    await session.commit()
    return row_count
