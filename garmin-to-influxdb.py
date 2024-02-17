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

import logging
logging.basicConfig(level=logging.DEBUG)
start_date = date(2023,9,1)
end_date = date(2023,9,17)

today = date.today()
# The speed multiplier was found by taking the "averageSpeed" float from an activity and comparing
# to the speed reporting in the app. For example a speed of 1.61199998 * multiplyer = 5.77804 km/hr
speed_multiplier = 3.584392177
garmin_username = ''
garmin_password = ""

garmin_date_format = "%Y-%m-%d"
influx_server = "x.x.x.x"
influx_port = 8086
influx_username = ""
influx_password = ""
influx_db = ""
influxdb_time_format = "%Y-%m-%dT%H:%M:%SZ"
gather_hrv_data = False

def get_data_from_garmin(component, command, client=None):
    """
    This method attempts to get data from Garmin. In order to be dynamically called, methods available on the
    Garmin client are passed in as strings. Therefore you need to run the eval() command in order to actually
    execute the client methods.

    :param component: This is the heading to retrieve i.e. total step count
    :param command: Method on Garmin object to be called. I.E.: client.get_steps_data
    :param client: this is the Garmin client object
    :return: returns the results from the Garmin server
    """
    try:
        result = eval(command)
    except (
        GarminConnectConnectionError,
        GarminConnectAuthenticationError,
        GarminConnectTooManyRequestsError,
    ) as err:
        print(f"Error occurred during Garmin Connect Client get {component}: {err}")
        quit()
    except Exception as e:  # pylint: disable=broad-except
        print(e)
        print(f"Unknown error occurred during Garmin Connect Client get {component}")
        quit()
    return result


def connect_to_garmin(username, password):
    """
    initialize the connection to garmin servers
    The library will try to relogin when session expires

    :param username: garmin username
    :param password: garmin connect password
    :return: client object
    """

    print("Garmin(email, password)")
    print("----------------------------------------------------------------------------------------")
    try:
        client = Garmin(username, password)
    except (
            GarminConnectConnectionError,
            GarminConnectAuthenticationError,
            GarminConnectTooManyRequestsError,
    ) as err:
        print(f"Error occurred during Garmin Connect Client get initial client: {err}")
        quit()
    except Exception:
        print("Unknown error occurred during Garmin Connect Client get initial client")
        quit()
    print("client.login()")
    print("----------------------------------------------------------------------------------------")
    login_command = "client.login()"
    get_data_from_garmin("login", login_command, client=client)
    return client


def download_all_activity(client, activities):
    """
    Download an Activity
    """
    try:
        for activity in activities:
            activity_id = activity["activityId"]
            print("client.download_activities(%s)", activity_id)
            print("----------------------------------------------------------------------------------------")

            gpx_data = client.download_activity(activity_id, dl_fmt=client.ActivityDownloadFormat.GPX)
            output_file = f"./{str(activity_id)}.gpx"
            with open(output_file, "wb") as fb:
                fb.write(gpx_data)

            tcx_data = client.download_activity(activity_id, dl_fmt=client.ActivityDownloadFormat.TCX)
            output_file = f"./{str(activity_id)}.tcx"
            with open(output_file, "wb") as fb:
                fb.write(tcx_data)

            zip_data = client.download_activity(activity_id, dl_fmt=client.ActivityDownloadFormat.ORIGINAL)
            output_file = f"./{str(activity_id)}.zip"
            with open(output_file, "wb") as fb:
                fb.write(zip_data)

            csv_data = client.download_activity(activity_id, dl_fmt=client.ActivityDownloadFormat.CSV)
            output_file = f"./{str(activity_id)}.csv"
            with open(output_file, "wb") as fb:
              fb.write(csv_data)
    except (
        GarminConnectConnectionError,
        GarminConnectAuthenticationError,
        GarminConnectTooManyRequestsError,
    ) as err:
        print(f"Error occurred during Garmin Connect Client get activity data: {err}")
        quit()
    except Exception:  # pylint: disable=broad-except
        print("Unknown error occurred during Garmin Connect Client get activity data")
        quit()


