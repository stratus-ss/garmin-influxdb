"""Orchestrates historical Garmin -> InfluxDB sync in weekly batches.

Usage:
    python sync_historical.py                    # resume from last saved state
    python sync_historical.py --start 2019-04-11  # override start date
    python sync_historical.py --dry-run           # print chunk plan without syncing

State is persisted to sync_state.json so crashes can be resumed.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path

from garminconnect import GarminConnectConnectionError
from influxdb import InfluxDBClient

from garmin_to_influxdb import (
    BATCH_DELAY_SECONDS,
    DEFAULT_SYNC_DELAY_SECONDS,
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
    connect_to_garmin,
    load_dotenv,
    sync_range,
)

# Load .env via shared helper
load_dotenv()

logger = logging.getLogger("sync_historical")


def _week_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Yield half-open week intervals [start, end) covering start->end."""
    chunks = []
    cur = start
    while cur <= end:
        week_end = cur + timedelta(days=6)
        if week_end > end:
            week_end = end
        chunks.append((cur, week_end))
        cur += timedelta(days=7)
    return chunks


def _state_path() -> Path:
    return Path(__file__).parent / "sync_state.json"


def _load_state() -> dict:
    p = _state_path()
    if p.exists():
        return json.loads(p.read_text())
    return {}


def _save_state(state: dict) -> None:
    _state_path().write_text(json.dumps(state, indent=2))


def _chunk_key(chunk_start: date) -> str:
    return chunk_start.isoformat()


def _run_chunk(
    garmin_client,
    influxdb_client,
    chunk_start: date,
    chunk_end: date,
    delay_seconds: float,
    activities_only: bool = False,
) -> dict:
    """Sync one chunk with connection-error retry. Returns result dict."""
    for attempt in range(MAX_RETRIES):
        try:
            return sync_range(
                garmin_client,
                influxdb_client,
                chunk_start,
                chunk_end,
                delay_seconds=delay_seconds,
                activities_only=activities_only,
            )
        except GarminConnectConnectionError as exc:
            if attempt == 0:
                logger.warning(
                    "Connection error on %s, retrying in 60s: %s",
                    chunk_start,
                    exc,
                )
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                return {
                    "days_synced": 0,
                    "days_failed": 1,
                    "activities_written": 0,
                    "activities_returned": 0,
                    "errors": [str(exc)],
                }
        except Exception as exc:
            return {
                "days_synced": 0,
                "days_failed": 1,
                "activities_written": 0,
                "activities_returned": 0,
                "errors": [str(exc)],
            }


