import html
import os
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from google.genai import types

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite-preview-06-17")

gemini = genai.Client(api_key=GEMINI_API_KEY)

PROMPT_VOICE = """Это голосовое сообщение из Telegram. Выполни две задачи:

1. Транскрипция — запиши дословно всё, что было сказано. Сохраняй язык оригинала.
2. Краткое содержание — в 1-3 предложениях опиши суть сказанного.

Ответ строго в таком формате (без заголовков, без маркдауна, просто текст):

ТРАНСКРИПЦИЯ:
(текст)

КРАТКОЕ СОДЕРЖАНИЕ:
(текст)"""

PROMPT_VIDEO = """Это видео-кружочек (video note) из Telegram. Выполни две задачи:

1. Транскрипция — запиши дословно всё, что было сказано. Сохраняй язык оригинала.
2. Краткое содержание — в 1-3 предложениях опиши суть сказанного И то, что происходит на видео (что видно, что показывают).

Ответ строго в таком формате (без заголовков, без маркдауна, просто текст):

ТРАНСКРИПЦИЯ:
(текст)

КРАТКОЕ СОДЕРЖАНИЕ:
(текст)"""


def format_response(raw: str) -> str:
    """Parse Gemini response and format as HTML with expandable blockquotes."""
    transcription = ""
    summary = ""

    raw = raw.strip()

    # Split by known markers
    upper = raw.upper()
    t_idx = upper.find("ТРАНСКРИПЦИЯ:")
    s_idx = upper.find("КРАТКОЕ СОДЕРЖАНИЕ:")

    if t_idx != -1 and s_idx != -1:
        transcription = raw[t_idx + len("ТРАНСКРИПЦИЯ:"):s_idx].strip()
        summary = raw[s_idx + len("КРАТКОЕ СОДЕРЖАНИЕ:"):].strip()
    else:
        # Fallback: just put everything in transcription
        transcription = raw
        summary = ""

    transcription = html.escape(transcription)
    summary = html.escape(summary)

    parts = [f"📝 <b>Транскрипция:</b>\n<blockquote expandable>{transcription}</blockquote>"]
    if summary:
        parts.append(f"\n📌 <b>Краткое содержание:</b>\n<blockquote expandable>{summary}</blockquote>")

    return "\n".join(parts)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Привет! Я бот для расшифровки голосовых сообщений и кружочков.\n\n"
        "Просто отправь мне 🎙 голосовое или 🔵 кружочек — я:\n"
        "• переведу речь в текст (транскрипция)\n"
        "• сделаю краткое содержание\n"
        "• для кружочков учту и то, что видно на видео\n\n"
        "Работаю в личных сообщениях и в группах.",
    )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message

    processing = await message.reply_text("🎙 Слушаю голосовое...")

    try:
        file = await context.bot.get_file(message.voice.file_id)
        data = await file.download_as_bytearray()

        response = gemini.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Content(
                    parts=[
                        types.Part.from_bytes(data=bytes(data), mime_type="audio/ogg"),
                        types.Part.from_text(text=PROMPT_VOICE),
                    ]
                )
            ],
        )

        await processing.edit_text(format_response(response.text), parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error("Voice processing error: %s", e)
        await processing.edit_text(f"❌ Не удалось обработать голосовое.\nОшибка: {e}")


async def handle_video_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message

    processing = await message.reply_text("🔵 Смотрю кружочек...")

    try:
        file = await context.bot.get_file(message.video_note.file_id)
        data = await file.download_as_bytearray()

        response = gemini.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Content(
                    parts=[
                        types.Part.from_bytes(data=bytes(data), mime_type="video/mp4"),
                        types.Part.from_text(text=PROMPT_VIDEO),
                    ]
                )
            ],
        )

        await processing.edit_text(format_response(response.text), parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error("Video note processing error: %s", e)
        await processing.edit_text(f"❌ Не удалось обработать кружочек.\nОшибка: {e}")


def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.VIDEO_NOTE, handle_video_note))

    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
