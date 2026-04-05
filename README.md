# 🎙 Telegram Transcription Bot

Telegram bot that automatically transcribes voice messages and video notes (circles) using Google Gemini API. Replies with a transcription and a summary — right in the chat, with expandable blocks.

Works in group chats and private messages. Supports forwarded voice messages.

## Features

- Transcribes **voice messages** (OGG audio)
- Transcribes **video notes** (circles) — including visual description from video
- **Four output modes** per user: full, transcription only, summary only, or one-sentence TL;DR
- **Per-user language** setting — translate output to any language
- **Fallback API key** — switches to a backup Gemini key automatically on quota limit
- **Rate limiting** — max 5 requests per user per minute
- **Admin commands** — detailed stats, ignore users in groups
- Shows voice/video **duration** in every response
- All transcriptions logged to Docker with chat name, user, timing, file size
- Daily log backup via cron to `/root/Telegram/logs/`
- Runs in **Docker** — isolated, auto-restarts on reboot

## Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | List all commands |
| `/both` | Transcription + summary *(default)* |
| `/transcription_only` | Only verbatim transcription |
| `/summary_only` | Only summary |
| `/tldr` | One sentence — the main point only |
| `/language [code]` | Set response language: `auto`, `ru`, `en`, `de`... |
| `/status` | Bot status, model, request counts |
| `/stats` | Detailed stats — admin only |
| `/myid` | Show your Telegram user ID |
| `/ignore` | Reply to a message to mute that user *(group admins only)* |

## How it looks

When someone sends a voice message or a circle, the bot replies:

> 🎙 **0:42** — John Doe
>
> 📝 **Transcription:**
> *(verbatim text — expandable)*
>
> 📌 **Summary:**
> *(1–3 sentences; for video notes also describes what's shown)*

## Requirements

- Telegram Bot token — from [@BotFather](https://t.me/BotFather)
- Google Gemini API key — free at [aistudio.google.com](https://aistudio.google.com)
- Docker + Docker Compose

## Setup

```bash
git clone https://github.com/egore4606/telegram-transcription-bot.git
cd telegram-transcription-bot
cp .env.example .env
nano .env   # fill in your tokens
docker compose up -d --build
```

## Configuration

```env
TELEGRAM_TOKEN=your_telegram_bot_token
GEMINI_API_KEY=your_primary_gemini_key
GEMINI_API_KEY_2=your_backup_gemini_key    # optional, used on quota limit
GEMINI_MODEL=gemini-3.1-flash-lite-preview # optional
ADMIN_USER_ID=123456789                    # your Telegram ID (find with /myid)
RATE_LIMIT=5                               # max requests per user per minute
```

Or pull the pre-built image:

```bash
docker pull ghcr.io/egore4606/telegram-transcription-bot:latest
```

## Usage in a group

Add the bot to your group. For it to receive all messages, either:
- Make it an **admin** in the group, or
- Disable **Privacy Mode** via @BotFather → Bot Settings → Group Privacy → Turn off (then re-add the bot)

## Logs

Transcriptions are logged to Docker with full context:

```
✅ VOICE | chat=My Group (−1001234) | user=John (123456) | duration=0:42 | size=64KB | mode=both | lang=auto | time=3.2s | text: ...
```

Daily log backups are saved to `./logs/bot-YYYY-MM-DD.log` via cron at midnight.

## Tech stack

- Python 3.12
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) (async)
- [google-genai](https://pypi.org/project/google-genai/)
- Docker + Docker Compose

## License

MIT
