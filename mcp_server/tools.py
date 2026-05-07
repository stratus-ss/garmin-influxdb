import os
from datetime import date, timedelta
from typing import Any

from influx_client import InfluxClient

from garmin_to_influxdb import DEFAULT_SYNC_DELAY_SECONDS, sync_range

_db: InfluxClient | None = None


def _db_client() -> InfluxClient:
    global _db
    if _db is None:
        _db = InfluxClient()
    return _db


def list_metrics() -> list[dict[str, Any]]:
    measurements = _db_client().get_measurements()
    return [
        {"name": m, "description": f"Garmin measurement: {m}"}
        for m in sorted(measurements)
    ]


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


# ── shoe / gear tracking ──────────────────────────────────────────────


def add_shoe(
    shoe_name: str,
    first_use_date: str,
    brand: str = "",
    model: str = "",
    max_distance_meters: float | None = None,
) -> dict[str, Any]:
    """Register a shoe with its first-use date. Dates in YYYY-MM-DD format."""
    import uuid as _uuid

    shoe_uuid = str(_uuid.uuid4())[:8]
    _db_client().write_shoe_metadata(
        shoe_uuid=shoe_uuid,
        shoe_name=shoe_name,
        first_use_date=first_use_date,
        brand=brand,
        model=model,
        max_distance_meters=max_distance_meters,
    )
    return {
        "status": "ok",
        "shoe_uuid": shoe_uuid,
        "shoe_name": shoe_name,
        "first_use_date": first_use_date,
    }


def list_shoes() -> list[dict[str, Any]]:
    """Return all registered shoes with their first-use dates."""
    return _db_client().get_shoe_metadata()


def query_shoe_distance(
    shoe_name: str,
    activity_type: list[str] | None = None,
) -> dict[str, Any]:
    """Calculate total distance accumulated on a shoe since its first use.

    Looks up the shoe's stored first-use date, then queries the sum of
    total_distance_meters from that date through today.
    """
    shoes = _db_client().get_shoe_metadata(name_filter=shoe_name)
    if not shoes:
        return {"status": "error", "detail": f"No shoe found with name '{shoe_name}'"}

    shoe = shoes[0]
    first_use = shoe.get("first_use_date", "")
    if not first_use:
        return {
            "status": "error",
            "detail": f"Shoe '{shoe_name}' has no first-use date stored",
        }

    today = date.today().isoformat()
    time_range = f"{first_use}..{today}"

    result = _db_client().query_scalar(
        metric="total_distance_meters",
        aggregation="sum",
        time_range=time_range,
        activity_type=activity_type,
    )
    result["shoe_name"] = shoe_name
    result["first_use_date"] = first_use
    result["shoe_uuid"] = shoe.get("shoe_uuid", "")
    result["max_distance_meters"] = shoe.get("max_distance_meters")
    return result


def sync_garmin(
    start_date: str | None = None,
    end_date: str | None = None,
    delay_seconds: float = DEFAULT_SYNC_DELAY_SECONDS,
) -> dict[str, Any]:
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
    return sync_range(
        client, _db_client()._client, start, end, delay_seconds=delay_seconds
    )
