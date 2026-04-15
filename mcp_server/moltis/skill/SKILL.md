---
name: garmin-fitness
description: Garmin Connect + InfluxDB fitness data MCP. Query steps, sleep, HRV, heart rate, activities; sync new data from Garmin Connect. Use when the user asks about their fitness data, training, sleep, steps, calories, or wants to sync new data from Garmin.
allowed_tools:
  - mcp__garmin-fitness__list_metrics
  - mcp__garmin-fitness__query_fitness_data
  - mcp__garmin-fitness__query_activities
  - mcp__garmin-fitness__delete_data
  - mcp__garmin-fitness__sync_garmin
---

# Garmin Fitness MCP

## Tool Routing

### "what measurements/metrics do you have?" / "what data is in the DB?"
→ `list_metrics()` — no arguments. Returns all measurement names.

### "how many steps did I get last week?" / "total steps this month" / "average heart rate over 7 days"
→ `query_fitness_data` — requires `metric`, `range`, `aggregation`. See Metric Catalog below.

### "show me my recent runs/workouts/activities" / "what did I do yesterday?"
→ `query_activities` — requires `range`, optional `fields`, `limit`, `activity_type`.

### "delete my sleep data for March" / "remove steps from last week"
→ `delete_data` — requires `measurement`, `range`. **Always confirm with the user before calling this.** Data is permanently deleted.

### "sync/pull new data from Garmin" / "refresh my fitness data"
→ `sync_garmin` — optional `start_date`, `end_date` (YYYY-MM-DD). Without dates, syncs from the day after the latest data in DB up to today (~30 days typical). **Each day takes ~2.5s due to Garmin rate-limiting.** Warn the user if syncing more than 14 days.

### "how far did I run this month?" / "total miles walked in March" / "total running time last week"
→ Use `query_fitness_data` with an Activity Field metric (`distance`, `duration`, `averageSpeed`, etc.) + `activity_type` filter + `aggregation="sum"`. Convert meters to miles (/ 1609.34) or seconds to hours (/ 3600) as needed.

## Metric Catalog

Use these metric names exactly in `query_fitness_data(metric="...")`. Call `list_metrics()` only when the user asks what measurements exist or when a metric they expect is missing from the catalog.

### Daily Stats (one row per day)

| Metric | Description | Unit hint |
|--------|-------------|-----------|
| `total_steps` | Daily step count | steps |
| `total_burned_calories` | Calories burned | kcal |
| `total_distance_meters` | Distance traveled | meters (→ miles via / 1609.34) |
| `daily_step_goal` | Daily step goal | steps |
| `highly_active_minutes` | Vigorous activity | seconds (→ hours via / 3600) |
| `moderately_active_minutes` | Moderate activity | seconds (→ hours via / 3600) |
| `sedentary_minutes` | Sedentary time | seconds (→ hours via / 3600) |

### Sleep

| Metric | Description |
|--------|-------------|
| `total_sleep_minutes` | Total time asleep |
| `light_sleep_minutes` | Light sleep |
| `deep_sleep_minutes` | Deep sleep |
| `awake_minutes` | Time awake after sleep onset |

### Heart Rate

| Metric | Description |
|--------|-------------|
| `resting_heart_rate` | Resting HR |
| `lowest_heart_rate` | Minimum HR that day |
| `highest_heart_rate` | Maximum HR that day |

### Floors

| Metric | Description |
|--------|-------------|
| `floors_ascended` | Floors climbed up |
| `floors_descended` | Floors climbed down |

### HRV

| Metric | Description |
|--------|-------------|
| `hrv_last_night_avg` | Last night's HRV average |
| `hrv_weekly_avg` | Weekly HRV average |

### Activity Fields (per-activity, tagged with `activityType`)

> **Note**: These metrics support `activity_type` filtering in `query_fitness_data`. Daily Stats, Sleep, Heart Rate, Floors, and HRV metrics do **not** have activity type tags -- `activity_type` is ignored for those.

| Metric | Description | Unit hint |
|--------|-------------|-----------|
| `distance` | Activity distance | meters |
| `duration` | Activity duration | seconds (→ hours via / 3600) |
| `averageSpeed` | Avg speed | km/h (→ mph via × 0.621371) |
| `maxSpeed` | Max speed | km/h |
| `averageHR` | Avg heart rate | bpm |
| `maxHR` | Max heart rate | bpm |
| `steps` | Steps during activity | steps |
| `averageRunningCadenceInStepsPerMinute` | Running cadence | spm |
| `avgStrideLength` | Average stride length | cm |