def create_json_body(measurement, measurement_value, datestamp, tags=None):
    """
    This creates the json body that will be used to create measurements in InfluxDB

    :param measurement: The name of the measurement to be created
    :param measurement_value: the numerical value of the measurement
    :param datestamp: datestamp in the following format: 2020-10-20T00:00:00Z
    :param tags: any tags to be assiated with the measurement. Expects a dict
    :return: json object
    """
    return [
        {
            "measurement": measurement,
            "tags": tags,
            "time": datestamp,
            "fields": {
                "value": measurement_value
            }
        }
    ]


def create_influxdb_daily_measurement(user_data, influxdb_client):
    """
    Creates a measurement based on once-a-day values in Garmin such as total steps

    :param user_data: A dict with information pulled down from garmin
    :param influxdb_client: the client connection object to the InfluxDB
    :return: Nothing. Simply writes to the DB
    """
    for heading, value in user_data.items():
        print("Adding %s\nValue: %s" % (heading, value))
        if value is None:
            print("Unknown whether value should be an INT or a FLOAT. Manually intervention "
                  "for this day is required")
        else:
            if "minutes" in heading.lower():
                value = value / 60
            print(user_data['current_date'])
            json_body = create_json_body(heading, value, user_data['current_date'])
            influxdb_client.write_points(json_body)


def create_influxdb_multi_measurement(user_data, subset_list_of_stats, start_time_heading, date_format,
                                      timestamp_offset=False):
    """
    This method is for handling objects that have potential for multiple readings per day
    Such as multiple activities

    :param user_data: A dict with information pulled down from garmin
    :param influxdb_client: the client connection object to the InfluxDB
    :param subset_list_of_stats: A lot of objects from Garmin have far too much information.
    This is a dict of a small subset
    :param start_time_heading: The datestamp for the start of an event. Acts as a unique ID
    :param date_format: Date objects from Garmin come in different forms. This object is expected to be
    the correct format for the type of object being handled
    :param timestamp_offset: For some reason, some date objects are too far behind. If an offset is needed, toggle this
    :return: Nothing. Simply writes to the DB
    """
    temp_dict = {}
    date_format = date_format
    for entry in user_data:
        activity_start = entry[start_time_heading]
        if timestamp_offset:
            timestamp = time.mktime(time.strptime(activity_start, date_format)) + 14400
        else:
            timestamp = time.mktime(time.strptime(activity_start, date_format))
        current_date = time.strftime(influxdb_time_format, time.localtime(round(timestamp)))
        for heading in subset_list_of_stats:
            try:
                temp_dict[current_date].update({heading: entry[heading]})
            except KeyError:
                temp_dict[current_date] = {heading: entry[heading]}
    for heading, inner_dict in temp_dict.items():
        for inner_heading, value in inner_dict.items():
            if value is None:
                print("Unknown whether value should be an INT or a FLOAT. Manually intervention "
                      "for this day is required")
            else:
                if "speed" in inner_heading.lower():
                    value = value * speed_multiplier
                json_body = create_json_body(inner_heading, value, heading)
                print(current_date)
                print("Adding: %s\nValue: %s" % (inner_heading, value))
                influxdb_client.write_points(json_body)
    print("")


client = connect_to_garmin(username=garmin_username,password=garmin_password)

# unless you want to graph the hourly heart rate times heart_rate is useless as you can get this info
# from the daily stats
# heart_rate = get_data_from_garmin("heart_rate", "client.get_heart_rates(today.isoformat())", client=client)

activities = get_data_from_garmin("activities", "client.get_activities(0, 10)", client=client)  # 0=start, 1=limit
activity_list = ['distance', 'duration', 'averageSpeed', 'maxSpeed', 'averageHR', 'maxHR',
                'averageRunningCadenceInStepsPerMinute', 'steps', 'avgStrideLength']
