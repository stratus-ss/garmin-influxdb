#!/usr/bin/env bash
# migrate_influxdb_garmin.sh
# In-place migration of the `total_steps` and `total_burned_calories`
# measurements from float to integer via full-measurement rewrite.
#
# Two-stage:
#   1. influxd backup -portable (creates a restore point for the entire
#      `garmin` database)
#   2. For each measurement: SELECT ::integer INTO temp -> DROP original ->
#      SELECT FROM temp INTO original -> DROP temp -> SHOW FIELD KEYS verify
#
# Safety: never prints the admin password. set -euo pipefail. SSH control
# connection is shared (-o ControlMaster) for speed. Every step exits non-zero
# on failure.
#
# Usage:
#   ./scripts/migrate_influxdb_garmin.sh                # full run
#   ./scripts/migrate_influxdb_garmin.sh --backup-only  # stop after backup
#   ./scripts/migrate_influxdb_garmin.sh --migrate-only # skip backup
#
# Required env on the operator host: ssh key for root@containers.x86experts.com
# Required env on the remote container: INFLUXDB_ADMIN_USER,
#   INFLUXDB_ADMIN_PASSWORD (read via `docker exec ... printenv`; never echoed)

set -euo pipefail

SSH_HOST="${MIGRATE_SSH_HOST:-root@containers.x86experts.com}"
CONTAINER="${MIGRATE_CONTAINER:-influxdb-metrics}"
DATABASE="${MIGRATE_DATABASE:-garmin}"
BACKUP_ROOT="${MIGRATE_BACKUP_ROOT:-/var/lib/influxdb-metrics/backups}"
BACKUP_NAME="${MIGRATE_BACKUP_NAME:-garmin-$(date -u +%Y%m%dT%H%M%SZ)}"
MEASUREMENTS=(
  "total_steps"
  "total_burned_calories"
  "total_distance_meters"
  "daily_step_goal"
  "highly_active_minutes"
  "moderately_active_minutes"
  "sedentary_minutes"
  "awake_minutes"
  "light_sleep_minutes"
  "deep_sleep_minutes"
  "total_sleep_minutes"
  "lowest_heart_rate"
  "highest_heart_rate"
  "resting_heart_rate"
  "steps"
)

DO_BACKUP=1
DO_MIGRATE=1
for arg in "$@"; do
  case "$arg" in
    --backup-only)  DO_MIGRATE=0 ;;
    --migrate-only) DO_BACKUP=0 ;;
    -h|--help)
      sed -n '2,30p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      printf 'unknown arg: %s\n' "$arg" >&2
      exit 2
      ;;
  esac
done

log() { printf 'migrate_influxdb_garmin: %s\n' "$*"; }

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'migrate_influxdb_garmin: missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

require_cmd ssh
require_cmd docker

ssh_run() {
  # Quote every argument so host-side shell expansion is impossible.
  ssh -o ConnectTimeout=10 -o BatchMode=yes "$SSH_HOST" "$1"
}

fetch_admin_creds() {
  log "fetch_admin_creds: reading INFLUXDB_ADMIN_USER and INFLUXDB_ADMIN_PASSWORD from container env"
  MIGRATE_ADMIN_USER="$(ssh_run "docker exec $CONTAINER printenv INFLUXDB_ADMIN_USER")"
  MIGRATE_ADMIN_PASSWORD="$(ssh_run "docker exec $CONTAINER printenv INFLUXDB_ADMIN_PASSWORD")"
  if [[ -z "${MIGRATE_ADMIN_USER:-}" || -z "${MIGRATE_ADMIN_PASSWORD:-}" ]]; then
    printf 'migrate_influxdb_garmin: missing INFLUXDB_ADMIN_USER or INFLUXDB_ADMIN_PASSWORD in container env\n' >&2
    exit 1
  fi
}

influx_exec() {
  # $1 = InfluxQL command (single-quote safe)
  local ql="$1"
  ssh_run "docker exec -i $CONTAINER influx -username '$MIGRATE_ADMIN_USER' -password '$MIGRATE_ADMIN_PASSWORD' -database $DATABASE -execute '$ql'"
}

