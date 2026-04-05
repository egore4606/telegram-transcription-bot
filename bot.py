import html
import os
import logging
from datetime import date

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

# ── Config ────────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_API_KEY_2 = os.environ.get("GEMINI_API_KEY_2")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "0"))

# Gemini clients — основной + резервный
gemini_clients = [genai.Client(api_key=GEMINI_API_KEY)]
if GEMINI_API_KEY_2:
    gemini_clients.append(genai.Client(api_key=GEMINI_API_KEY_2))

# ── In-memory state ───────────────────────────────────────────────────────────

# user_id → "both" | "transcription_only" | "summary_only"
user_modes: dict[int, str] = {}

# user_id → "auto" | "ru" | "en" | "de" | ...
user_languages: dict[int, str] = {}

# user_ids которых бот игнорирует
ignored_users: set[int] = set()

# Статистика (сбрасывается при перезапуске)
stats: dict = {
    "voice": 0,
    "video": 0,
    "today": 0,
    "today_date": str(date.today()),
    "users": {},  # str(user_id) → count
}

# ── Prompts ───────────────────────────────────────────────────────────────────

def build_prompt(media_type: str, language: str) -> str:
    if media_type == "voice":
        task = "Это голосовое сообщение из Telegram."
        summary_note = "опиши суть сказанного"
    else:
        task = "Это видео-кружочек (video note) из Telegram."
        summary_note = "опиши суть сказанного И то, что происходит на видео (что видно, что показывают)"

    if language == "auto":
        lang_instruction = "Сохраняй язык оригинала."
    else:
        lang_instruction = f"Переведи ответ на язык: {language}."

    return f"""{task} {lang_instruction} Выполни две задачи:

1. Транскрипция — запиши дословно всё, что было сказано.
2. Краткое содержание — в 1-3 предложениях {summary_note}.

Ответ строго в таком формате (без маркдауна, просто текст):

ТРАНСКРИПЦИЯ:
(текст)

КРАТКОЕ СОДЕРЖАНИЕ:
(текст)"""

# ── Gemini call with fallback ─────────────────────────────────────────────────

async def call_gemini(contents: list) -> str:
    last_error = None
    for i, client in enumerate(gemini_clients):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
            )
            return response.text
        except Exception as e:
            err_str = str(e).lower()
            is_quota = "429" in str(e) or "quota" in err_str or "rate" in err_str or "resource_exhausted" in err_str
            if is_quota and i < len(gemini_clients) - 1:
                logger.warning("Client %d quota exceeded, switching to backup key", i + 1)
                last_error = e
                continue
            last_error = e
            break
    raise last_error

# ── Helpers ───────────────────────────────────────────────────────────────────

def format_response(raw: str, mode: str) -> str:
    raw = raw.strip()
    upper = raw.upper()

    t_idx = upper.find("ТРАНСКРИПЦИЯ:")
    s_idx = upper.find("КРАТКОЕ СОДЕРЖАНИЕ:")

    if t_idx != -1 and s_idx != -1:
        transcription = raw[t_idx + len("ТРАНСКРИПЦИЯ:"):s_idx].strip()
        summary = raw[s_idx + len("КРАТКОЕ СОДЕРЖАНИЕ:"):].strip()
    else:
        transcription = raw
        summary = ""

    parts = []
    if mode in ("both", "transcription_only"):
        parts.append(f"📝 <b>Транскрипция:</b>\n<blockquote expandable>{html.escape(transcription)}</blockquote>")
    if mode in ("both", "summary_only") and summary:
        parts.append(f"📌 <b>Краткое содержание:</b>\n<blockquote expandable>{html.escape(summary)}</blockquote>")

    return "\n\n".join(parts) if parts else html.escape(transcription)


def friendly_error(e: Exception) -> str:
    err_str = str(e).lower()
    if "429" in str(e) or "quota" in err_str or "resource_exhausted" in err_str:
        return "⏳ Превышен лимит запросов к Gemini. Оба ключа исчерпаны. Попробуй через минуту."
    if "too large" in err_str or "file_too_large" in err_str or "size" in err_str:
        return "❌ Файл слишком большой (макс. 20 МБ)."
    if "invalid" in err_str or "unsupported" in err_str:
        return "❌ Формат файла не поддерживается."
    return f"⚠️ Что-то пошло не так. Попробуй ещё раз.\n<code>{html.escape(str(e)[:200])}</code>"


