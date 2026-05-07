#!/usr/bin/env python3
"""End-to-end test for garmin-influxdb MCP server via docker compose."""
import subprocess, json, time, sys

compose_file = "/home/stratus/git_projects/garmin-influxdb/docker-compose.yml"

def send(proc, req):
    msg = json.dumps(req).encode()
    proc.stdin.write(msg + b"\n")
    proc.stdin.flush()

def recv(proc, timeout=5):
    import select
    r, _, _ = select.select([proc.stdout], [], [], timeout)
    if r:
        return proc.stdout.readline()
    return None

print("=== Starting MCP server container ===")
proc = subprocess.Popen(
    ["docker", "compose", "-f", compose_file, "run", "--rm", "-T", "garmin-influxdb-mcp"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    cwd="/home/stratus/git_projects/garmin-influxdb",
)

time.sleep(3)

# Check if it started
if proc.poll() is not None:
    # container exited
    err = proc.stderr.read()
    print("CONTAINER EXITED EARLY:")
    print(err.decode()[:500])
    sys.exit(1)

# 1. Initialize
print("\n=== 1. Initialize ===")
send(proc, {"jsonrpc": "2.0", "id": 0, "method": "initialize",
           "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                      "clientInfo": {"name": "e2e-test", "version": "1.0"}}})
resp = recv(proc, timeout=5)
if resp:
    print("INIT OK:", resp.decode()[:200])
else:
    print("NO INIT RESPONSE")
    err = proc.stderr.read()
    print("STDERR:", err.decode()[:300])
    proc.terminate()
    sys.exit(1)

# 2. List tools
print("\n=== 2. List tools ===")
send(proc, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
resp = recv(proc, timeout=5)
if resp:
    data = json.loads(resp.decode())
    tools = data.get("result", {}).get("tools", [])
    print(f"Found {len(tools)} tools:", [t["name"] for t in tools])
else:
    print("NO TOOLS RESPONSE")
    proc.terminate()
    sys.exit(1)

# 3. Call list_metrics
print("\n=== 3. list_metrics ===")
send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
           "params": {"name": "list_metrics", "arguments": {}}})
resp = recv(proc, timeout=5)
if resp:
    data = json.loads(resp.decode())
    content = data.get("result", {}).get("content", [])
    if content:
        print("list_metrics:", content[0].get("text", "")[:300])
else:
    print("NO RESPONSE")
    proc.terminate()
    sys.exit(1)

# 4. Call query_fitness_data
print("\n=== 4. query_fitness_data (4 weeks) ===")
send(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
           "params": {"name": "query_fitness_data",
                      "arguments": {"metric": "total_distance_meters", "aggregation": "sum", "range": "4w"}}})
resp = recv(proc, timeout=10)
if resp:
    data = json.loads(resp.decode())
    content = data.get("result", {}).get("content", [])
    if content:
        print("query_fitness_data:", content[0].get("text", "")[:500])
else:
    print("NO RESPONSE")
    proc.terminate()
    sys.exit(1)

# 5. Call sync_garmin for 1 day
print("\n=== 5. sync_garmin (1 day: 2026-04-12) ===")
send(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
           "params": {"name": "sync_garmin",
                      "arguments": {"start_date": "2026-04-12", "end_date": "2026-04-12"}}})
resp = recv(proc, timeout=30)
if resp:
    data = json.loads(resp.decode())
    content = data.get("result", {}).get("content", [])
    if content:
        print("sync_garmin:", content[0].get("text", "")[:500])
else:
    print("NO RESPONSE (sync may be taking longer due to Garmin rate-limit delay)")
    # check stderr
    se = proc.stderr.read()
    if se:
        print("STDERR:", se.decode()[:300])

proc.terminate()
print("\n=== DONE ===")