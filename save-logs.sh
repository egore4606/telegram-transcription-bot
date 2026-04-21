#!/bin/bash
# Incremental daily backup of bot logs to the local bot/logs directory.
# On the first run, exports only the last 24 hours to avoid duplicating the full
# retained Docker log history. Subsequent runs export only new lines since the
# previous successful run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
DATE="$(date +%Y-%m-%d)"
LOG_FILE="$LOG_DIR/bot-$DATE.log"
STATE_FILE="$LOG_DIR/.save-logs-state"

mkdir -p "$LOG_DIR"

TMP_LOG_FILE="$(mktemp "$LOG_DIR/.bot-$DATE-XXXXXX.tmp")"
TMP_STATE_FILE="$(mktemp "$LOG_DIR/.save-logs-state-XXXXXX.tmp")"
trap 'rm -f "$TMP_LOG_FILE" "$TMP_STATE_FILE"' EXIT

if [[ -f "$STATE_FILE" ]]; then
    SINCE="$(cat "$STATE_FILE")"
else
    SINCE="$(date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%SZ')"
fi
UNTIL="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

docker compose -f "$COMPOSE_FILE" logs --no-color --since "$SINCE" --until "$UNTIL" > "$TMP_LOG_FILE"

if [[ -s "$TMP_LOG_FILE" ]]; then
    cat "$TMP_LOG_FILE" >> "$LOG_FILE"
fi

printf '%s\n' "$UNTIL" > "$TMP_STATE_FILE"
mv "$TMP_STATE_FILE" "$STATE_FILE"
