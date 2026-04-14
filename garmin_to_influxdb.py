#!/usr/bin/env python3
# Nov 1, 2020
# This script is intended to download data from Garmin and then insert it into an InfluxDB


from garminconnect import (
    Garmin,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
    GarminConnectAuthenticationError,
)

from datetime import date, timedelta
import time
from influxdb import InfluxDBClient
from garth.exc import GarthHTTPError
import os
import requests
import logging
import argparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
start_date = date(2026, 4, 6)
end_date = date(2026, 4, 13)
tokenstore = ".garminconnect"
speed_multiplier = 3.584392177
# The speed multiplier was found by taking the "averageSpeed" float from an activity and comparing
# to the speed reporting in the app. For example a speed of 1.61199998 * multiplyer = 5.77804 km/hr
garmin_username = os.getenv("GARMIN_USER", "")
garmin_password = os.getenv("GARMIN_PASS", "")

garmin_date_format = "%Y-%m-%d"
influx_server = os.getenv("INFLUX_HOST", "localhost")
influx_port = int(os.getenv("INFLUX_PORT", "8086"))
influx_username = os.getenv("INFLUX_USER", "")
influx_password = os.getenv("INFLUX_PASS", "")
influx_db = os.getenv("INFLUX_DB", "garmin")
influxdb_time_format = "%Y-%m-%dT%H:%M:%SZ"


def get_data_from_garmin(component, method_name, args=None, client=None):
    """
    Call a method on the Garmin client by name with given arguments.

    :param component: Description of the data being fetched (for logging)
    :param method_name: Name of the method on the Garmin client, e.g. "get_stats"
    :param args: Tuple of positional arguments to pass to the method
    :param client: The Garmin client object
    :return: Result from the Garmin API call
    """
    try:
        method = getattr(client, method_name)
        return method(*(args or []))
    except (
        GarminConnectConnectionError,
        GarminConnectAuthenticationError,
        GarminConnectTooManyRequestsError,
    ) as err:
        logger.error("Garmin Connect error during %s: %s", component, err)
        raise
    except Exception as e:
        logger.error("Error during %s: %s", component, e)
        raise


def connect_to_garmin(username, password):
    """
    initialize the connection to garmin servers
    The library will try to relogin when session expires

    :param username: garmin username
    :param password: garmin connect password
    :return: client object
    """

    # print("Garmin(email, password)")
    # print("----------------------------------------------------------------------------------------")
    # try:
    #     client = Garmin(username, password)
    # except (
    #         GarminConnectConnectionError,
    #         GarminConnectAuthenticationError,
    #         GarminConnectTooManyRequestsError,
    # ) as err:
    #     print("Error occurred during Garmin Connect Client get initial client: %s" % err)
    #     quit()
    # except Exception:
    #     print("Unknown error occurred during Garmin Connect Client get initial client")
    #     quit()
    # print("client.login()")
    # print("----------------------------------------------------------------------------------------")
    # login_command = "client.login()"
    # get_data_from_garmin("login", login_command, client=client)
    # return client

    try:
        logger.info("Login to Garmin Connect using token data from '%s'...", tokenstore)
        garmin = Garmin()
        garmin.login(tokenstore)
    except (FileNotFoundError, GarthHTTPError, GarminConnectAuthenticationError):
        logger.info(
            "Tokens not found -- login with credentials to generate them. "
            "They will be saved to '%s'.", tokenstore
        )
        try:
            garmin = Garmin(garmin_username, garmin_password)
            garmin.login()
            garmin.garth.dump(tokenstore)

        except (
            FileNotFoundError,
            GarthHTTPError,
            GarminConnectAuthenticationError,
            requests.exceptions.HTTPError,
        ) as err:
            logger.error("Login failed: %s", err)
            return None

    return garmin


def download_all_activity(client, activities):
    for activity in activities:
        activity_id = activity["activityId"]
        logger.info("Downloading activity %s", activity_id)

        gpx_data = client.download_activity(
            activity_id, dl_fmt=client.ActivityDownloadFormat.GPX
        )
        output_file = f"./{str(activity_id)}.gpx"
        with open(output_file, "wb") as fb:
            fb.write(gpx_data)

        tcx_data = client.download_activity(
            activity_id, dl_fmt=client.ActivityDownloadFormat.TCX
        )
        output_file = f"./{str(activity_id)}.tcx"
        with open(output_file, "wb") as fb:
            fb.write(tcx_data)

        zip_data = client.download_activity(
            activity_id, dl_fmt=client.ActivityDownloadFormat.ORIGINAL
        )
        output_file = f"./{str(activity_id)}.zip"
        with open(output_file, "wb") as fb:
            fb.write(zip_data)

        csv_data = client.download_activity(
            activity_id, dl_fmt=client.ActivityDownloadFormat.CSV
        )
        output_file = f"./{str(activity_id)}.csv"
        with open(output_file, "wb") as fb:
            fb.write(csv_data)


def create_json_body(measurement, measurement_value, datestamp, tags=None):
    if tags is None:
        tags = {}
    json_body = [
        {
            "measurement": measurement,
            "tags": tags,
            "time": datestamp,
            "fields": {"value": measurement_value},
        }
    ]
    return json_body


