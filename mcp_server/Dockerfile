FROM python:3.13-slim

WORKDIR /app

COPY mcp_server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy garmin_to_influxdb.py alongside server.py so bare imports work
COPY garmin_to_influxdb.py ./garmin_to_influxdb.py
COPY mcp_server/ ./mcp_server/

CMD ["python", "mcp_server/server.py"]
