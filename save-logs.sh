#!/bin/bash
# Daily backup of bot logs
LOG_DIR="/root/Telegram/logs"
DATE=$(date +%Y-%m-%d)
docker compose -f /root/Telegram/docker-compose.yml logs --no-color > "$LOG_DIR/bot-$DATE.log" 2>&1
# Keep only last 30 days
find "$LOG_DIR" -name "bot-*.log" -mtime +30 -delete
