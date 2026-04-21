# 🎙 Telegram Transcription Bot

Telegram bot that transcribes voice messages and video notes with Google Gemini, then replies in chat with a transcription, a summary, or a one-line TL;DR.

Works in private chats and groups. Settings are scoped separately for personal chats and each group.

## Features

- Transcribes **voice messages** (OGG audio)
- Transcribes **video notes** (circles) and also accounts for the visual part of the video
- Supports **four output modes** per scope: full, transcription only, summary only, TL;DR
- Stores **separate settings for private chats and groups**
- Supports **per-scope language setting**: `auto`, `ru`, `en`, `de`, ...
- Uses a **fallback API key** when the primary Gemini key hits quota
- Uses a **fallback model chain** when the current model is overloaded
- Shows a live **processing timer** while a voice/video is being handled
- Persists settings, stats, pending feedback, processed media history, and changelog delivery state in **SQLite**
- Lets users send **feedback** directly to the admin
- Syncs the Telegram **command menu automatically on startup**
- Supports an explicit **admin-only changelog broadcast** command with deduplication per changelog version
- Archives processed voice/video requests and Gemini model attempts in SQLite
- Saves daily Docker logs to `./logs/` with an **incremental backup script**
- Runs in **Docker** and survives restarts

## Commands

### User Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | Show commands and usage hints |
| `/both` | Transcription + summary *(default)* |
| `/transcription_only` | Only verbatim transcription |
| `/summary_only` | Only summary |
| `/tldr` | One sentence with the main point |
| `/language [code]` | Set response language: `auto`, `ru`, `en`, `de`, ... |
| `/myid` | Show your Telegram user ID |
| `/changelog` | Show the current public changelog |
| `/feedback` | Bot asks for feedback in the next message |
| `/feedback [text]` | Send feedback immediately in one command |
| `/ignore` | In groups, reply to a user message to toggle ignore *(group admins only)* |

### Admin Commands

| Command | Description |
|---|---|
| `/stats` | Bot stats and runtime info |
| `/block [user_id]` | Block a user globally |
| `/unblock [user_id]` | Remove a global block |
| `/broadcast_changelog` | Send the current changelog to known private-chat users |

The bot publishes these commands to Telegram Bot API automatically on startup:

- the user command set is synced as the default command menu;
- the admin chat gets an extended command set with both user and admin commands.

## How It Looks

When someone sends a voice message or a circle, the bot replies with:

> 🎙 **0:42** — John Doe
>
> 📝 **Transcription:**
> *(verbatim text — expandable)*
>
> 📌 **Summary:**
> *(1–3 sentences; for video notes also describes what is shown)*

While the message is being processed, the bot updates a live timer in place.

## Requirements

- Telegram Bot token from [@BotFather](https://t.me/BotFather)
- Google Gemini API key from [aistudio.google.com](https://aistudio.google.com)
- Docker + Docker Compose

## Setup

```bash
git clone https://github.com/egore4606/telegram-transcription-bot.git
cd telegram-transcription-bot
cp .env.example .env
nano .env
docker compose up -d --build
```

## Configuration

```env
TELEGRAM_TOKEN=your_telegram_bot_token
GEMINI_API_KEY=your_primary_gemini_key
GEMINI_API_KEY_2=your_backup_gemini_key
GEMINI_MODEL=gemini-3.1-flash-lite-preview
MODEL_REQUEST_TIMEOUT=45
DATABASE_PATH=/data/bot.sqlite3
ADMIN_USER_ID=123456789
RATE_LIMIT=5
```

Or use the pre-built image:

```bash
docker pull ghcr.io/egore4606/telegram-transcription-bot:latest
```

## Usage In Groups

Add the bot to your group. For it to receive all messages, either:

- make it an admin in the group, or
- disable Privacy Mode in @BotFather and re-add the bot.

## Logs

Runtime logs stay in Docker and can be backed up into local files with `save-logs.sh`.

- Backup files are written as `./logs/bot-YYYY-MM-DD.log`
- The script keeps a state file at `./logs/.save-logs-state`
- On the **first run**, it exports only the **last 24 hours** of Docker logs
- On later runs, it exports only **new log lines since the previous successful run**
- Re-running the script on the same day does not duplicate older log lines

Typical usage:

```bash
./save-logs.sh
```

## Database

The bot stores persistent state in SQLite. In Docker, the default database path is:

```text
/data/bot.sqlite3
```

Stored in the database:

- private-chat and per-group settings
- ignore/block state
- rate-limit windows
- daily and per-user stats
- processed voice/video request history
- Gemini model attempt history for each processed message
- pending feedback state
- changelog delivery records

Only media the bot actually processes is archived. Regular text chat messages are not copied into the database, except operational state needed for the bot itself, such as feedback flow and private/group context tracking.

## Database Migrations

SQLite schema changes are handled by an internal sequential migration system in `storage.py`.

- `schema_version` stores the applied schema version
- `Storage.init_db()` applies missing migrations in order
- Empty databases are created from scratch and migrated to the latest version automatically
- Existing older databases are upgraded in place

Current migration layout:

- version `1`: initial persistent bot schema
- version `2`: pending feedback state
- version `3`: changelog broadcast delivery tracking

When adding a new schema change:

1. Add a new migration SQL block or function in `storage.py`
2. Append it to the ordered migration map with the next integer version
3. Bump `LATEST_SCHEMA_VERSION`
4. Add or update tests that cover the new schema behavior

## Changelog Broadcast

Changelog broadcast is **manual by design**. It is not sent automatically on every restart.

To broadcast the current changelog:

1. Update `PUBLIC_CHANGELOG_TEXT` in `bot.py`
2. Bump `PUBLIC_CHANGELOG_VERSION` in `bot.py`
3. Run `/broadcast_changelog` from the admin account

The bot records which `PUBLIC_CHANGELOG_VERSION` was already sent to which private-chat user, so the same release is not re-sent to the same person by accident.

## Tests

Install dev dependencies:

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

Run the test suite locally without Telegram or Gemini network calls:

```bash
python -m pytest
```

The tests cover:

- Gemini response parsing and formatting
- prompt building
- feedback pending state
- stats aggregation and joins with `users`
- rate limiting
- model attempt persistence order
- settings scope separation
- SQLite migration behavior
- changelog delivery deduplication

## Tech Stack

- Python 3.12
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- [google-genai](https://pypi.org/project/google-genai/)
- SQLite
- Docker + Docker Compose

## License

MIT
