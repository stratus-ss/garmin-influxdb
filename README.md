# Garmin Connect to InfluxDB

This script stands on the giants of the [GarminConnect PyPi](https://pypi.org/project/garminconnect/) as well as the [InfluxDB PyPi](https://influxdb-python.readthedocs.io/en/latest/include-readme.html). 

## Prerequisites

- Python 3.10+
- InfluxDB 1.x instance
- Garmin Connect account

## Setup

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Environment variables:

| Variable       | Default   | Description                              |
|---------------|-----------|------------------------------------------|
| `GARMIN_USER`  | (empty)   | Garmin Connect email                    |
| `GARMIN_PASS`  | (empty)   | Garmin Connect password                  |
| `INFLUX_HOST`  | localhost | InfluxDB host                            |
| `INFLUX_PORT`  | 8086      | InfluxDB port                            |
| `INFLUX_USER`  | (empty)   | InfluxDB username                        |
| `INFLUX_PASS`  | (empty)   | InfluxDB password                        |
| `INFLUX_DB`    | garmin    | InfluxDB database name                   |

Token cache: on first login the script stores auth tokens in `.garminconnect/` so subsequent runs do not need credentials.

## Scripts

### `garmin_to_influxdb.py`

One-shot sync for a fixed date range. Edit the `start_date` / `end_date` variables at the top of the file, or override them via CLI:

```bash
python garmin_to_influxdb.py                           # use hardcoded dates in script
python garmin_to_influxdb.py --start 2026-01-01        # override start
python garmin_to_influxdb.py --start 2026-01-01 --end 2026-03-31  # override both
```

Data written per day:
- Daily stats: steps, distance, calories, active minutes, floors, heart rate
- Sleep: deep, light, awake minutes
- HRV (if supported by your device)
- Intra-day step timestamps
- Activities with `activityType` tag (running, cycling, swimming, etc.)

### `sync_historical.py`

Week-by-week orchestrator for backfilling historical data. Handles crashes gracefully via `sync_state.json`.

```bash
# Resume from last saved state (default start: 2019-04-11)
python sync_historical.py

# Dry run -- shows weeks without syncing
python sync_historical.py --dry-run

# Custom range
python sync_historical.py --start 2019-04-11 --end 2021-12-31

# Tune delays (seconds between each day, seconds between weeks)
python sync_historical.py --delay 4 --batch-delay 300
```

CLI flags:

| Flag            | Default | Description                                      |
|----------------|---------|--------------------------------------------------|
| `--start`      | 2019-04-11 | Override sync start date (YYYY-MM-DD)        |
| `--end`        | today   | Override sync end date                           |
| `--delay`       | 4       | Seconds to wait between each day                 |
| `--batch-delay` | 300    | Seconds to wait between weekly chunks            |
| `--dry-run`     | false   | Print chunk plan without calling Garmin API      |
| `--force`       | false   | Re-sync all chunks, ignoring completed state     |

Completed weeks are tracked in `sync_state.json` and skipped on subsequent runs. To re-sync a week, edit or delete its entry in that file.

## Data Model

Activities are written with an `activityType` tag (e.g. `running`, `cycling`, `swimming`) so you can filter by sport type in InfluxDB queries.

Speed fields (`averageSpeed`, `maxSpeed`) are multiplied by 3.584392177 to convert Garmin's internal unit (m/s) to km/h.

**GMT offset:** daily stat timestamps have 20000 seconds added to them to correct for a timezone offset. Without this correction, activities would appear on the previous day in InfluxDB.

**HRV data:** heart rate variability data is not available on all devices. When a device doesn't support it, the sync will log an error but continue without failing the day. It is not enabled by default.

**Sync behavior:** activities are fetched as a single request for the entire date range, while per-day stats (steps, sleep, heart rate, etc.) are fetched individually for each day. This means a failure in one day's per-day data does not affect the activity fetch.

## MCP Server

An optional MCP server lives in `mcp_server/`. It is not required for either script above -- both work standalone.