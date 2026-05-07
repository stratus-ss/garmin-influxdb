# Garmin Connect to InfluxDB

Syncs Garmin Connect workout data and daily health metrics to InfluxDB for time-series analysis. Supports both one-shot and historical backfill sync modes, plus an optional MCP server for programmatic access.

![License](https://img.shields.io/github/license/stratus-ss/garmin-influxdb)
![Python](https://img.shields.io/github/pipenv/l/python-version/stratus-ss/garmin-influxdb?label=python%203.10%2B)
![InfluxDB](https://img.shields.io/badge/InfluxDB-1.x-blue)


## Quick Start

```bash
# 1. Clone
git clone https://github.com/stratus-ss/garmin-influxdb.git
cd garmin-influxdb

# 2. Install
pip install -r requirements.txt
pip install -r mcp_server/requirements.txt

# 3. Configure and run
cp .env.example .env
# edit .env with your GARMIN_USER, GARMIN_PASS, INFLUX_HOST, INFLUX_USER, INFLUX_PASS
python garmin_to_influxdb.py --start 2026-01-01
```

On first run, tokens are cached in `.garminconnect/` for re-use on subsequent runs.

## Features

- **Bidirectional sync:** activities + daily stats (steps, sleep, HRV, calories, heart rate, floors)
- **Historical backfill:** week-by-week orchestrator with crash recovery via `sync_state.json`
- **Speed calibration:** applies verified multiplier (3.584392177) to convert Garmin m/s to km/h
- **Activity tagging:** `activityType` tag on all activity records for sport-based filtering
- **Timezone correction:** +20000s offset applied to daily stat timestamps
- **MCP server:** optional FastMCP server for AI agent tool access to InfluxDB queries and sync
- **Shoe tracking:** register shoes with first-use dates, query cumulative distance to determine replacement timing

## Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE](ARCHITECTURE.md) | High-level module map and design decisions |
| [CODEFLOW](CODEFLOW.md) | Runtime data flow with Mermaid diagrams |
| [AGENTS](AGENTS.md) | AI agent working context |

## Scripts

### `garmin_to_influxdb.py`

One-shot sync for a fixed date range. Edit `start_date` / `end_date` in the script, or override via CLI:

```bash
python garmin_to_influxdb.py                           # hardcoded dates in script
python garmin_to_influxdb.py --start 2026-01-01        # override start
python garmin_to_influxdb.py --start 2026-01-01 --end 2026-03-31  # override both
```

### `sync_historical.py`

Week-by-week orchestrator for backfilling historical data. Handles crashes via `sync_state.json`:

```bash
python sync_historical.py                    # resume from last saved state
python sync_historical.py --dry-run          # print chunk plan without syncing
python sync_historical.py --start 2019-04-11 --end 2021-12-31
python sync_historical.py --delay 4 --batch-delay 300
```

**CLI flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--start` | 2019-04-11 | Override sync start date (YYYY-MM-DD) |
| `--end` | today | Override sync end date |
| `--delay` | 4 | Seconds to wait between each day |
| `--batch-delay` | 300 | Seconds to wait between weekly chunks |
| `--dry-run` | false | Print chunk plan without calling Garmin API |
| `--force` | false | Re-sync all chunks, ignoring completed state |

Completed weeks are tracked in `sync_state.json` and skipped on subsequent runs. To re-sync a week, edit or delete its entry.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GARMIN_USER` | (empty) | Garmin Connect email |
| `GARMIN_PASS` | (empty) | Garmin Connect password |
| `INFLUX_HOST` | localhost | InfluxDB host |
| `INFLUX_PORT` | 8086 | InfluxDB port |
| `INFLUX_USER` | (empty) | InfluxDB username |
| `INFLUX_PASS` | (empty) | InfluxDB password |
| `INFLUX_DB` | garmin | InfluxDB database name |

## Data Model

**Activities** are written with an `activityType` tag (e.g. `running`, `cycling`, `swimming`) so you can filter by sport type in InfluxDB queries.

**Speed fields** (`averageSpeed`, `maxSpeed`) are multiplied by **3.584392177** to convert Garmin's internal m/s to km/h. Do not change this multiplier without Garmin app verification.

**Timezone:** daily stat timestamps have +20000 seconds added to correct a timezone offset. Without this, activities appear on the previous day in InfluxDB.

**HRV data:** not available on all devices. When unsupported, the sync logs an error but continues without failing the day.

**Sync behavior:** activities are fetched as a single request for the entire range, while per-day stats are fetched individually per day. A failure in one day's per-day data does not affect the activity fetch.

## Shoe / Gear Tracking

The MCP server supports tracking running shoe mileage to help determine when to replace them.

**Register a shoe:**
```
add_shoe(shoe_name="Brooks Ghost 15", first_use_date="2025-03-01", max_distance_meters=643738)
```
`max_distance_meters` is optional (typical shoe life ~643,000m / 400 miles).

**Check mileage:**
```
query_shoe_distance(shoe_name="Brooks Ghost 15")
```
Returns total distance accumulated since the shoe's first use, plus the replacement threshold if set. Filter by activity type with `activity_type=["running"]`.

**List all shoes:**
```
list_shoes()
```

Shoe metadata is stored in the `gear_metadata` measurement in InfluxDB. The first-use date is used as the point timestamp so it aligns naturally with time-based queries.

## MCP Server

The optional MCP server in `mcp_server/` exposes eight tools: `list_metrics`, `query_fitness_data`, `query_activities`, `delete_data`, `sync_garmin`, `add_shoe`, `list_shoes`, and `query_shoe_distance`. It is not required for either script above -- both work standalone. Run it with:

```bash
python mcp_server/server.py
```

## License

[AGPL-3.0](LICENSE)
