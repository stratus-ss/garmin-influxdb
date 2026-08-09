# garmin-influxdb -- Code Flow Documentation

<!-- Purpose: Visualize runtime data and control flow using Mermaid diagrams.
     Each section covers one major workflow or pipeline stage.
     Keep text minimal -- let the diagrams do the talking. -->

---

## Table of Contents

1. [One-Shot Sync Pipeline](#1-one-shot-sync-pipeline)
2. [Historical Backfill Orchestration](#2-historical-backfill-orchestration)
3. [Per-Day Sync Detail](#3-per-day-sync-detail)
4. [MCP Read Path](#4-mcp-read-path)
5. [MCP Sync Path](#5-mcp-sync-path)
6. [Complete Data Flow Summary](#6-complete-data-flow-summary)
7. [Key Modules and Responsibilities](#7-key-modules-and-responsibilities)

---

## 1. One-Shot Sync Pipeline

Entry: `python garmin_to_influxdb.py`. Syncs recent activities and daily stats for a hardcoded date range.

```mermaid
flowchart TD
    A["garmin_to_influxdb.py<br/>__main__"] --> B["connect_to_garmin<br/>token-cached login"]
    B --> C["sync_range<br/>date-range orchestrator"]
    C --> D["sync_activities<br/>single range request"]
    C --> E["sync_day loop<br/>per-day stats"]
    D --> F["InfluxDB<br/>write_points"]
    E --> F
    F --> G["Logs: days_synced, activities_written"]
```

Note: `sync_range` is the universal write path shared by CLI, historical backfill, and MCP sync.

---

## 2. Historical Backfill Orchestration

Entry: `python sync_historical.py`. Splits date range into week chunks with state persistence.

```mermaid
flowchart TD
    A["sync_historical.py<br/>__main__"] --> B["load sync_state.json<br/>or create empty"]
    B --> C["_week_chunks<br/>split into 7-day intervals"]
    C --> D{"{chunk complete?}"}
    D -->|yes| G["skip, log"]
    D -->|no| E["connect_to_garmin<br/>single client reuse"]
    E --> F["_run_chunk<br/>sync_range + retry"]
    F --> H{"{days_failed > 0?}"}
    H -->|yes| I["mark failed, sleep 60s, retry once"]
    H -->|no| J["mark complete, save state"]
    I --> F
    J --> K["sleep 300s, next chunk"]
    K --> D
    G --> K
```

---

## 3. Per-Day Sync Detail

`sync_day` fetches and writes all stats for a single calendar day.

```mermaid
flowchart TD
    A["sync_day<br/>date string"] --> B["get_steps_data"]
    A --> C["get_hrv_data"]
    A --> D["get_stats"]
    A --> E["get_sleep_data"]
    B --> F["create_influxdb_multi_measurement<br/>steps, startGMT"]
    C --> G["create_influxdb_daily_measurement<br/>hrv_last_night_avg, hrv_weekly_avg"]
    D --> H["create_influxdb_daily_measurement<br/>floors, calories, steps, heart rate, active minutes"]
    E --> H
    F --> I["InfluxDB<br/>write_points"]
    G --> I
    H --> I
    I --> J["logger.info synced"]
```

---

## 4. MCP Read Path

Client calls one of: list_metrics, query_fitness_data, query_activities. No Garmin API involved.

```mermaid
sequenceDiagram
    participant Client as AI Agent
    participant Server as mcp_server/server.py
    participant Tools as mcp_server/tools.py
    participant IC as InfluxClient
    participant InfluxDB

    Client->>Server: tool call (e.g. query_fitness_data)
    Server->>Tools: list_metrics / query_fitness_data / query_activities
    Tools->>IC: _db_client() singleton
    IC->>InfluxDB: InfluxQL (SHOW MEAS, SELECT agg, SELECT from activities)
    InfluxDB-->>IC: measurement list / scalar result / activity rows
    IC-->>Tools: parsed result dict
    Tools-->>Server: JSON
    Server-->>Client: JSON string
```

---

## 5. MCP Sync Path

Client calls sync_garmin. Resolves date range, then calls connect_to_garmin + sync_range.

```mermaid
sequenceDiagram
    participant Client as AI Agent
    participant Server as mcp_server/server.py
    participant Tools as mcp_server/tools.py
    participant IC as InfluxClient
    participant Garmin as Garmin Connect API
    participant InfluxDB

    Client->>Server: sync_garmin(start_date, end_date, delay_seconds)
    Server->>Tools: sync_garmin()
    Tools->>IC: get_latest_timestamp()
    IC->>InfluxDB: SELECT last(value) FROM total_steps
    InfluxDB-->>IC: latest timestamp
    IC-->>Tools: start = latest + 1 day (or user-provided)
    Tools->>Tools: connect_to_garmin(username, password)
    Tools->>Garmin: garth token login
    Garmin-->>Tools: Garmin client
    Tools->>Garmin: get_activities_by_date(start, end)
    Tools->>Garmin: get_steps_data / get_stats / get_sleep_data (per day)
    Tools->>InfluxDB: write_points per measurement
    InfluxDB-->>Tools: write ack
    Tools-->>Server: result dict
    Server-->>Client: JSON result
```

---

## 6. Complete Data Flow Summary

End-to-end: Garmin Connect API sources -> sync layer -> InfluxDB storage.

```mermaid
flowchart LR
    subgraph Sources
        G["Garmin Connect API"]
    end

    subgraph SyncLayer ["Sync Layer (garmin_to_influxdb.py)"]
        A["connect_to_garmin"]
        B["sync_range"]
        C["sync_activities"]
        D["sync_day"]
        E["create_influxdb_multi_measurement"]
        F["create_influxdb_daily_measurement"]
    end

    subgraph Storage
        I["InfluxDB"]
    end

    Sources --> SyncLayer
    A --> B
    B --> C
    B --> D
    C --> E
    D --> F
    E --> I
    F --> I
```

---

## 7. Key Modules and Responsibilities

```mermaid
flowchart TB
    subgraph garmin_to_influxdb["garmin_to_influxdb.py"]
        A1["connect_to_garmin<br/>token-cached login via garth"]
        A2["sync_range<br/>orchestrates activities + per-day data"]
        A3["sync_activities<br/>single range fetch, write activity records"]
        A4["sync_day<br/>fetch + write daily stats for one day"]
        A5["create_influxdb_daily_measurement"]
        A6["create_influxdb_multi_measurement"]
    end

    subgraph sync_historical["sync_historical.py"]
        B1["_week_chunks<br/>split date range into 7-day intervals"]
        B2["_run_chunk<br/>sync_range with retry on connection error"]
        B3["run<br/>load/save state, loop chunks, apply delays"]
    end

    subgraph mcp_server_server["mcp_server/server.py"]
        C1["MCPServer app (mcp 2.x)<br/>8 tool decorators: list_metrics, query_fitness_data, query_activities, delete_data, add_shoe, list_shoes, query_shoe_distance, sync_garmin"]
    end

    subgraph mcp_server_tools["mcp_server/tools.py"]
        D1["_db_client<br/>lazy InfluxClient singleton"]
        D2["sync_garmin<br/>date resolution + connect_to_garmin + sync_range"]
        D3["query_fitness_data / query_activities / list_metrics / delete_data"]
    end

    subgraph mcp_server_influx_client["mcp_server/influx_client.py"]
        E1["InfluxClient<br/>InfluxDBClient wrapper"]
        E2["get_measurements<br/>SHOW MEASUREMENTS"]
        E3["query_scalar<br/>aggregation with group by time"]
        E4["query_activities<br/>multi-field activity log query"]
        E5["delete_measurement_range<br/>DELETE FROM with time clause"]
        E6["get_latest_timestamp<br/>SELECT last(value) FROM total_steps"]
    end

    sync_historical -->|imports| garmin_to_influxdb
    mcp_server_tools -->|imports| garmin_to_influxdb
    mcp_server_tools -->|imports| mcp_server_influx_client
    mcp_server_server -->|calls| mcp_server_tools
```

---

<!-- Guidelines:
     - Each section = one logical workflow or pipeline stage
     - Prefer flowchart for pipelines, sequenceDiagram for service interactions
     - Keep annotations outside the diagram blocks (below, as brief notes)
     - Use subgraph blocks to group related steps
     - Name nodes descriptively: A["Parse Config"] not A["Step 1"]
-->