def update_stats(user_id: int, media_type: str) -> None:
    today = str(date.today())
    if stats["today_date"] != today:
        stats["today"] = 0
        stats["today_date"] = today

    stats[media_type] += 1
    stats["today"] += 1
    uid = str(user_id)
    stats["users"][uid] = stats["users"].get(uid, 0) + 1


def is_admin(user_id: int) -> bool:
    return ADMIN_USER_ID != 0 and user_id == ADMIN_USER_ID

# ── Command handlers ──────────────────────────────────────────────────────────

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Привет! Я бот для расшифровки голосовых сообщений и кружочков.\n\n"
        "Просто отправь мне 🎙 голосовое или 🔵 кружочек — я:\n"
        "• переведу речь в текст\n"
        "• сделаю краткое содержание\n"
        "• для кружочков учту и видеоряд\n\n"
        "Используй /help для списка команд."
    )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>Команды:</b>\n\n"
        "🎙 Просто отправь голосовое или кружочек — бот расшифрует\n\n"
        "<b>Режим вывода:</b>\n"
        "/both — показывать транскрипцию и саммари <i>(по умолчанию)</i>\n"
        "/transcription_only — только транскрипция\n"
        "/summary_only — только краткое содержание\n\n"
        "<b>Язык ответа:</b>\n"
        "/language auto — язык оригинала <i>(по умолчанию)</i>\n"
        "/language ru — перевести на русский\n"
        "/language en — перевести на английский\n\n"
        "<b>Прочее:</b>\n"
        "/status — состояние бота\n"
        "/myid — узнать свой Telegram ID\n",
        parse_mode=ParseMode.HTML,
    )


async def handle_myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    name = update.effective_user.full_name
    await update.message.reply_text(f"👤 <b>{html.escape(name)}</b>\nTelegram ID: <code>{uid}</code>", parse_mode=ParseMode.HTML)


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = str(date.today())
    if stats["today_date"] != today:
        today_count = 0
    else:
        today_count = stats["today"]

    backup = "✅ подключён" if GEMINI_API_KEY_2 else "❌ не настроен"
    await update.message.reply_text(
        f"✅ <b>Бот работает</b>\n\n"
        f"🤖 Модель: <code>{GEMINI_MODEL}</code>\n"
        f"🔑 Резервный ключ: {backup}\n"
        f"📊 Запросов сегодня: <b>{today_count}</b>\n"
        f"📊 Всего голосовых: <b>{stats['voice']}</b>\n"
        f"📊 Всего кружочков: <b>{stats['video']}</b>",
        parse_mode=ParseMode.HTML,
    )


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Эта команда только для администратора.")
        return

    top_users = sorted(stats["users"].items(), key=lambda x: x[1], reverse=True)[:5]
    top_text = "\n".join(f"  <code>{uid}</code>: {cnt}" for uid, cnt in top_users) or "  нет данных"

    await update.message.reply_text(
        f"📊 <b>Статистика</b>\n\n"
        f"🎙 Голосовых: <b>{stats['voice']}</b>\n"
        f"🔵 Кружочков: <b>{stats['video']}</b>\n"
        f"📅 Сегодня: <b>{stats['today']}</b>\n\n"
        f"👥 Топ пользователей:\n{top_text}",
        parse_mode=ParseMode.HTML,
    )


async def handle_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if not context.args:
        current = user_languages.get(uid, "auto")
        await update.message.reply_text(
            f"Текущий язык: <code>{current}</code>\n\n"
            "Использование: /language auto | ru | en | de | ...",
            parse_mode=ParseMode.HTML,
        )
        return

    lang = context.args[0].lower()
    user_languages[uid] = lang
    label = "язык оригинала" if lang == "auto" else lang
    await update.message.reply_text(f"✅ Язык ответа: <b>{html.escape(label)}</b>", parse_mode=ParseMode.HTML)


