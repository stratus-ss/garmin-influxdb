import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import tools
from mcp.server.fastmcp import FastMCP

MCP = FastMCP("garmin-influxdb-mcp")


@MCP.tool()
def list_metrics() -> str:
    """Returns all available measurement names stored in the Garmin InfluxDB. Use this to discover what fitness data can be queried."""
    return json.dumps(tools.list_metrics(), indent=2)


@MCP.tool()
def query_fitness_data(
    metric: str,
    range: str,
    aggregation: str,
    group_by: str | None = None,
    activity_type: list[str] | None = None,
) -> str:
    """Query aggregated fitness data from InfluxDB. Use activity_type to filter (e.g. ['running','walking']). Suitable for totals, averages, extremes over a period."""
    return json.dumps(tools.query_fitness_data(
        metric=metric,
        aggregation=aggregation,
        range=range,
        group_by=group_by,
        activity_type=activity_type,
    ), indent=2)


@MCP.tool()
def query_activities(
    range: str,
    fields: list[str] | None = None,
    limit: int = 10,
    activity_type: list[str] | None = None,
) -> str:
    """Query activities with optional type filter. Use activity_type=['running','walking'] to narrow results."""
    return json.dumps(tools.query_activities(
        range=range,
        fields=fields,
        limit=limit,
        activity_type=activity_type,
    ), indent=2)


@MCP.tool()
def delete_data(measurement: str, range: str) -> str:
    """Delete data points from a measurement within a time range. Use YYYY-MM-DD..YYYY-MM-DD for absolute ranges or InfluxDB relative like 4w."""
    return json.dumps(tools.delete_data(measurement=measurement, range=range), indent=2)


@MCP.tool()
def sync_garmin(start_date: str | None = None, end_date: str | None = None, delay_seconds: float = 4.0) -> str:
    """Sync Garmin Connect data to InfluxDB. Dates in YYYY-MM-DD format.
    Defaults: start = day after latest data in DB, end = today.
    delay_seconds sets the pause between each day (default 4s to avoid API rate limits).
    For bulk historical syncs, use 4s or higher."""
    return json.dumps(tools.sync_garmin(start_date=start_date, end_date=end_date, delay_seconds=delay_seconds), indent=2)


if __name__ == "__main__":
    MCP.run(transport="stdio")