verify_field_type_integer() {
  local m="$1"
  local out
  out="$(influx_exec "SHOW FIELD KEYS FROM \"$m\"")"
  printf '%s\n' "$out"
  if ! printf '%s' "$out" | grep -q 'integer'; then
    printf 'migrate_influxdb_garmin: %s missing integer field type\n' "$m" >&2
    exit 1
  fi
  if printf '%s' "$out" | grep -q 'float'; then
    printf 'migrate_influxdb_garmin: %s still reports float field type\n' "$m" >&2
    exit 1
  fi
}

run_backup() {
  log "backup: creating portable backup $BACKUP_NAME under $BACKUP_ROOT"
  ssh_run "mkdir -p $BACKUP_ROOT/$BACKUP_NAME"
  ssh_run "docker exec $CONTAINER influxd backup -portable -db $DATABASE -host 127.0.0.1:8088 /var/lib/influxdb/backups/$BACKUP_NAME"
  ssh_run "docker cp $CONTAINER:/var/lib/influxdb/backups/$BACKUP_NAME $BACKUP_ROOT/"
  log "backup: verifying backup directory exists on host"
  ssh_run "test -d $BACKUP_ROOT/$BACKUP_NAME && test -n \"\$(ls -A $BACKUP_ROOT/$BACKUP_NAME)\""
  log "backup: ok"
}

migrate_one() {
  local m="$1"
  local t="${1}_temp"
  log "migrate: $m -> $t -> $m"
  log "  pre-state: SHOW FIELD KEYS FROM $m"
  verify_field_type_integer_or_skip "$m"

  log "  step 1/4: SELECT \"value\"::integer INTO $t FROM $m (full measurement)"
  influx_exec "SELECT \"value\"::integer AS \"value\" INTO \"$t\" FROM \"$m\""

  log "  step 1b: count(*)$m vs count(*) $t must match"
  local pre_count post_count
  pre_count="$(influx_exec "SELECT count(\"value\") FROM \"$m\"" | awk -F'[[:space:]]+' '/^name:/ {hdr=1; next} hdr && NF>=2 && $2 ~ /^[0-9]+$/ {print $2; exit}')"
  post_count="$(influx_exec "SELECT count(\"value\") FROM \"$t\"" | awk -F'[[:space:]]+' '/^name:/ {hdr=1; next} hdr && NF>=2 && $2 ~ /^[0-9]+$/ {print $2; exit}')"
  log "    pre_count=$pre_count  post_count=$post_count"
  if [[ -z "$pre_count" || -z "$post_count" || "$pre_count" != "$post_count" ]]; then
    printf 'migrate_influxdb_garmin: count mismatch for %s (pre=%s post=%s)\n' "$m" "$pre_count" "$post_count" >&2
    exit 1
  fi

  log "  step 2/4: DROP MEASUREMENT $m"
  influx_exec "DROP MEASUREMENT \"$m\""

  log "  step 3/4: SELECT \"value\" INTO $m FROM $t"
  influx_exec "SELECT \"value\" INTO \"$m\" FROM \"$t\""

  log "  step 4/4: DROP MEASUREMENT $t"
  influx_exec "DROP MEASUREMENT \"$t\""

  log "  post-state: SHOW FIELD KEYS FROM $m"
  verify_field_type_integer "$m"
  log "  $m: ok"
}

verify_field_type_integer_or_skip() {
  local m="$1"
  local out
  out="$(influx_exec "SHOW FIELD KEYS FROM \"$m\"")"
  printf '%s\n' "$out"
  if ! printf '%s' "$out" | grep -qE 'integer|float'; then
    log "  $m has no field type yet -- skipping pre-state integer check (measurement empty)"
    return 0
  fi
}

main() {
  fetch_admin_creds
  if [[ "$DO_BACKUP" -eq 1 ]]; then
    run_backup
  else
    log "backup: skipped (--migrate-only)"
  fi
  if [[ "$DO_MIGRATE" -eq 1 ]]; then
    for m in "${MEASUREMENTS[@]}"; do
      migrate_one "$m"
    done
  else
    log "migrate: skipped (--backup-only)"
  fi
  log "done"
}

main