async def handle_transcription_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_modes[update.effective_user.id] = "transcription_only"
    await update.message.reply_text("✅ Режим: только <b>транскрипция</b>", parse_mode=ParseMode.HTML)


async def handle_summary_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_modes[update.effective_user.id] = "summary_only"
    await update.message.reply_text("✅ Режим: только <b>краткое содержание</b>", parse_mode=ParseMode.HTML)


async def handle_both(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_modes[update.effective_user.id] = "both"
    await update.message.reply_text("✅ Режим: <b>транскрипция + саммари</b>", parse_mode=ParseMode.HTML)


async def handle_ignore(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message

    # Только в группах
    if message.chat.type not in ("group", "supergroup"):
        await message.reply_text("⚠️ Эта команда работает только в группах.")
        return

    # Проверяем что вызывающий — админ группы
    member = await message.chat.get_member(message.from_user.id)
    if member.status not in ("administrator", "creator"):
        await message.reply_text("⛔ Эта команда только для администраторов группы.")
        return

    # Должно быть реплаем на чьё-то сообщение
    if not message.reply_to_message:
        await message.reply_text("ℹ️ Ответь на сообщение пользователя командой /ignore, чтобы его заблокировать.")
        return

    target = message.reply_to_message.from_user
    if target.id in ignored_users:
        ignored_users.discard(target.id)
        await message.reply_text(f"✅ Пользователь <b>{html.escape(target.full_name)}</b> снова будет обрабатываться.", parse_mode=ParseMode.HTML)
    else:
        ignored_users.add(target.id)
        await message.reply_text(f"🚫 Сообщения от <b>{html.escape(target.full_name)}</b> теперь игнорируются.", parse_mode=ParseMode.HTML)

# ── Media handlers ────────────────────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user_id = message.from_user.id

    if user_id in ignored_users:
        return

    processing = await message.reply_text("🎙 Слушаю голосовое...")

    try:
        file = await context.bot.get_file(message.voice.file_id)
        data = await file.download_as_bytearray()

        mode = user_modes.get(user_id, "both")
        language = user_languages.get(user_id, "auto")
        prompt = build_prompt("voice", language)

        raw = await call_gemini([
            types.Content(parts=[
                types.Part.from_bytes(data=bytes(data), mime_type="audio/ogg"),
                types.Part.from_text(text=prompt),
            ])
        ])

        update_stats(user_id, "voice")
        await processing.edit_text(format_response(raw, mode), parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error("Voice error: %s", e)
        await processing.edit_text(friendly_error(e), parse_mode=ParseMode.HTML)


async def handle_video_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user_id = message.from_user.id

    if user_id in ignored_users:
        return

    processing = await message.reply_text("🔵 Смотрю кружочек...")

    try:
        file = await context.bot.get_file(message.video_note.file_id)
        data = await file.download_as_bytearray()

        mode = user_modes.get(user_id, "both")
        language = user_languages.get(user_id, "auto")
        prompt = build_prompt("video", language)

        raw = await call_gemini([
            types.Content(parts=[
                types.Part.from_bytes(data=bytes(data), mime_type="video/mp4"),
                types.Part.from_text(text=prompt),
            ])
        ])

        update_stats(user_id, "video")
        await processing.edit_text(format_response(raw, mode), parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error("Video note error: %s", e)
        await processing.edit_text(friendly_error(e), parse_mode=ParseMode.HTML)

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("myid", handle_myid))
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler("stats", handle_stats))
    app.add_handler(CommandHandler("language", handle_language))
    app.add_handler(CommandHandler("transcription_only", handle_transcription_only))
    app.add_handler(CommandHandler("summary_only", handle_summary_only))
    app.add_handler(CommandHandler("both", handle_both))
    app.add_handler(CommandHandler("ignore", handle_ignore))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.VIDEO_NOTE, handle_video_note))

    logger.info("Bot started (model: %s, backup key: %s)", GEMINI_MODEL, "yes" if GEMINI_API_KEY_2 else "no")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
