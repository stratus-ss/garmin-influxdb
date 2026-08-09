# Garmin InfluxDB MCP Server

MCP server for Garmin fitness data. Exposes 8 tools via mcp 2.x `MCPServer` to query and sync data from InfluxDB and Garmin Connect.

## Moltis Configuration

Add this to your Moltis config:

```toml
[mcp.servers.garmin-fitness]
command = "docker"
args = ["exec", "-i", "garmin-influxdb-mcp", "python", "mcp_server/server.py"]
```

Or use the image directly without docker-compose:

```toml
[mcp.servers.garmin-fitness]
command = "docker"
args = [
  "run", "--rm", "-i",
  "--network", "host",
  "-e", "INFLUX_HOST=<host>",
  "-e", "INFLUX_PORT=8086",
  "-e", "INFLUX_USER=<user>",
  "-e", "INFLUX_DB=garmin",
  "-e", "GARMIN_USER=<garmin_user>",
  "-e", "GARMIN_PASS=<garmin_pass>",
  "quay.io/sovens/mcps/garmin-influxdb:0.6.1"
]
```

## Environment Variables

| Variable        | Required | Description                              |
|-----------------|----------|------------------------------------------|
| `INFLUX_HOST`   | Yes      | InfluxDB host                            |
| `INFLUX_PORT`   | No       | InfluxDB port (default 8086)             |
| `INFLUX_USER`   | Yes      | InfluxDB username                        |
| `INFLUX_PASS`   | Yes      | InfluxDB password                        |
| `INFLUX_DB`     | No       | Database name (default garmin)            |
| `GARMIN_USER`   | Yes      | Garmin Connect email                     |
| `GARMIN_PASS`   | Yes      | Garmin Connect password                  |

## Available Tools

| Tool                  | Description                                                                 |
|-----------------------|-----------------------------------------------------------------------------|
| `list_metrics`        | Discover available measurements in InfluxDB                                  |
| `query_fitness_data`  | Aggregate a metric over a time range (sum/mean/min/max/count/last)       |
| `query_activities`    | List recent activities with optional field selection and type filter        |
| `delete_data`         | Delete data from a measurement within a time range (use with caution)       |
| `add_shoe`            | Register a shoe with first-use date and optional max distance                |
| `list_shoes`          | List all registered shoes with metadata                                       |
| `query_shoe_distance` | Calculate total distance on a shoe since first use                          |
| `sync_garmin`         | Sync fitness data from Garmin Connect for a date range                      |

## Query Examples

**Total steps this week:**

```
query_fitness_data(metric="total_steps", aggregation="sum", range="1w")
```

**Total running + walking distance in a date range** (result in meters, divide by 1609.34 for miles):

```
query_fitness_data(metric="distance", aggregation="sum", range="2026-01-01..2026-03-31", activity_type=["running", "walking"])
```

**Recent activities:**

```
query_activities(range="2w", fields=["distance", "duration", "averageHR"], limit=10, activity_type=["running"])
```

**Sync new data from Garmin:**

```
sync_garmin()                          # syncs from day after latest data to today
sync_garmin(start_date="2026-04-01")   # sync a specific range
```

## Docker Compose Architecture

The container runs with `command: ["sleep", "infinity"]` rather than starting the server directly.

Moltis connects via `docker exec -i <container> python mcp_server/server.py`, which requires the container to already be **running**. The `sleep infinity` command keeps the container alive so the exec call can attach to it on demand. Without it, the container would exit immediately after startup and Moltis would fail with "No such container".

The server is invoked **on-demand** by Moltis -- it is not the container entrypoint.

## Skill Reference

For AI routing guidance (how the skill decides which tool to use for a given question), see `mcp_server/moltis/skill/SKILL.md`.
