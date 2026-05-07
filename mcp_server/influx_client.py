import os
import re
from datetime import date
from typing import Any, Optional

from influxdb import InfluxDBClient

_ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(Z?))?$")
_RELATIVE_RE = re.compile(r"^\d+[smhdw]$")
_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


_METRIC_UNITS = {
    "total_distance_meters": "meters",
    "total_steps": "steps",
    "total_burned_calories": "kcal",
    "distance": "meters",
    "duration": "seconds",
    "averageSpeed": "km/h",
    "maxSpeed": "km/h",
    "averageHR": "bpm",
    "maxHR": "bpm",
    "steps": "steps",
    "highly_active_minutes": "minutes",
    "moderately_active_minutes": "minutes",
    "sedentary_minutes": "minutes",
    "awake_minutes": "minutes",
    "light_sleep_minutes": "minutes",
    "deep_sleep_minutes": "minutes",
    "total_sleep_minutes": "minutes",
    "lowest_heart_rate": "bpm",
    "highest_heart_rate": "bpm",
    "resting_heart_rate": "bpm",
    "floors_ascended": "floors",
    "floors_descended": "floors",
    "avgStrideLength": "cm",
    "averageRunningCadenceInStepsPerMinute": "spm",
    "hrv_last_night_avg": "ms",
    "hrv_weekly_avg": "ms",
}


_DISPLAY_FORMATTERS = {
    "total_distance_meters": lambda raw: (
        f"{raw:,.0f} meters ({raw / 1609.34:.1f} miles)"
    ),
    "distance": lambda raw: f"{raw:,.0f} meters ({raw / 1609.34:.1f} miles)",
    "total_steps": lambda raw: f"{raw:,.0f} steps",
    "total_burned_calories": lambda raw: f"{raw:,.0f} kcal",
    "highly_active_minutes": lambda raw: f"{raw:,.0f} seconds ({raw / 3600:.1f} hours)",
    "moderately_active_minutes": lambda raw: (
        f"{raw:,.0f} seconds ({raw / 3600:.1f} hours)"
    ),
    "sedentary_minutes": lambda raw: f"{raw:,.0f} seconds ({raw / 3600:.1f} hours)",
    "awake_minutes": lambda raw: f"{raw:,.0f} seconds ({raw / 3600:.1f} hours)",
    "light_sleep_minutes": lambda raw: f"{raw:,.0f} seconds ({raw / 3600:.1f} hours)",
    "deep_sleep_minutes": lambda raw: f"{raw:,.0f} seconds ({raw / 3600:.1f} hours)",
    "total_sleep_minutes": lambda raw: f"{raw:,.0f} seconds ({raw / 3600:.1f} hours)",
    "averageSpeed": lambda raw: f"{raw:.2f} km/h ({raw * 0.621371:.1f} mph)",
    "maxSpeed": lambda raw: f"{raw:.2f} km/h ({raw * 0.621371:.1f} mph)",
    "avgStrideLength": lambda raw: f"{raw:.1f} cm ({raw / 100:.2f} m)",
    "averageRunningCadenceInStepsPerMinute": lambda raw: f"{raw:.0f} spm",
    "averageHR": lambda raw: f"{raw:.0f} bpm",
    "maxHR": lambda raw: f"{raw:.0f} bpm",
    "lowest_heart_rate": lambda raw: f"{raw:.0f} bpm",
    "highest_heart_rate": lambda raw: f"{raw:.0f} bpm",
    "resting_heart_rate": lambda raw: f"{raw:.0f} bpm",
    "floors_ascended": lambda raw: f"{raw:.0f} floors",
    "floors_descended": lambda raw: f"{raw:.0f} floors",
    "duration": lambda raw: f"{raw:,.0f} seconds ({raw / 3600:.1f} hours)",
}


# Conversions to human-readable units
def _display(metric: str, raw: float) -> str:
    """Format a metric value for human-readable display."""
    if raw is None:
        return "N/A"
    formatter = _DISPLAY_FORMATTERS.get(metric)
    if formatter:
        return formatter(raw)
    return f"{raw}"


