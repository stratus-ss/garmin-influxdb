import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from garmin_to_influxdb import load_dotenv

load_dotenv()

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
    return json.dumps(
        tools.query_fitness_data(
            metric=metric,
            aggregation=aggregation,
            range=range,
            group_by=group_by,
            activity_type=activity_type,
        ),
        indent=2,
    )


@MCP.tool()
def query_activities(
    range: str,
    fields: list[str] | None = None,
    limit: int = 10,
    activity_type: list[str] | None = None,
) -> str:
    """Query activities with optional type filter. Use activity_type=['running','walking'] to narrow results."""
    return json.dumps(
        tools.query_activities(
            range=range,
            fields=fields,
            limit=limit,
            activity_type=activity_type,
        ),
        indent=2,
    )


@MCP.tool()
def delete_data(measurement: str, range: str) -> str:
    """Delete data points from a measurement within a time range. Use YYYY-MM-DD..YYYY-MM-DD for absolute ranges or InfluxDB relative like 4w."""
    return json.dumps(tools.delete_data(measurement=measurement, range=range), indent=2)


@MCP.tool()
def add_shoe(
    shoe_name: str,
    first_use_date: str,
    brand: str = "",
    model: str = "",
    max_distance_meters: float | None = None,
) -> str:
    """Register a shoe with its first-use date so you can track mileage on it.
    first_use_date must be YYYY-MM-DD.  max_distance_meters is optional (typical shoe life ~643,000 meters / 400 miles)."""
    return json.dumps(
        tools.add_shoe(
            shoe_name=shoe_name,
            first_use_date=first_use_date,
            brand=brand,
            model=model,
            max_distance_meters=max_distance_meters,
        ),
        indent=2,
    )


@MCP.tool()
def list_shoes() -> str:
    """List all registered shoes with their first-use dates and metadata."""
    return json.dumps(tools.list_shoes(), indent=2)


@MCP.tool()
def query_shoe_distance(
    shoe_name: str,
    activity_type: list[str] | None = None,
) -> str:
    """Calculate total distance accumulated on a shoe since its first use.
    Looks up the shoe's stored first-use date, then sums total_distance_meters from that date through today.
    Use activity_type to filter e.g. ['running','walking']."""
    return json.dumps(
        tools.query_shoe_distance(
            shoe_name=shoe_name,
            activity_type=activity_type,
        ),
        indent=2,
    )


@MCP.tool()
def sync_garmin(
    start_date: str | None = None,
    end_date: str | None = None,
    delay_seconds: float = 4.0,
) -> str:
    """Sync Garmin Connect data to InfluxDB. Dates in YYYY-MM-DD format.
    Defaults: start = day after latest data in DB, end = today.
    delay_seconds sets the pause between each day (default 4s to avoid API rate limits).
    For bulk historical syncs, use 4s or higher."""
    return json.dumps(
        tools.sync_garmin(
            start_date=start_date, end_date=end_date, delay_seconds=delay_seconds
        ),
        indent=2,
    )


if __name__ == "__main__":
    MCP.run(transport="stdio")