def create_influxdb_daily_measurement(user_data, influxdb_client):
    for heading, value in user_data.items():
        if heading == "current_date":
            continue
        if value is None:
            logger.info("  Skipping '%s': null value", heading)
            continue
        if "minutes" in heading.lower():
            value = value / 60
        logger.info("  %s: %s", heading, value)
        json_body = create_json_body(heading, value, user_data["current_date"])
        influxdb_client.write_points(json_body)


def create_influxdb_multi_measurement(
    user_data,
    subset_list_of_stats,
    start_time_heading,
    date_format,
    timestamp_offset=False,
    entry_tags_fn=None,
    influxdb_client=None,
):
    """
    Handles objects with multiple readings per day, such as activities.

    :param user_data: List of dicts from Garmin
    :param subset_list_of_stats: Keys to extract from each entry
    :param start_time_heading: Key containing the timestamp for each entry
    :param date_format: strptime format for the timestamp
    :param timestamp_offset: Apply +14400s offset if True (for local->UTC correction)
    :param entry_tags_fn: Optional callable(entry) -> dict of tags to attach to each point
    """
    temp_dict = {}
    for entry in user_data:
        activity_start = entry[start_time_heading]
        if timestamp_offset:
            timestamp = time.mktime(time.strptime(activity_start, date_format)) + 14400
        else:
            timestamp = time.mktime(time.strptime(activity_start, date_format))
        current_date = time.strftime(
            influxdb_time_format, time.localtime(round(timestamp))
        )
        tags = entry_tags_fn(entry) if entry_tags_fn else None
        for heading in subset_list_of_stats:
            value = entry.get(heading)
            if value is None:
                continue
            if heading not in temp_dict.get(current_date, {}):
                temp_dict.setdefault(current_date, {})[heading] = value
            else:
                temp_dict[current_date][heading] = value
    for heading, inner_dict in temp_dict.items():
        for inner_heading, value in inner_dict.items():
            if value is None:
                logger.info("  Skipping '%s': null value", inner_heading)
                continue
            if "speed" in inner_heading.lower():
                value = value * speed_multiplier
            json_body = create_json_body(inner_heading, value, heading, tags=tags)
            influxdb_client.write_points(json_body)


def _activity_tags(entry):
    """Extract activityType tag from an activity dict returned by Garmin."""
    at = entry.get("activityType")
    if isinstance(at, dict):
        return {"activityType": at.get("typeKey", "unknown")}
    return {"activityType": "unknown"}


def sync_activities(client, influxdb_client, start_date, end_date):
    """Fetch and write activities for the given date range. Returns dict with counts."""
    activity_list = [
        "distance",
        "duration",
        "averageSpeed",
        "maxSpeed",
        "averageHR",
        "maxHR",
        "averageRunningCadenceInStepsPerMinute",
        "steps",
        "avgStrideLength",
    ]
    try:
        activities = get_data_from_garmin(
            "activities",
            "get_activities_by_date",
            args=(str(start_date), str(end_date)),
            client=client,
        )
        activities_returned = len(activities)
        written = 0
        for entry in activities:
            start_local = entry.get("startTimeLocal")
            if not start_local:
                continue
            ts = time.mktime(time.strptime(start_local, "%Y-%m-%d %H:%M:%S")) + 14400
            datestamp = time.strftime(
                influxdb_time_format, time.localtime(round(ts))
            )
            tags = _activity_tags(entry)
            for heading in activity_list:
                value = entry.get(heading)
                if value is None:
                    continue
                if "speed" in heading.lower():
                    value = value * speed_multiplier
                body = create_json_body(heading, value, datestamp, tags=tags)
                influxdb_client.write_points(body)
            written += 1
        logger.info("Wrote %d activities to InfluxDB", written)
        return {
            "days_synced": 1,
            "days_failed": 0,
            "activities_written": written,
            "activities_returned": activities_returned,
            "errors": [],
        }
    except Exception as exc:
        return {
            "days_synced": 0,
            "days_failed": 1,
            "activities_written": 0,
            "activities_returned": 0,
            "errors": [str(exc)],
        }


