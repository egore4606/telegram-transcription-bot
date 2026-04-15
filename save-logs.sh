#!/bin/bash
# Daily backup of bot logs to the local bot/logs directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
DATE="$(date +%Y-%m-%d)"

mkdir -p "$LOG_DIR"
TMP_FILE="$(mktemp "$LOG_DIR/.bot-$DATE-XXXXXX.tmp")"
trap 'rm -f "$TMP_FILE"' EXIT

docker compose -f "$COMPOSE_FILE" logs --no-color > "$TMP_FILE" 2>&1
mv "$TMP_FILE" "$LOG_DIR/bot-$DATE.log"
