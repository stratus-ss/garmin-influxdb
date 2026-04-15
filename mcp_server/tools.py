from typing import Any
import os
from datetime import date, timedelta
from influx_client import InfluxClient
from garmin_to_influxdb import sync_range

_db: InfluxClient | None = None


def _db_client() -> InfluxClient:
    global _db
    if _db is None:
        _db = InfluxClient()
    return _db


def list_metrics() -> list[dict[str, Any]]:
    measurements = _db_client().get_measurements()
    return [{"name": m, "description": f"Garmin measurement: {m}"} for m in sorted(measurements)]


def query_fitness_data(
    metric: str,
    aggregation: str,
    range: str,
    group_by: str | None = None,
    activity_type: list[str] | None = None,
) -> dict[str, Any]:
    return _db_client().query_scalar(
        metric=metric,
        aggregation=aggregation,
        time_range=range,
        group_by=group_by,
        activity_type=activity_type,
    )


def query_activities(
    range: str,
    fields: list[str] | None = None,
    limit: int = 10,
    activity_type: list[str] | None = None,
) -> list[dict[str, Any]]:
    return _db_client().query_activities(
        time_range=range,
        fields=fields,
        limit=limit,
        activity_type=activity_type,
    )


def delete_data(measurement: str, range: str) -> dict[str, Any]:
    result = _db_client().delete_measurement_range(measurement, range)
    return {"status": "ok", "detail": result}


def sync_garmin(start_date: str | None = None, end_date: str | None = None, delay_seconds: float = 4.0) -> dict[str, Any]:
    from garmin_to_influxdb import connect_to_garmin

    latest = _db_client().get_latest_timestamp()
    if start_date:
        start = date.fromisoformat(start_date)
    elif latest:
        start = latest + timedelta(days=1)
    else:
        start = date.today() - timedelta(days=30)

    if end_date:
        end = date.fromisoformat(end_date)
    else:
        end = date.today()

    client = connect_to_garmin(
        username=os.getenv("GARMIN_USER", ""),
        password=os.getenv("GARMIN_PASS", ""),
    )
    if client is None:
        return {"status": "error", "detail": "Garmin login failed"}
    return sync_range(client, _db_client()._client, start, end, delay_seconds=delay_seconds)