class InfluxClient:
    def __init__(self):
        self._client = InfluxDBClient(
            host=os.getenv("INFLUX_HOST", "localhost"),
            port=int(os.getenv("INFLUX_PORT", "8086")),
            username=os.getenv("INFLUX_USER", ""),
            password=os.getenv("INFLUX_PASS", ""),
            database=os.getenv("INFLUX_DB", "garmin"),
        )

    def get_measurements(self) -> list[str]:
        result = self._client.query("SHOW MEASUREMENTS")
        return [m["name"] for m in result.get_points()]

    # ── shoe / gear metadata ──────────────────────────────────────────────

    def write_shoe_metadata(
        self,
        shoe_uuid: str,
        shoe_name: str,
        first_use_date: str,
        brand: str = "",
        model: str = "",
        retired: bool = False,
        max_distance_meters: Optional[float] = None,
    ) -> None:
        """Store shoe metadata as a point in the 'gear_metadata' measurement.

        The point timestamp is set to the first-use date so that the
        measurement naturally aligns with time-based queries.
        """
        fields: dict[str, Any] = {
            "shoe_name": shoe_name,
            "first_use_date": first_use_date,
        }
        if brand:
            fields["brand"] = brand
        if model:
            fields["model"] = model
        if retired:
            fields["retired"] = "true"
        if max_distance_meters is not None:
            fields["max_distance_meters"] = max_distance_meters

        tags = {"shoe_uuid": shoe_uuid}

        body = [
            {
                "measurement": "gear_metadata",
                "tags": tags,
                "time": f"{first_use_date}T00:00:00Z",
                "fields": fields,
            }
        ]
        self._client.write_points(body)

    def get_shoe_metadata(
        self, name_filter: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Return all stored shoe metadata, optionally filtered by shoe name."""
        where = ""
        if name_filter:
            where = f" WHERE \"shoe_name\" = '{name_filter}'"
        ql = f"SELECT last(shoe_name), last(first_use_date), last(brand), last(model), last(retired), last(max_distance_meters) FROM gear_metadata{where} GROUP BY shoe_uuid"
        results = self._client.query(ql)
        shoes = []
        for (_, tags), points in results.items():
            point_list = list(points)
            if not point_list:
                continue
            p = point_list[-1]
            shoes.append(
                {
                    "shoe_uuid": tags.get("shoe_uuid", "") if tags else "",
                    "shoe_name": p.get("last", ""),
                    "first_use_date": p.get("last_1", ""),
                    "brand": p.get("last_2", "") or "",
                    "model": p.get("last_3", "") or "",
                    "retired": p.get("last_4", "") == "true",
                    "max_distance_meters": p.get("last_5"),
                }
            )
        return shoes

    def get_latest_shoe_sync(self) -> date | None:
        """Return the most recent first_use_date stored in gear_metadata, or None."""
        ql = "SELECT last(first_use_date) FROM gear_metadata"
        points = list(self._client.query(ql).get_points())
        if not points or not points[0].get("time"):
            return None
        ts = points[0].get("time", "")
        if not ts:
            return None
        return date.fromisoformat(ts.replace("Z", "+00:00")[:10])

    def _build_time_clause(self, time_range: str) -> str:
        if ".." in time_range:
            start, end = time_range.split("..", 1)
            if not _ISO8601_RE.match(start) or not _ISO8601_RE.match(end):
                raise ValueError(f"Invalid date format in time range: {time_range!r}")
            return f"time >= '{start}' AND time <= '{end}'"
        if not _RELATIVE_RE.match(time_range):
            raise ValueError(f"Invalid relative time range: {time_range!r}")
        return f"time > now() - {time_range}"

    def delete_measurement_range(self, measurement: str, time_range: str) -> str:
        """Delete points from a measurement within a time range."""
        if not _NAME_RE.match(measurement):
            raise ValueError(f"Invalid measurement name: {measurement!r}")
        time_clause = self._build_time_clause(time_range)
        ql = f'DELETE FROM "{measurement}" WHERE {time_clause}'
        self._client.query(ql)
        return f"Deleted from {measurement} where {time_clause}"

    def get_latest_timestamp(self) -> date | None:
        """Return the date of the most recent total_steps entry, or None if empty."""
        ql = 'SELECT last(value) FROM "total_steps"'
        points = list(self._client.query(ql).get_points())
        if not points:
            return None
        # InfluxDB returns ISO8601 strings like "2026-04-12T00:00:00Z"
        ts = points[0].get("time", "")
        if not ts:
            return None
        dt = date.fromisoformat(ts.replace("Z", "+00:00")[:10])
        return dt

    def _build_type_clause(self, activity_type: Optional[list[str]] = None) -> str:
        if not activity_type:
            return ""
        for t in activity_type:
            if not _NAME_RE.match(t):
                raise ValueError(f"Invalid activity type: {t!r}")
        conditions = " OR ".join(f"\"activityType\" = '{t}'" for t in activity_type)
        return f" AND ({conditions})"

    def query_scalar(
        self,
        metric: str,
        aggregation: str,
        time_range: str,
        group_by: Optional[str] = None,
        activity_type: Optional[list[str]] = None,
    ) -> dict:
        time_clause = self._build_time_clause(time_range) + self._build_type_clause(
            activity_type
        )
        if group_by:
            ql = f'SELECT {aggregation}(value) AS result FROM "{metric}" WHERE {time_clause} GROUP BY time({group_by})'
            points = list(self._client.query(ql).get_points())
            values = [
                float(p["result"])
                for p in points
                if isinstance(p.get("result"), (int, float))
            ]
        else:
            ql = f'SELECT {aggregation}(value) AS result FROM "{metric}" WHERE {time_clause}'
            points = list(self._client.query(ql).get_points())
            values = [
                float(p["result"])
                for p in points
                if isinstance(p.get("result"), (int, float))
            ]

        if not values:
            return {
                "metric": metric,
                "aggregation": aggregation,
                "range": time_range,
                "result": None,
                "unit_hint": _METRIC_UNITS.get(metric, "unknown"),
            }

        if group_by:
            result = [
                {
                    "timestamp": p["time"],
                    "value": float(p["result"]),
                    "display": _display(metric, float(p["result"])),
                }
                for p in points
                if p.get("result") is not None
            ]
        else:
            scalar = values[0] if len(values) == 1 else values
            result = scalar

        if isinstance(result, (int, float)):
            display_val = float(result)
        elif isinstance(result, list) and result:
            first = result[0]
            display_val = (
                first.get("value") if isinstance(first, dict) else float(first)
            )
        else:
            display_val = None

        return {
            "metric": metric,
            "aggregation": aggregation,
            "range": time_range,
            "result": result,
            "display": _display(metric, display_val),
            "unit_hint": _METRIC_UNITS.get(metric, "unknown"),
        }

    def query_activities(
        self,
        time_range: str,
        fields: Optional[list[str]] = None,
        limit: int = 10,
        activity_type: Optional[list[str]] = None,
    ) -> list[dict]:
        if not fields:
            fields = [
                "distance",
                "duration",
                "averageSpeed",
                "maxSpeed",
                "averageHR",
                "maxHR",
                "steps",
            ]

        where = self._build_time_clause(time_range) + self._build_type_clause(
            activity_type
        )
        rows_by_time: dict[str, dict[str, Any]] = {}

        for field in fields:
            ql = f'SELECT value FROM "{field}" WHERE {where} GROUP BY "activityType"'
            result = self._client.query(ql)
            for (_, tags), points in result.items():
                act_type = tags.get("activityType", "unknown") if tags else "unknown"
                for p in points:
                    ts = p.get("time")
                    if not ts:
                        continue
                    key = f"{ts}_{act_type}"
                    if key not in rows_by_time:
                        rows_by_time[key] = {"time": ts, "activityType": act_type}
                    rows_by_time[key][field] = p.get("value")

        sorted_rows = sorted(
            rows_by_time.values(), key=lambda r: r["time"], reverse=True
        )
        return sorted_rows[:limit]
