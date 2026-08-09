# garmin-influxdb

<!-- Purpose: Briefing document for AI coding agents.
     Keep under 150 lines. Cover what an agent needs to be productive.
     Ref: AGENTS.md standard (agentsmd.online), wimpysworld conventions. -->

## Project Overview

Syncs Garmin Connect workout data to InfluxDB for time-series analysis. Supports both live ingestion and historical backfill via CLI scripts, plus an MCP server for programmatic access.

- **Language:** Python 3.12+ (garminconnect 0.3.x requires Python 3.12+)
- **Framework:** MCP (Model Context Protocol) for server; stdlib argparse for scripts
- **Package manager:** pip + requirements.txt (no pyproject.toml)
- **Key dependencies:** garminconnect, influxdb, mcp, garth, python-dotenv
- **Container image:** `quay.io/sovens/mcps/garmin-influxdb:0.6.1` (mcp 2.x `MCPServer`)

## Commands

```bash
# Install dependencies
pip install -r requirements.txt
pip install -r mcp_server/requirements.txt

# Run live sync (ingest recent activities)
python garmin_to_influxdb.py

# Run historical backfill
python sync_historical.py

# Run MCP server (for AI agent tool access)
python mcp_server/server.py

# With Docker (InfluxDB + MCP server)
docker-compose up -d
```

## Code Style

- Formatter: black (line length 100)
- Type hints optional but appreciated on public functions
- Imports: stdlib, third-party, local (separated by blank lines)
- Functions over classes in core scripts; classes OK in mcp_server/
- stdlib logging only (no external logging libs)
- Max function length: 80 lines
- No hardcoded secrets -- use .env or environment variables

## File Structure

```
garmin-influxdb/
  .env                         # Credentials (never commit)
  .env.example                 # Template without credentials
  .garminconnect/              # Token cache (auto-created)
  garmin_to_influxdb.py        # Live sync entry point
  sync_historical.py           # Historical backfill entry point
  test_e2e.py                  # Ad-hoc integration test (needs Docker + real InfluxDB)
  requirements.txt             # Root dependencies
  docker-compose.yaml          # InfluxDB + MCP server container
  mcp_server/
    server.py                  # MCP server entry point
    influx_client.py           # InfluxDB client wrapper
    tools.py                   # MCP tool definitions
    requirements.txt            # MCP server dependencies
    Dockerfile                 # Container build for MCP server
    garmin_sync.py             # (dead code -- do not reference as active)
```

## Configuration

- Config loaded from `.env` at runtime
- Env vars: GARMIN_USER, GARMIN_PASS, INFLUX_HOST, INFLUX_PORT, INFLUX_USER, INFLUX_PASS, INFLUX_DB
- Optional: START_DATE, END_DATE for date-range ingestion
- Token cache stored in `.garminconnect/` (auto-created on first login)

## Do Not

- Do not commit `.env` or any file with actual credentials
- Do not modify garmin_sync.py -- it is dead code with no tests
- Do not change the speed multiplier 3.584392177 without Garmin app verification
- Do not add pyproject.toml -- requirements.txt is the established pattern
- Do not add new test frameworks -- there is no pytest suite
- Do not widen a dependency major bound without a migration plan (see `zed_plans/garmin_influx_dependency_upgrade_2026-08-09.md` for the pattern)

## Testing

- No pytest suite. test_e2e.py is ad-hoc and requires Docker + real InfluxDB
- mcp_server/test_mcp_client.py is gitignored (not tracked)
- Run integration tests manually with `docker-compose up -d` before any significant changes

<!-- Guidelines:
     - Keep the whole file under 150 lines
     - Focus on what an AI agent needs to be immediately productive
     - Commands must be copy-paste ready
     - File structure should match current reality (update when structure changes)
-->
