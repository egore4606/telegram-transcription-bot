# Configuration reference

Copy `.env.example` to `.env` and keep the real file outside version control.

## Credentials

| Variable | Required | Default | Description |
|---|---:|---|---|
| `TELEGRAM_TOKEN` | Yes | — | Telegram Bot API token from [@BotFather](https://t.me/BotFather). |
| `GEMINI_API_KEY` | Yes | — | Primary Google Gemini API key. |
| `GEMINI_API_KEY_2` | No | empty | Backup Gemini key used after the primary key fails or reaches quota. |
| `ADMIN_USER_ID` | Recommended | `0` | Telegram user ID allowed to run administrator commands. Use `/myid` to find it. |

## Models and retries

| Variable | Default | Description |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.5-flash` | First model attempted by the fallback chain. |
| `MODEL_REQUEST_TIMEOUT` | `40` | Timeout for one Gemini request in seconds. |
| `PRIMARY_MODEL_ATTEMPTS` | `1` | Attempts made with the primary model before continuing. Minimum is one. |
| `FALLBACK_MODEL_ATTEMPTS` | `1` | Attempts per fallback model. Minimum is one. |

The application also has a built-in fallback model chain. Keep the configured model compatible
with your Gemini account and update the chain in `bot.py` when Google deprecates a model.

## Storage

| Variable | Default | Description |
|---|---|---|
| `DATABASE_PATH` | `/data/bot.sqlite3` | SQLite path. The Compose files persist `/data` in a named volume. |
| `PENDING_FEEDBACK_TTL_SECONDS` | `900` | Time in seconds that `/feedback` waits for the user's next message. |

## Limits

| Variable | Default | Description |
|---|---|---|
| `RATE_LIMIT` | `5` | Media-processing requests allowed per user per minute. |
| `COMMAND_RATE_LIMIT` | `10` | Ordinary commands allowed during the command window. |
| `COMMAND_RATE_LIMIT_WINDOW_SECONDS` | `300` | Command rate-limit window in seconds. |
| `MAX_ACTIVE_JOBS_PER_USER` | `3` | Concurrent active media jobs for one user. |
| `MAX_ACTIVE_JOBS_PER_CHAT` | `5` | Concurrent active media jobs for one private chat or group. |

Overflow jobs are queued in memory. Restarting the process clears the queue but does not delete
the permanent SQLite processing history.

## Progress updates

| Variable | Default | Description |
|---|---|---|
| `PROGRESS_PRIVATE_REFRESH_INTERVAL` | `1` | Minimum seconds between progress edits in private chats. |
| `PROGRESS_GROUP_REFRESH_INTERVAL` | `5` | Minimum seconds between progress edits in groups. Values below three are raised to three. |

Aggressive refresh values can trigger Telegram flood control. The defaults are intentionally more
conservative for groups.

## Admin panel service

These variables are set directly by `docker-compose.yml` for the admin-panel container:

| Variable | Default | Description |
|---|---|---|
| `ADMIN_PANEL_HOST` | `0.0.0.0` | Listen address inside the container. |
| `ADMIN_PANEL_PORT` | `8081` | Listen port inside the container. |

The host binding remains `127.0.0.1:8081`, so the panel is reachable only locally or through an
SSH tunnel.
