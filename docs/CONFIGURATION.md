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
| `MODEL_ORDER` | `benchmark` | Rank the existing general models by October measured complete-result speed, per media type/length. `manual` explicitly opts out. |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | Primary model only with `MODEL_ORDER=manual`; otherwise the measured benchmark chain is used. |
| `GEMINI_SUMMARY_MODEL` | `gemini-3.5-flash` | General-purpose model used to summarize, translate, or clean output after a dedicated Gemini 3.5 Transcribe model. Must not be a Transcribe model. |
| `MODEL_REQUEST_TIMEOUT` | `40` | Timeout for one Gemini request in seconds. |
| `PRIMARY_MODEL_ATTEMPTS` | `1` | Attempts made with the primary model before continuing. Minimum is one. |
| `FALLBACK_MODEL_ATTEMPTS` | `1` | Attempts per fallback model. Minimum is one. |

The application also has a built-in fallback model chain. Keep the configured model compatible
with your Gemini account and update the chain in `bot.py` when Google deprecates a model.
The rationale and exact measured medians are in [MODEL_SPEED_ORDER.md](MODEL_SPEED_ORDER.md).
Live is an independent preview for observed Telegram jobs up to ten minutes, not a sequential
main-chain model. Longer media skips the preview. A legacy manual Live primary maps to file STT.

For dedicated file STT, set both `MODEL_ORDER=manual` and `GEMINI_MODEL=gemini-3.5-transcribe`.
Summary, TL;DR, translation or cleanup then use `GEMINI_SUMMARY_MODEL`. The file endpoint accepts
up to one hour. Increase `MODEL_REQUEST_TIMEOUT` for long recordings if required.

User context/UI choices are stored per private chat/group, not in environment variables;
see [USER_SETTINGS_CONTEXT.md](USER_SETTINGS_CONTEXT.md). Context and technical details default OFF.

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
| `MAX_ACTIVE_JOBS_GLOBAL` | `5` | Maximum concurrent media jobs across the whole bot process. |
| `MAX_QUEUED_JOBS` | `25` | Maximum number of jobs waiting in the in-memory queue. |
| `MAX_QUEUED_JOBS_PER_USER` | `5` | Maximum queued jobs belonging to one user. |
| `MAX_MEDIA_BYTES` | `20971520` | Maximum accepted media size in bytes (20 MiB by default). |

Overflow jobs are queued in memory until either the global or per-user queue limit is reached.
New jobs are rejected with a user-facing message when the queue is full. Restarting the process
clears the queue but does not delete the permanent SQLite processing history.

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