### Intraday Steps

| Metric | Description |
|--------|-------------|
| `steps` | Per-timestamp step counts throughout the day |

## Range Formats

Two formats are accepted:

- **Relative**: `now() - <duration>` — e.g. `4w` (4 weeks), `7d` (7 days), `1d` (1 day)
- **Absolute**: `YYYY-MM-DD..YYYY-MM-DD` — e.g. `2026-01-01..2026-04-13`

Examples:
- Last 4 weeks: `range="4w"`
- March 2026: `range="2026-03-01..2026-03-31"`
- Since Jan 1st: `range="2026-01-01..2026-04-13"`

## Aggregations

Pass to `aggregation=` in `query_fitness_data`:

| Value | Meaning |
|-------|---------|
| `sum` | Total (steps, calories, distance) |
| `mean` | Average |
| `min` | Minimum |
| `max` | Maximum |
| `count` | Number of data points |
| `last` | Most recent value |

## Activity Types

Use with `activity_type=["running"]` etc. in `query_fitness_data` or `query_activities`. Common types: `running`, `walking`, `cycling`, `swimming`, `strength_training`, `yoga`, `hiit`, `other`. Filter by multiple: `activity_type=["running", "cycling"]`.

## Common Query Patterns

### Weekly step total
```
query_fitness_data(metric="total_steps", range="1w", aggregation="sum")
```

### Average sleep duration over 2 weeks
```
query_fitness_data(metric="total_sleep_minutes", range="2w", aggregation="mean")
```
→ Display as hours: divide seconds by 3600.

### Resting HR trend (daily for 4 weeks)
```
query_fitness_data(metric="resting_heart_rate", range="4w", aggregation="mean", group_by="1d")
```

### Recent 5 activities
```
query_activities(range="2w", limit=5)
```

### Recent runs only
```
query_activities(range="4w", limit=10, activity_type=["running"])
```

### Weekly calories burned
```
query_fitness_data(metric="total_burned_calories", range="1w", aggregation="sum")
```

### HRV this week vs last week
```
query_fitness_data(metric="hrv_last_night_avg", range="1w", aggregation="mean")
query_fitness_data(metric="hrv_last_night_avg", range="2w", aggregation="mean")
```

### Total running + walking distance in a date range
```
query_fitness_data(metric="distance", range="2026-01-01..2026-03-31", aggregation="sum", activity_type=["running", "walking"])
```
Result is in meters -- divide by 1609.34 for miles.

### Total running duration this month
```
query_fitness_data(metric="duration", range="4w", aggregation="sum", activity_type=["running"])
```
Result is in seconds -- divide by 3600 for hours.

## Sync Guidance

`sync_garmin()` without dates:
- **Start**: day after the latest `total_steps` entry in InfluxDB, or 30 days ago if DB is empty
- **End**: today
- **Rate**: ~2.5 seconds per day (Garmin API limit)

### When to run sync
- New Garmin data is not showing up → sync
- After a missed day or vacation → sync with explicit `start_date` and `end_date`
- Before answering questions about the last few days → sync first if data seems missing

### Large sync warning
If the default range would sync more than 14 days, warn the user: "This will take ~35 seconds due to Garmin rate-limiting. Continue?" Use explicit short ranges when the user only needs recent data.

### Sync with explicit dates
```
sync_garmin(start_date="2026-04-01", end_date="2026-04-13")
```

## Anti-Patterns

- **Do NOT call `list_metrics()` to check what metrics exist** — the Metric Catalog in this skill lists all of them. Call `list_metrics()` only when the user asks "what measurements do you have?".
- **Do NOT call `delete_data` without explicit user confirmation.** Data is permanent. Show the user what will be deleted first: "Delete all `total_sleep_minutes` from 2026-03-01 to 2026-03-31? This cannot be undone."
- **Do NOT call `sync_garmin` with no date range for large gaps** — if the user asks to sync "all of March", specify `start_date` and `end_date` explicitly rather than relying on the auto-default which starts from the latest data.
- **Do NOT assume the DB has recent data** — if the user asks about yesterday's steps and the answer looks stale, suggest running `sync_garmin()`.
- **Do NOT use aggregation `mean` on metrics that are already daily totals** (like `total_steps`) and then compare across different range sizes without accounting for the difference. A 4-week `sum` and 1-week `sum` need the same time base for comparison.