def run(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    start_date = date.fromisoformat(args.start) if args.start else date(2019, 4, 11)
    end_date = date.fromisoformat(args.end) if args.end else date.today()
    delay_seconds = args.delay
    batch_delay = args.batch_delay

    if args.dry_run:
        chunks = _week_chunks(start_date, end_date)
        logger.info("Dry run -- %d chunks would be processed:", len(chunks))
        for s, e in chunks:
            logger.info("  %s -> %s  (%d days)", s, e, (e - s).days + 1)
        return

    chunks = _week_chunks(start_date, end_date)
    state = _load_state()

    # Reuse a single Garmin client across all chunks so the garth
    # token cache keeps us logged in without re-auth.
    garmin_client = connect_to_garmin(
        username=os.getenv("GARMIN_USER", ""),
        password=os.getenv("GARMIN_PASS", ""),
    )
    if garmin_client is None:
        raise RuntimeError("Garmin login failed. Check credentials and token store.")

    influxdb_client = InfluxDBClient(
        host=os.getenv("INFLUX_HOST", "localhost"),
        port=int(os.getenv("INFLUX_PORT", "8086")),
        username=os.getenv("INFLUX_USER", ""),
        password=os.getenv("INFLUX_PASS", ""),
        database=os.getenv("INFLUX_DB", "garmin"),
    )

    total_synced = 0
    total_failed = 0
    succeeded_chunks = 0
    failed_chunks = 0

    for idx, (chunk_start, chunk_end) in enumerate(chunks):
        key = _chunk_key(chunk_start)
        chunk_state = state.get(key)

        if not args.force and chunk_state and chunk_state.get("status") == "complete":
            logger.info(
                "[%s -> %s]  SKIP (already complete, %d days synced)",
                chunk_start,
                chunk_end,
                chunk_state.get("days_synced", 0),
            )
            total_synced += chunk_state.get("days_synced", 0)
            succeeded_chunks += 1
            continue

        days_in_chunk = (chunk_end - chunk_start).days + 1
        logger.info(
            "===== [%d/%d] Syncing %s -> %s (%d days) =====",
            idx + 1,
            len(chunks),
            chunk_start,
            chunk_end,
            days_in_chunk,
        )

        result = _run_chunk(
            garmin_client,
            influxdb_client,
            chunk_start,
            chunk_end,
            delay_seconds,
            activities_only=args.activities_only,
        )

        if result["days_failed"] > 0:
            logger.warning(
                "First attempt had %d failures for chunk %s, retrying once...",
                result["days_failed"],
                chunk_start,
            )
            time.sleep(RETRY_DELAY_SECONDS)
            result = _run_chunk(
                garmin_client,
                influxdb_client,
                chunk_start,
                chunk_end,
                delay_seconds,
                activities_only=args.activities_only,
            )

        if result["days_failed"] > 0:
            logger.error(
                "[%s -> %s]  FAILED: %d days failed -- %s",
                chunk_start,
                chunk_end,
                result["days_failed"],
                result["errors"],
            )
            state[key] = {
                "status": "failed",
                "chunk_end": str(chunk_end),
                "days_synced": result["days_synced"],
                "days_failed": result["days_failed"],
                "activities_written": result.get("activities_written", 0),
                "errors": result["errors"],
            }
            total_failed += result["days_failed"]
            failed_chunks += 1
        else:
            logger.info(
                "[%s -> %s]  OK: %d days synced, %d activities written",
                chunk_start,
                chunk_end,
                result["days_synced"],
                result.get("activities_written", 0),
            )
            state[key] = {
                "status": "complete",
                "chunk_end": str(chunk_end),
                "days_synced": result["days_synced"],
                "activities_written": result.get("activities_written", 0),
            }
            total_synced += result["days_synced"]
            succeeded_chunks += 1

        _save_state(state)

        if idx < len(chunks) - 1:
            logger.info("Sleeping %ds before next chunk...", batch_delay)
            time.sleep(batch_delay)

    logger.info("")
    logger.info("========== SUMMARY ==========")
    logger.info("  Total chunks:  %d", len(chunks))
    logger.info("  Succeeded:     %d", succeeded_chunks)
    logger.info("  Failed:        %d", failed_chunks)
    logger.info("  Total days synced: %d", total_synced)
    if failed_chunks > 0:
        logger.info(
            "  Failed chunks are marked in %s -- edit to 'complete' to skip on resume",
            _state_path(),
        )
    logger.info("=============================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Historical Garmin -> InfluxDB sync orchestrator"
    )
    parser.add_argument(
        "--start",
        help="Override start date (YYYY-MM-DD). Default: 2019-04-11 or last saved state",
    )
    parser.add_argument(
        "--end",
        help="Override end date (YYYY-MM-DD). Default: today",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_SYNC_DELAY_SECONDS,
        help="Seconds to wait between each day during sync. Default: 4",
    )
    parser.add_argument(
        "--batch-delay",
        type=int,
        default=BATCH_DELAY_SECONDS,
        help="Seconds to wait between chunks. Default: 300",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the chunk plan without calling Garmin API",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-sync all chunks, ignoring completed state in sync_state.json",
    )
    parser.add_argument(
        "--activities-only",
        action="store_true",
        help="Only re-fetch and write activity data, skipping daily stats/sleep/HR. "
        "Useful for re-syncing activities after a failed or empty chunk.",
    )
    run(parser.parse_args())
