from datetime import date, timedelta
import time
import os
import logging

from garminconnect import (
    Garmin,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
    GarminConnectAuthenticationError,
)
from garth.exc import GarthHTTPError

logger = logging.getLogger(__name__)

INFLUX_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
GARMIN_DATE_FORMAT = "%Y-%m-%d"
SPEED_MULTIPLIER = 3.584392177

TOKENSTORE = os.path.join(os.path.dirname(__file__), "..", ".garminconnect")

ACTIVITY_FIELDS = [
    "distance", "duration", "averageSpeed", "maxSpeed",
    "averageHR", "maxHR", "averageRunningCadenceInStepsPerMinute",
    "steps", "avgStrideLength",
]


def _json_body(measurement: str, value: float, datestamp: str, tags=None) -> list[dict]:
    return [
        {
            "measurement": measurement,
            "tags": tags or {},
            "time": datestamp,
            "fields": {"value": value},
        }
    ]


class GarminSync:
    def __init__(self, influx_client, delay_seconds: float = 4.0):
        self._influx = influx_client
        self._client: Garmin | None = None
        self._delay = delay_seconds

    def connect(self) -> None:
        username = os.getenv("GARMIN_USER", "")
        password = os.getenv("GARMIN_PASS", "")
        self._client = Garmin(username, password)
        try:
            self._client.login(TOKENSTORE)
        except Exception:
            self._client.login()
        self._client.garth.dump(TOKENSTORE)

    def _get(self, component: str, command: str):
        client = self._client
        try:
            return eval(command)
        except (
            GarminConnectConnectionError,
            GarminConnectAuthenticationError,
            GarminConnectTooManyRequestsError,
        ) as err:
            logger.error("Garmin Connect error during %s: %s", component, err)
            raise
        except Exception as e:
            logger.error("Unknown error during %s: %s", component, e)
            raise

    def _write_daily(self, user_data: dict) -> None:
        for heading, value in user_data.items():
            if heading == "current_date":
                continue
            if value is None:
                continue
            if "minutes" in heading.lower():
                value = value / 60
            json_body = _json_body(heading, value, user_data["current_date"])
            self._influx.write_points(json_body)

    def _write_activities(self, activities: list[dict]) -> int:
        written = 0
        for activity in activities:
            start_local = activity.get("startTimeLocal")
            if not start_local:
                continue
            ts = time.mktime(time.strptime(start_local, "%Y-%m-%d %H:%M:%S")) + 14400
            datestamp = time.strftime(INFLUX_TIME_FORMAT, time.localtime(round(ts)))

            activity_type = "unknown"
            at = activity.get("activityType")
            if isinstance(at, dict):
                activity_type = at.get("typeKey", "unknown")
            tags = {"activityType": activity_type}

            for field in ACTIVITY_FIELDS:
                value = activity.get(field)
                if value is None:
                    continue
                if "speed" in field.lower():
                    value = value * SPEED_MULTIPLIER
                body = _json_body(field, value, datestamp, tags=tags)
                self._influx.write_points(body)
            written += 1
        logger.info("Wrote %d activities to InfluxDB", written)
        return written

    def _write_multi(
        self,
        user_data: list[dict],
        subset: list[str],
        start_heading: str,
        date_format: str,
    ) -> None:
        temp: dict[str, dict] = {}
        for entry in user_data:
            activity_start = entry.get(start_heading)
            if not activity_start:
                continue
            ts = time.mktime(time.strptime(activity_start, date_format))
            current_date = time.strftime(INFLUX_TIME_FORMAT, time.localtime(round(ts)))
            for heading in subset:
                try:
                    temp[current_date].update({heading: entry[heading]})
                except KeyError:
                    temp[current_date] = {heading: entry[heading]}
        for current_date, inner in temp.items():
            for heading, value in inner.items():
                if value is None:
                    continue
                json_body = _json_body(heading, value, current_date)
                self._influx.write_points(json_body)

    def sync(self, start_date: date, end_date: date, activities_only: bool = False) -> dict:
        if self._client is None:
            raise RuntimeError("Not connected. Call connect() first.")

        days = (end_date - start_date).days + 1
        errors = []

        activities_returned = 0
        activities_written = 0
        try:
            activities = self._get(
                "activities",
                f'client.get_activities_by_date("{start_date.isoformat()}", "{end_date.isoformat()}")',
            )
            activities_returned = len(activities)
            activities_written = self._write_activities(activities)
        except Exception as ex:
            logger.error("Failed to sync activities: %s", ex)
            errors.append({"date": "activities", "error": str(ex)})

        if activities_returned == 0 and days >= 3:
            logger.warning(
                "Zero activities returned for %s -> %s (%d days) -- check Garmin session",
                start_date,
                end_date,
                days,
            )

        if activities_only:
            return {"days_synced": days - len(errors), "days_failed": len(errors), "activities_written": activities_written, "activities_returned": activities_returned, "errors": errors}

        for i in range(days):
            day = start_date + timedelta(days=i)
            day_str = str(day)

            try:
                stats = self._get("stats", f'client.get_stats("{day_str}")')
                stats_ts = time.mktime(time.strptime(stats["calendarDate"], GARMIN_DATE_FORMAT)) + 20000
                stats_date = time.strftime(INFLUX_TIME_FORMAT, time.localtime(stats_ts))

                daily_stats = {
                    "total_burned_calories": stats["totalKilocalories"],
                    "current_date": stats_date,
                    "total_steps": stats["totalSteps"],
                    "total_distance_meters": stats["totalDistanceMeters"],
                    "daily_step_goal": stats["dailyStepGoal"],
                    "highly_active_minutes": stats["highlyActiveSeconds"],
                    "moderately_active_minutes": stats["activeSeconds"],
                    "sedentary_minutes": stats["sedentarySeconds"],
                }
                self._write_daily(daily_stats)

                sleep_data = self._get("sleep", f'client.get_sleep_data("{day_str}")')
                sleep_ts = time.mktime(time.strptime(sleep_data["dailySleepDTO"]["calendarDate"], GARMIN_DATE_FORMAT))
                sleep_date = time.strftime(INFLUX_TIME_FORMAT, time.localtime(sleep_ts))
                sleep = {
                    "awake_minutes": sleep_data["dailySleepDTO"]["awakeSleepSeconds"],
                    "light_sleep_minutes": sleep_data["dailySleepDTO"]["lightSleepSeconds"],
                    "deep_sleep_minutes": sleep_data["dailySleepDTO"]["deepSleepSeconds"],
                    "total_sleep_minutes": sleep_data["dailySleepDTO"]["sleepTimeSeconds"],
                    "current_date": sleep_date,
                }
                self._write_daily(sleep)

                heart_rate = {
                    "lowest_heart_rate": stats["minHeartRate"],
                    "highest_heart_rate": stats["maxHeartRate"],
                    "resting_heart_rate": stats["restingHeartRate"],
                    "current_date": stats_date,
                }
                self._write_daily(heart_rate)

                floors = {
                    "floors_ascended": stats["floorsAscended"],
                    "floors_descended": stats["floorsDescended"],
                    "current_date": stats_date,
                }
                self._write_daily(floors)

                # HRV
                try:
                    hrv_data = self._get("hrv", f'client.get_hrv_data("{day_str}")')
                    summary = hrv_data.get("hrvSummary") or {}
                    hrv = {
                        "hrv_last_night_avg": summary.get("lastNightAvg"),
                        "hrv_weekly_avg": summary.get("weeklyAvg"),
                        "current_date": stats_date,
                    }
                    self._write_daily(hrv)
                except Exception:
                    pass

                # Steps (intra-day)
                step_data = self._get("step_data", f'client.get_steps_data("{day_str}")')
                self._write_multi(step_data, ["steps"], "startGMT", "%Y-%m-%dT%H:%M:%S.%f")

            except Exception as ex:
                logger.error("Failed to sync %s: %s", day_str, ex)
                errors.append({"date": day_str, "error": str(ex)})

            time.sleep(self._delay)

        return {"days_synced": days - len(errors), "days_failed": len(errors), "activities_written": activities_written, "activities_returned": activities_returned, "errors": errors}