# there is very little data in the step_data so it's not worth re-skinning
time_delta = end_date - start_date
influxdb_client = InfluxDBClient(influx_server, influx_port, influx_username, influx_password, influx_db)
create_influxdb_multi_measurement(activities, activity_list, 'startTimeLocal', '%Y-%m-%d %H:%M:%S',
                                 timestamp_offset=True)
for x in range(time_delta.days +1):
    day = str(start_date + timedelta(days=x))
    client_get_data = f'client.get_steps_data("{day}")'
    client_get_sleep = f'client.get_sleep_data("{day}")'
    client_get_stats = f'client.get_stats("{day}")'
    
    step_data = get_data_from_garmin("step_data", client_get_data, client=client)
    
    stats = get_data_from_garmin("stats", client_get_stats, client=client)
    sleep_data = get_data_from_garmin("sleep_data", client_get_sleep, client=client)
    sleep_data_date = time.mktime(time.strptime(sleep_data['dailySleepDTO']['calendarDate'], garmin_date_format))
    # Adding 20000 seconds to the date to account for the GMT offset. Without this, activities were showing up
    # on previous day in InfluxDB
    daily_stats_date = time.mktime(time.strptime(stats['calendarDate'], garmin_date_format)) + 20000
    floor_data = {
        'floors_ascended': stats['floorsAscended'],
        'floors_descended':  stats['floorsDescended'],
        "current_date": time.strftime(influxdb_time_format, time.localtime(daily_stats_date))
    }
    useful_daily_sleep_data = {
        'awake_minutes': sleep_data['dailySleepDTO']['awakeSleepSeconds'],
        'light_sleep_minutes': sleep_data['dailySleepDTO']['lightSleepSeconds'],
        'deep_sleep_minutes': sleep_data['dailySleepDTO']['deepSleepSeconds'],
        'total_sleep_minutes': sleep_data['dailySleepDTO']['sleepTimeSeconds'],
        'current_date': time.strftime(influxdb_time_format, time.localtime(sleep_data_date))
                              }
    heart_rate = {
        "lowest_heart_rate": stats['minHeartRate'],
        "highest_heart_rate": stats['maxHeartRate'],
        "resting_heart_rate": stats['restingHeartRate'],
        "current_date": time.strftime(influxdb_time_format, time.localtime(daily_stats_date))
    }
    
    daily_stats = {
        "total_burned_calories": stats['totalKilocalories'],
        "current_date": time.strftime(influxdb_time_format, time.localtime(daily_stats_date)),
        "total_steps": stats['totalSteps'],
        "daily_step_goal": stats['dailyStepGoal'],
        "highly_active_minutes": stats['highlyActiveSeconds'],
        "moderately_active_minutes": stats['activeSeconds'],
        "sedentary_minutes": stats['sedentarySeconds']
    }
    
    if gather_hrv_data:
        # Only gather this data if the user has set this to true
        # This data isn't available on all devices so it will error if set to True by default
        client_get_hrv = f'client.get_hrv_data("{day}")'
        hrv_data = get_data_from_garmin("hrv_data", client_get_hrv, client=client)
        hrv_daily_summary = {
            "hrv_last_night_avg": hrv_data['hrvSummary']['lastNightAvg'],
            "hrv_weekly_avg": hrv_data['hrvSummary']['weeklyAvg'],
            "hrv_status": hrv_data['hrvSummary']['status'],
            "current_date": time.strftime(influxdb_time_format, time.localtime(daily_stats_date)) 
        }
        create_influxdb_daily_measurement(hrv_daily_summary, influxdb_client)
        
    create_influxdb_daily_measurement(daily_stats, influxdb_client)
    create_influxdb_daily_measurement(useful_daily_sleep_data, influxdb_client)
    create_influxdb_daily_measurement(heart_rate, influxdb_client)
    create_influxdb_daily_measurement(floor_data, influxdb_client)
    
    step_list = ['steps']

    create_influxdb_multi_measurement(step_data, step_list, 'startGMT', "%Y-%m-%dT%H:%M:%S.%f",
                                      )
    print(day)
    time.sleep(2.5)

print("")
