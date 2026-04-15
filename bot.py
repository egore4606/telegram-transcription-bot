import asyncio
import html
import os
import logging
import time
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
# Заглушить спам от httpx (getUpdates каждые 2-3 сек)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_API_KEY_2 = os.environ.get("GEMINI_API_KEY_2")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
GEMINI_FALLBACK_MODELS = [
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]
ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "0"))
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", "5"))  # requests per minute per user
MODEL_OVERLOAD_RETRY_DELAY = 5

GEMINI_MODEL_CHAIN: list[str] = []
for model_name in [GEMINI_MODEL, *GEMINI_FALLBACK_MODELS]:
    if model_name not in GEMINI_MODEL_CHAIN:
        GEMINI_MODEL_CHAIN.append(model_name)

# Gemini clients — основной + резервный
gemini_clients = [genai.Client(api_key=GEMINI_API_KEY)]
if GEMINI_API_KEY_2:
    gemini_clients.append(genai.Client(api_key=GEMINI_API_KEY_2))

# ── In-memory state ───────────────────────────────────────────────────────────

# ("user" | "chat", id) → "both" | "transcription_only" | "summary_only" | "tldr"
mode_settings: dict[tuple[str, int], str] = {}

# ("user" | "chat", id) → "auto" | "ru" | "en" | "de" | ...
language_settings: dict[tuple[str, int], str] = {}

# user_ids которых бот игнорирует
ignored_users: set[int] = set()

# Rate limiting: user_id → [timestamp, ...]
user_request_times: dict[int, list[float]] = {}

# Статистика (сбрасывается при перезапуске)
stats: dict = {
    "voice": 0,
    "video": 0,
    "today": 0,
    "today_date": str(date.today()),
    "users": {},  # str(user_id) → count
}

# ── Prompts ───────────────────────────────────────────────────────────────────

def build_prompt(media_type: str, language: str, mode: str) -> str:
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

    if mode == "tldr":
        return f"""{task} {lang_instruction}

Напиши ОДНО короткое предложение — самую суть того, о чём говорится (и что показано, если это видео).

Ответ строго в таком формате (без маркдауна, просто текст):

КРАТКОЕ СОДЕРЖАНИЕ:
(одно предложение)"""

    return f"""{task} {lang_instruction} Выполни две задачи:

1. Транскрипция — запиши дословно всё, что было сказано.
2. Краткое содержание — в 1-3 предложениях {summary_note}.

Ответ строго в таком формате (без маркдауна, просто текст):

ТРАНСКРИПЦИЯ:
(текст)

КРАТКОЕ СОДЕРЖАНИЕ:
(текст)"""

# ── Gemini call with fallback ─────────────────────────────────────────────────

