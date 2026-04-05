#!/bin/bash
# Daily backup of bot logs to /root/Telegram/logs/bot-YYYY-MM-DD.log
LOG_DIR="/root/Telegram/logs"
DATE=$(date +%Y-%m-%d)
docker compose -f /root/Telegram/docker-compose.yml logs --no-color > "$LOG_DIR/bot-$DATE.log" 2>&1
