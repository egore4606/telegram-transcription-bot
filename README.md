# 🎙 Telegram Transcription Bot

Telegram bot that automatically transcribes voice messages and video notes (circles) using Google Gemini API. Replies with a full transcription and a brief summary — right in the chat.

## Features

- Transcribes **voice messages** (OGG audio)
- Transcribes **video notes** (circles/кружочки) — including visual description
- Sends back two collapsible blocks: transcription + summary
- Works in **group chats** and **private messages**
- Powered by **Google Gemini** (multimodal, free tier)
- Runs in **Docker** — isolated, auto-restarts on reboot

## How it looks

When someone sends a voice message or a circle, the bot replies:

> 📝 **Transcription:**
> *(verbatim text of what was said)*
>
> 📌 **Summary:**
> *(1–3 sentence summary; for video notes also describes what's shown)*

## Requirements

- Telegram Bot token (from [@BotFather](https://t.me/BotFather))
- Google Gemini API key (free at [aistudio.google.com](https://aistudio.google.com))
- Docker + Docker Compose

## Setup

```bash
git clone https://github.com/egore4606/telegram-transcription-bot.git
cd telegram-transcription-bot
cp .env.example .env
nano .env   # fill in your TELEGRAM_TOKEN and GEMINI_API_KEY
docker compose up -d --build
```

## Configuration

Edit `.env`:

```env
TELEGRAM_TOKEN=your_telegram_bot_token
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.1-flash-lite-preview   # optional, this is the default
```

## Usage in a group

Add the bot to your group. For it to receive all messages, either:
- Make it an **admin** in the group, or
- Disable **Privacy Mode** via @BotFather → Bot Settings → Group Privacy → Turn off (then re-add the bot)

## Tech stack

- Python 3.12
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) (async)
- [google-genai](https://pypi.org/project/google-genai/)
- Docker + Docker Compose

## License

MIT