def sync_day(client, influxdb_client, day_str, gather_hrv_data=False):
    """Sync all data for a single day. Returns None on success, error string on failure."""
    try:
        step_data = get_data_from_garmin("step_data", "get_steps_data", args=(day_str,), client=client)
        hrv_data = get_data_from_garmin("hrv_data", "get_hrv_data", args=(day_str,), client=client)
        stats = get_data_from_garmin("stats", "get_stats", args=(day_str,), client=client)
        sleep_data = get_data_from_garmin("sleep_data", "get_sleep_data", args=(day_str,), client=client)
        sleep_data_date = time.mktime(
            time.strptime(sleep_data["dailySleepDTO"]["calendarDate"], garmin_date_format)
        )
        daily_stats_date = (
            time.mktime(time.strptime(stats["calendarDate"], garmin_date_format)) + 20000
        )
        floor_data = {
            "floors_ascended": stats["floorsAscended"],
            "floors_descended": stats["floorsDescended"],
            "current_date": time.strftime(
                influxdb_time_format, time.localtime(daily_stats_date)
            ),
        }
        useful_daily_sleep_data = {
            "awake_minutes": sleep_data["dailySleepDTO"]["awakeSleepSeconds"],
            "light_sleep_minutes": sleep_data["dailySleepDTO"]["lightSleepSeconds"],
            "deep_sleep_minutes": sleep_data["dailySleepDTO"]["deepSleepSeconds"],
            "total_sleep_minutes": sleep_data["dailySleepDTO"]["sleepTimeSeconds"],
            "current_date": time.strftime(
                influxdb_time_format, time.localtime(sleep_data_date)
            ),
        }
        heart_rate = {
            "lowest_heart_rate": stats["minHeartRate"],
            "highest_heart_rate": stats["maxHeartRate"],
            "resting_heart_rate": stats["restingHeartRate"],
            "current_date": time.strftime(
                influxdb_time_format, time.localtime(daily_stats_date)
            ),
        }
        daily_stats = {
            "total_burned_calories": stats["totalKilocalories"],
            "current_date": time.strftime(
                influxdb_time_format, time.localtime(daily_stats_date)
            ),
            "total_steps": stats["totalSteps"],
            "total_distance_meters": stats["totalDistanceMeters"],
            "daily_step_goal": stats["dailyStepGoal"],
            "highly_active_minutes": stats["highlyActiveSeconds"],
            "moderately_active_minutes": stats["activeSeconds"],
            "sedentary_minutes": stats["sedentarySeconds"],
        }
        create_influxdb_daily_measurement(daily_stats, influxdb_client)
        create_influxdb_daily_measurement(useful_daily_sleep_data, influxdb_client)
        create_influxdb_daily_measurement(heart_rate, influxdb_client)
        create_influxdb_daily_measurement(floor_data, influxdb_client)

        if gather_hrv_data:
            try:
                hrv_daily_summary = {
                    "hrv_last_night_avg": hrv_data["hrvSummary"]["lastNightAvg"],
                    "hrv_weekly_avg": hrv_data["hrvSummary"]["weeklyAvg"],
                    "current_date": time.strftime(
                        influxdb_time_format, time.localtime(daily_stats_date)
                    ),
                }
                create_influxdb_daily_measurement(hrv_daily_summary, influxdb_client)
            except Exception:
                pass

        create_influxdb_multi_measurement(
            step_data,
            ["steps"],
            "startGMT",
            "%Y-%m-%dT%H:%M:%S.%f",
            influxdb_client=influxdb_client,
        )
        logger.info("Synced %s", day_str)
        return None
    except Exception as exc:
        return str(exc)


def sync_range(client, influxdb_client, start_date, end_date, delay_seconds=4.0, gather_hrv_data=False, activities_only=False):
    """
    Sync all data for a date range (activities + per-day stats).
    Returns dict with days_synced, days_failed, activities_written, activities_returned, errors.
    If activities_only=True, skips per-day stats and returns after syncing activities.
    """
    time_delta = end_date - start_date
    errors = []
    activities_written = 0
    activities_returned = 0

    # Activities (one shot for the whole range)
    act_result = sync_activities(client, influxdb_client, str(start_date), str(end_date))
    activities_written = act_result.get("activities_written", 0)
    activities_returned = act_result.get("activities_returned", 0)
    if act_result["days_failed"] > 0:
        errors.append({"date": "activities", "error": act_result["errors"][0]})

    if activities_only:
        if activities_returned == 0 and time_delta.days >= 3:
            logger.warning(
                "Zero activities returned for %s -> %s (%d days) -- check Garmin session",
                start_date,
                end_date,
                time_delta.days + 1,
            )
        failed = len(errors)
        return {
            "days_synced": time_delta.days + 1,
            "days_failed": failed,
            "activities_written": activities_written,
            "activities_returned": activities_returned,
            "errors": errors,
        }

    # Per-day data
    for x in range(time_delta.days + 1):
        day = str(start_date + timedelta(days=x))
        err = sync_day(client, influxdb_client, day, gather_hrv_data=gather_hrv_data)
        if err:
            errors.append({"date": day, "error": err})
        time.sleep(delay_seconds)

    failed = len(errors)
    synced = (time_delta.days + 1) - failed
    return {"days_synced": synced, "days_failed": failed, "activities_written": activities_written, "activities_returned": activities_returned, "errors": errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync Garmin Connect data to InfluxDB")
    parser.add_argument(
        "--start",
        default=None,
        help="Start date (YYYY-MM-DD). Defaults to the hardcoded start_date below.",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="End date (YYYY-MM-DD). Defaults to the hardcoded end_date below.",
    )
    args = parser.parse_args()

    _start = date.fromisoformat(args.start) if args.start else start_date
    _end = date.fromisoformat(args.end) if args.end else end_date

    client = connect_to_garmin(username=garmin_username, password=garmin_password)
    influxdb_client = InfluxDBClient(
        influx_server, influx_port, influx_username, influx_password, influx_db
    )
    sync_range(client, influxdb_client, _start, _end)
