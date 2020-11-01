# Python Garmin Connect data converter to InfluxDB

This script stands on the giants of the [GarminConnect PyPi](https://pypi.org/project/garminconnect/) as well as the [InfluxDB PyPi](https://influxdb-python.readthedocs.io/en/latest/include-readme.html). 

This script has no usage, although in the future perhaps it will take username, password, server information and/or date ranges as script parameters. You will need to edit the following variables in the script:
```
start_date = date(2018,4,1)
end_date = date(2020,11,1)
garmin_username = 
garmin_password = 
influx_server = 
influx_port = 
influx_username = 
influx_password = 
influx_db = 
```

You should not edit the date or time format variables in the script unless something stops working. Garmin provides at least 3 different date/time stamps in their data and this needs to be converted to the InfluxDB expected format.

I have made some opinionated choices about which type of data is valuable. There are significant portions of data from Garmin that are most likely not worth storing long term.

**IMPORTANT NOTE**: I am using time delta in order to loop over various dates for bulk collection of data. The intent is to be able to run this once a week and pull down the updates to be stored in InfluxDB.

This should be considered ALPHA version. It is functional but will absolutely have bugs
