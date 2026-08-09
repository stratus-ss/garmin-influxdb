# scripts/ — operational wrappers

This directory holds shell wrappers that codify multi-step InfluxDB operations
performed from the operator host. Each script:

- exits non-zero on any failure (`set -euo pipefail`)
- prints structured progress (`migrate_influxdb_garmin: <step>`) so the devlog
  can quote output verbatim
- never prints the InfluxDB admin password (credentials are read from the
  remote container's env via `docker exec ... printenv` and passed only to the
  `influx` CLI on the remote side)
- is referenced by name from the plan file rather than inlined as ad-hoc shell

## migrate_influxdb_garmin.sh

Performs the `total_steps` and `total_burned_calories` field-type rewrite:

1. `influxd backup -portable -db garmin -host 127.0.0.1:8088` inside the
   `influxdb-metrics` container, copied to the host backup root
2. For each measurement, in order:
   - `SHOW FIELD KEYS` (pre-state, logged to devlog)
   - `SELECT "value"::integer AS "value" INTO "<m>_temp" FROM "<m>"` (full
     measurement; no time filter)
   - count-check `SELECT count("value") FROM "<m>_temp"` matches the
     pre-rewrite count
   - `DROP MEASUREMENT "<m>"`
   - `SELECT "value" INTO "<m>" FROM "<m>_temp"` (rebuilds the measurement;
     temp was integer so the type is locked)
   - `DROP MEASUREMENT "<m>_temp"`
   - `SHOW FIELD KEYS` (post-state — must report only `integer`)

### Required remote state

| Component | Value |
|-----------|-------|
| SSH host | `root@containers.x86experts.com` (override with `MIGRATE_SSH_HOST`) |
| InfluxDB container | `influxdb-metrics` (override with `MIGRATE_CONTAINER`) |
| Database | `garmin` (override with `MIGRATE_DATABASE`) |
| Backup host dir | `/var/lib/influxdb-metrics/backups` (override with `MIGRATE_BACKUP_ROOT`) |
| Container env vars | `INFLUXDB_ADMIN_USER`, `INFLUXDB_ADMIN_PASSWORD` |
| Backup endpoint port | `8088` (`-host 127.0.0.1:8088`) |

The script reads credentials via:

```
u=$(ssh "$SSH_HOST" "docker exec $CONTAINER printenv INFLUXDB_ADMIN_USER")
p=$(ssh "$SSH_HOST" "docker exec $CONTAINER printenv INFLUXDB_ADMIN_PASSWORD")
```

`$p` is passed only to `docker exec ... influx -password "$p"` on the remote
side. The script never `echo`s or `set -x`s the password locally.

### Usage

```bash
# Full run (backup + migration of both measurements)
./scripts/migrate_influxdb_garmin.sh

# Backup-only (creates restore point without rewriting measurements)
./scripts/migrate_influxdb_garmin.sh --backup-only

# Migrate-only (assumes backup already taken; rewrites both measurements)
./scripts/migrate_influxdb_garmin.sh --migrate-only
```

### Recovery from a failed migration

1. Confirm backup directory exists on the host:
   `ssh root@containers.x86experts.com ls /var/lib/influxdb-metrics/backups/<BACKUP_NAME>`
2. Stop the InfluxDB container:
   `ssh root@containers.x86experts.com docker stop influxdb-metrics`
3. Restore the portable backup:
   `ssh root@containers.x86experts.com docker exec influxdb-metrics influxd restore -portable -db garmin /var/lib/influxdb/backups/<BACKUP_NAME>`
4. Restart the container:
   `ssh root@containers.x86experts.com docker start influxdb-metrics`
5. Re-enable any sync sources disabled during migration.

### Why a wrapper?

The plan authoring protocol (EXECUTION_PROTOCOL.md §6) requires a wrapper
when the same shell sequence is executed more than once. This script replaces
the original plan's inline `influx -username admin -password ...` chains with
a single reference and:

- pins the auth path so it cannot regress to literal credentials
- reuses a single SSH control connection
- exits non-zero on any step, which the executor's TASK_QUEUE can pick up as
  BLOCKED without parsing multi-line command output

### Why not in `/tmp`?

Per EXECUTION_PROTOCOL.md §1.5, operational artifacts and wrappers belong in
the repo tree so they survive reboots, session churn, and machine moves. The
script is committed alongside the plan that references it.

## Dependency Rollback

The MCP container is pinned to mcp 2.x and runs the `MCPServer` API. If
the deployed container must be rolled back to a working state quickly:

### Container rollback

The currently deployed image is `quay.io/sovens/mcps/garmin-influxdb:0.6.1`.
Local copies of older tags are retained:

- `0.5` — pre-type-fix; float writer, working server (NOT a valid rollback
  for the integer-field invariant — re-deploying 0.5 will re-introduce
  field-type conflicts in `total_steps`, `total_burned_calories`, etc.)
- `0.6` — integer writer, broken mcp 2.0 import (not a working server)
- `0.6.1` — current, integer writer + mcp 2.0 `MCPServer`

The honest rollback that preserves the type-fix outcome is:

```bash
git revert <sha-of-server.py-edit>     # restore mcp.server.fastmcp import
sed -i 's/mcp>=2.0,<3.0/mcp>=1.27,<2.0/' mcp_server/requirements.txt
docker build -f mcp_server/Dockerfile -t quay.io/sovens/mcps/garmin-influxdb:0.6.2 .
docker push quay.io/sovens/mcps/garmin-influxdb:0.6.2
ssh stratus@arch-openclaw 'docker pull quay.io/sovens/mcps/garmin-influxdb:0.6.2 && \
  docker stop garmin-influxdb-mcp && docker rm garmin-influxdb-mcp && \
  docker run -d --name garmin-influxdb-mcp --network host --restart unless-stopped \
    -w /app -e INFLUX_HOST=... -e INFLUX_USER=... \
    -e INFLUX_PASS=... -e INFLUX_DB=garmin -e INFLUX_PORT=8087 \
    -e GARMIN_USER=... -e GARMIN_PASS=... \
    quay.io/sovens/mcps/garmin-influxdb:0.6.2 sleep infinity'
```

### Venv rollback

The `venv_garmin` virtualenv is recreated on Python 3.14.6 to satisfy
garminconnect 0.3.x's `Python>=3.12` requirement. A pre-upgrade pip-freeze
snapshot is saved at:

```
/tmp/venv_garmin_freeze_2026-08-09.txt
```

Rollback to the previous (garminconnect 0.2.x) venv:

```bash
python3.11 -m venv venv_garmin
venv_garmin/bin/pip install -r /tmp/venv_garmin_freeze_2026-08-09.txt
```

Note: the rolled-back venv can only install garminconnect up to 0.3.2
because garminconnect >=0.3.3 requires Python 3.12+.