async def call_gemini(contents: list, model_name: str) -> str:
    last_error = None
    for i, client in enumerate(gemini_clients):
        try:
            response = client.models.generate_content(
                model=model_name,
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

def is_model_overloaded_error(e: Exception) -> bool:
    err_str = str(e).lower()
    return (
        "503" in str(e)
        or "status': 'unavailable'" in err_str
        or '"status": "unavailable"' in err_str
        or "high demand" in err_str
        or "currently experiencing high demand" in err_str
        or "please try again later" in err_str
    )


async def safe_edit_text(message, text: str) -> None:
    try:
        await message.edit_text(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            raise


async def show_overload_countdown(message, model_name: str) -> None:
    for seconds_left in range(MODEL_OVERLOAD_RETRY_DELAY, 0, -1):
        await safe_edit_text(
            message,
            "⚠️ <b>Модель перегружена</b>\n"
            f"<code>{html.escape(model_name)}</code>\n"
            f"Пробую снова через <b>{seconds_left}</b> сек...",
        )
        await asyncio.sleep(1)


async def call_gemini_with_retries(contents: list, processing_message) -> tuple[str, str]:
    last_error = None

    for model_idx, model_name in enumerate(GEMINI_MODEL_CHAIN):
        attempts_for_model = 2 if model_idx == 0 else 1

        for attempt in range(attempts_for_model):
            try:
                if model_idx > 0 and attempt == 0:
                    await safe_edit_text(
                        processing_message,
                        "🔄 <b>Переключаюсь на резервную модель</b>\n"
                        f"<code>{html.escape(model_name)}</code>\n"
                        "Пробую обработать сообщение снова...",
                    )

                raw = await call_gemini(contents, model_name)
                return raw, model_name
            except Exception as e:
                last_error = e

                if not is_model_overloaded_error(e):
                    raise

                logger.warning(
                    "Model overloaded | model=%s | attempt=%d/%d | error=%s",
                    model_name,
                    attempt + 1,
                    attempts_for_model,
                    e,
                )

                if model_idx == 0 and attempt == 0:
                    await show_overload_countdown(processing_message, model_name)
                    continue

                next_model_idx = model_idx + 1
                if next_model_idx < len(GEMINI_MODEL_CHAIN):
                    next_model = GEMINI_MODEL_CHAIN[next_model_idx]
                    await safe_edit_text(
                        processing_message,
                        "⚠️ <b>Модель всё ещё перегружена</b>\n"
                        f"<code>{html.escape(model_name)}</code>\n"
                        f"Переключаюсь на <code>{html.escape(next_model)}</code>...",
                    )
                    break

                raise

    raise last_error


def format_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def get_settings_scope(message) -> tuple[tuple[str, int], str]:
    if message.chat.type in ("group", "supergroup"):
        return ("chat", message.chat.id), "для этой группы"
    return ("user", message.from_user.id), "для тебя"


def check_rate_limit(user_id: int) -> bool:
    now = time.time()
    times = user_request_times.get(user_id, [])
    times = [t for t in times if now - t < 60]
    if len(times) >= RATE_LIMIT:
        user_request_times[user_id] = times
        return False
    times.append(now)
    user_request_times[user_id] = times
    return True


def format_response(raw: str, mode: str) -> str:
    raw = raw.strip()
    upper = raw.upper()

    t_idx = upper.find("ТРАНСКРИПЦИЯ:")
    s_idx = upper.find("КРАТКОЕ СОДЕРЖАНИЕ:")

    if mode == "tldr":
        if s_idx != -1:
            summary = raw[s_idx + len("КРАТКОЕ СОДЕРЖАНИЕ:"):].strip()
        else:
            summary = raw
        return f"💡 {html.escape(summary)}"

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
    if is_model_overloaded_error(e):
        tried_models = " → ".join(GEMINI_MODEL_CHAIN)
        return (
            "⏳ Все доступные модели Gemini сейчас перегружены.\n"
            f"Пробовал по очереди: <code>{html.escape(tried_models)}</code>\n"
            "Попробуй ещё раз чуть позже."
        )
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
        "Настройки в личке и в каждой группе хранятся отдельно.\n\n"
        "<b>Режим вывода:</b>\n"
        "/both — транскрипция + саммари <i>(по умолчанию)</i>\n"
        "/transcription_only — только транскрипция\n"
        "/summary_only — только краткое содержание\n"
        "/tldr — одно предложение, самая суть\n\n"
        "<b>Язык ответа:</b>\n"
        "/language auto — язык оригинала <i>(по умолчанию)</i>\n"
        "/language ru | en | de | ... — перевести\n\n"
        "<b>Прочее:</b>\n"
        "/myid — узнать свой Telegram ID\n",
        parse_mode=ParseMode.HTML,
    )


async def handle_myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    name = update.effective_user.full_name
    await update.message.reply_text(f"👤 <b>{html.escape(name)}</b>\nTelegram ID: <code>{uid}</code>", parse_mode=ParseMode.HTML)


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Эта команда только для администратора.")
        return

    today = str(date.today())
    today_count = stats["today"] if stats["today_date"] == today else 0
    backup = "✅ подключён" if GEMINI_API_KEY_2 else "❌ не настроен"

    top_users = sorted(stats["users"].items(), key=lambda x: x[1], reverse=True)[:5]
    top_text = "\n".join(f"  <code>{uid}</code>: {cnt}" for uid, cnt in top_users) or "  нет данных"

    blocked_text = "\n".join(f"  <code>{uid}</code>" for uid in ignored_users) or "  нет"

    await update.message.reply_text(
        f"🤖 <b>Статус и статистика</b>\n\n"
        f"<b>Система:</b>\n"
        f"  Модели: <code>{html.escape(' -> '.join(GEMINI_MODEL_CHAIN))}</code>\n"
        f"  Резервный ключ: {backup}\n\n"
        f"<b>Запросы:</b>\n"
        f"  Сегодня: <b>{today_count}</b>\n"
        f"  Голосовых всего: <b>{stats['voice']}</b>\n"
        f"  Кружочков всего: <b>{stats['video']}</b>\n\n"
        f"<b>Топ пользователей:</b>\n{top_text}\n\n"
        f"<b>Заблокированы:</b>\n{blocked_text}",
        parse_mode=ParseMode.HTML,
    )


async def handle_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope_key, scope_label = get_settings_scope(update.message)

    if not context.args:
        current = language_settings.get(scope_key, "auto")
        await update.message.reply_text(
            f"Текущий язык {scope_label}: <code>{current}</code>\n\n"
            "Использование: /language auto | ru | en | de | ...",
            parse_mode=ParseMode.HTML,
        )
        return

    lang = context.args[0].lower()
    language_settings[scope_key] = lang
    label = "язык оригинала" if lang == "auto" else lang
    await update.message.reply_text(
        f"✅ Язык ответа {scope_label}: <b>{html.escape(label)}</b>",
        parse_mode=ParseMode.HTML,
    )


async def handle_transcription_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope_key, scope_label = get_settings_scope(update.message)
    mode_settings[scope_key] = "transcription_only"
    await update.message.reply_text(
        f"✅ Режим {scope_label}: только <b>транскрипция</b>",
        parse_mode=ParseMode.HTML,
    )


async def handle_summary_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope_key, scope_label = get_settings_scope(update.message)
    mode_settings[scope_key] = "summary_only"
    await update.message.reply_text(
        f"✅ Режим {scope_label}: только <b>краткое содержание</b>",
        parse_mode=ParseMode.HTML,
    )


async def handle_tldr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope_key, scope_label = get_settings_scope(update.message)
    mode_settings[scope_key] = "tldr"
    await update.message.reply_text(
        f"✅ Режим {scope_label}: <b>только главное</b> (одно предложение)",
        parse_mode=ParseMode.HTML,
    )


async def handle_both(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope_key, scope_label = get_settings_scope(update.message)
    mode_settings[scope_key] = "both"
    await update.message.reply_text(
        f"✅ Режим {scope_label}: <b>транскрипция + саммари</b>",
        parse_mode=ParseMode.HTML,
    )


async def handle_block(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Эта команда только для администратора.")
        return

    if not context.args:
        await update.message.reply_text(
            "Использование: /block <code>user_id</code>\n"
            "Узнать ID пользователя: попроси его написать /myid",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный ID. Должно быть число.")
        return

    if target_id == ADMIN_USER_ID:
        await update.message.reply_text("❌ Нельзя заблокировать самого себя.")
        return

    ignored_users.add(target_id)
    logger.info("ADMIN BLOCK | admin=%d blocked user=%d", update.effective_user.id, target_id)
    await update.message.reply_text(f"🚫 Пользователь <code>{target_id}</code> заблокирован.", parse_mode=ParseMode.HTML)


async def handle_unblock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Эта команда только для администратора.")
        return

    if not context.args:
        blocked = "\n".join(f"  <code>{uid}</code>" for uid in ignored_users) or "  никого нет"
        await update.message.reply_text(
            f"Использование: /unblock <code>user_id</code>\n\n"
            f"<b>Сейчас заблокированы:</b>\n{blocked}",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный ID. Должно быть число.")
        return

    if target_id in ignored_users:
        ignored_users.discard(target_id)
        logger.info("ADMIN UNBLOCK | admin=%d unblocked user=%d", update.effective_user.id, target_id)
        await update.message.reply_text(f"✅ Пользователь <code>{target_id}</code> разблокирован.", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(f"ℹ️ Пользователь <code>{target_id}</code> не был заблокирован.", parse_mode=ParseMode.HTML)


async def handle_ignore(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message

    if message.chat.type not in ("group", "supergroup"):
        await message.reply_text("⚠️ Эта команда работает только в группах.")
        return

    member = await message.chat.get_member(message.from_user.id)
    if member.status not in ("administrator", "creator"):
        await message.reply_text("⛔ Эта команда только для администраторов группы.")
        return

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
    user_name = message.from_user.full_name

    if user_id in ignored_users:
        return

    if not check_rate_limit(user_id):
        await message.reply_text("⏳ Слишком много запросов. Подожди минуту.")
        return

    duration = message.voice.duration
    duration_str = format_duration(duration)
    processing = await message.reply_text(f"🎙 Слушаю голосовое ({duration_str})...")

    chat_title = message.chat.title or "личка"
    chat_id = message.chat.id
    t_start = time.monotonic()

    try:
        file = await context.bot.get_file(message.voice.file_id)
        data = await file.download_as_bytearray()
        file_size_kb = len(data) // 1024

        scope_key, _ = get_settings_scope(message)
        mode = mode_settings.get(scope_key, "both")
        language = language_settings.get(scope_key, "auto")
        prompt = build_prompt("voice", language, mode)

        raw, model_used = await call_gemini_with_retries([
            types.Content(parts=[
                types.Part.from_bytes(data=bytes(data), mime_type="audio/ogg"),
                types.Part.from_text(text=prompt),
            ])
        ], processing)

        elapsed = time.monotonic() - t_start
        update_stats(user_id, "voice")
        header = f"🎙 <b>{duration_str}</b> — {html.escape(user_name)}\n\n"
        await safe_edit_text(processing, header + format_response(raw, mode))

        logger.info(
            "✅ VOICE | chat=%s (%d) | user=%s (%d) | duration=%s | size=%dKB | mode=%s | lang=%s | model=%s | time=%.1fs | text: %s",
            chat_title, chat_id, user_name, user_id, duration_str, file_size_kb, mode, language, model_used, elapsed,
            raw.replace("\n", " ")[:300]
        )

    except Exception as e:
        elapsed = time.monotonic() - t_start
        logger.error("❌ VOICE ERROR | chat=%s (%d) | user=%s (%d) | time=%.1fs | error: %s",
                     chat_title, chat_id, user_name, user_id, elapsed, e)
        await safe_edit_text(processing, friendly_error(e))


async def handle_video_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user_id = message.from_user.id
    user_name = message.from_user.full_name

    if user_id in ignored_users:
        return

    if not check_rate_limit(user_id):
        await message.reply_text("⏳ Слишком много запросов. Подожди минуту.")
        return

    duration = message.video_note.duration
    duration_str = format_duration(duration)
    processing = await message.reply_text(f"🔵 Смотрю кружочек ({duration_str})...")

    chat_title = message.chat.title or "личка"
    chat_id = message.chat.id
    t_start = time.monotonic()

    try:
        file = await context.bot.get_file(message.video_note.file_id)
        data = await file.download_as_bytearray()
        file_size_kb = len(data) // 1024

        scope_key, _ = get_settings_scope(message)
        mode = mode_settings.get(scope_key, "both")
        language = language_settings.get(scope_key, "auto")
        prompt = build_prompt("video", language, mode)

        raw, model_used = await call_gemini_with_retries([
            types.Content(parts=[
                types.Part.from_bytes(data=bytes(data), mime_type="video/mp4"),
                types.Part.from_text(text=prompt),
            ])
        ], processing)

        elapsed = time.monotonic() - t_start
        update_stats(user_id, "video")
        header = f"🔵 <b>{duration_str}</b> — {html.escape(user_name)}\n\n"
        await safe_edit_text(processing, header + format_response(raw, mode))

        logger.info(
            "✅ VIDEO | chat=%s (%d) | user=%s (%d) | duration=%s | size=%dKB | mode=%s | lang=%s | model=%s | time=%.1fs | text: %s",
            chat_title, chat_id, user_name, user_id, duration_str, file_size_kb, mode, language, model_used, elapsed,
            raw.replace("\n", " ")[:300]
        )

    except Exception as e:
        elapsed = time.monotonic() - t_start
        logger.error("❌ VIDEO ERROR | chat=%s (%d) | user=%s (%d) | time=%.1fs | error: %s",
                     chat_title, chat_id, user_name, user_id, elapsed, e)
        await safe_edit_text(processing, friendly_error(e))

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("myid", handle_myid))
    app.add_handler(CommandHandler("stats", handle_stats))
    app.add_handler(CommandHandler("block", handle_block))
    app.add_handler(CommandHandler("unblock", handle_unblock))
    app.add_handler(CommandHandler("language", handle_language))
    app.add_handler(CommandHandler("transcription_only", handle_transcription_only))
    app.add_handler(CommandHandler("summary_only", handle_summary_only))
    app.add_handler(CommandHandler("tldr", handle_tldr))
    app.add_handler(CommandHandler("both", handle_both))
    app.add_handler(CommandHandler("ignore", handle_ignore))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.VIDEO_NOTE, handle_video_note))

    logger.info(
        "Bot started (models: %s, backup key: %s)",
        " -> ".join(GEMINI_MODEL_CHAIN),
        "yes" if GEMINI_API_KEY_2 else "no",
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
