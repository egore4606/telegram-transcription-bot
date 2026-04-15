import asyncio
import html
import logging
import os
import time

from google import genai
from google.genai import types
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from storage import Storage, utc_now


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
DATABASE_PATH = os.environ.get("DATABASE_PATH", "/data/bot.sqlite3")
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

STORAGE = Storage(DATABASE_PATH)

PUBLIC_CHANGELOG_TEXT = """🆕 <b>Что нового в боте</b>

Вот что стало лучше:
- если Gemini временно перегружен, бот теперь обычно не падает с ошибкой, а сам ждёт, пробует снова и при необходимости переключается на резервные модели;
- режим ответа и язык теперь можно настраивать отдельно в личке и в каждой группе;
- настройки, статистика и история обработанных голосовых и кружочков теперь не пропадают после перезапуска бота;
- появилась команда <code>/feedback</code> — можно быстро отправить пожелание или сообщить о проблеме;
- появилась команда <code>/changelog</code> — можно в любой момент посмотреть последние изменения.

Если заметишь что-то странное в работе бота, отправь <code>/feedback твой текст</code>."""

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


# ── Helpers ───────────────────────────────────────────────────────────────────


def is_quota_error(error: Exception) -> bool:
    err_str = str(error).lower()
    return (
        "429" in str(error)
        or "quota" in err_str
        or "rate" in err_str
        or "resource_exhausted" in err_str
    )


def is_model_overloaded_error(error: Exception) -> bool:
    err_str = str(error).lower()
    return (
        "503" in str(error)
        or "status': 'unavailable'" in err_str
        or '"status": "unavailable"' in err_str
        or "high demand" in err_str
        or "currently experiencing high demand" in err_str
        or "please try again later" in err_str
    )


def extract_error_code(error: Exception) -> str:
    err_str = str(error).lower()
    if is_model_overloaded_error(error):
        return "model_overloaded"
    if is_quota_error(error):
        return "quota_exhausted"
    if "too large" in err_str or "file_too_large" in err_str or "size" in err_str:
        return "file_too_large"
    if "invalid" in err_str or "unsupported" in err_str:
        return "invalid_media"
    return "unknown_error"


def shorten_error(error: Exception, limit: int = 1000) -> str:
    return str(error).strip()[:limit]


def format_duration(seconds: int) -> str:
    minutes, remaining_seconds = divmod(seconds, 60)
    return f"{minutes}:{remaining_seconds:02d}"


def get_settings_scope(message) -> tuple[tuple[str, int], str]:
    if message.chat.type in ("group", "supergroup"):
        return ("chat", message.chat.id), "для этой группы"
    return ("user", message.from_user.id), "для тебя"


def parse_response_sections(raw: str, mode: str) -> tuple[str, str]:
    raw = raw.strip()
    upper = raw.upper()

    transcription_idx = upper.find("ТРАНСКРИПЦИЯ:")
    summary_idx = upper.find("КРАТКОЕ СОДЕРЖАНИЕ:")

    if mode == "tldr":
        if summary_idx != -1:
            return "", raw[summary_idx + len("КРАТКОЕ СОДЕРЖАНИЕ:"):].strip()
        return "", raw

    if transcription_idx != -1 and summary_idx != -1:
        transcription = raw[transcription_idx + len("ТРАНСКРИПЦИЯ:"):summary_idx].strip()
        summary = raw[summary_idx + len("КРАТКОЕ СОДЕРЖАНИЕ:"):].strip()
        return transcription, summary

    return raw, ""


def format_response(raw: str, mode: str) -> str:
    transcription, summary = parse_response_sections(raw, mode)

    if mode == "tldr":
        return f"💡 {html.escape(summary)}"

    parts = []
    if mode in ("both", "transcription_only") and transcription:
        parts.append(f"📝 <b>Транскрипция:</b>\n<blockquote expandable>{html.escape(transcription)}</blockquote>")
    if mode in ("both", "summary_only") and summary:
        parts.append(f"📌 <b>Краткое содержание:</b>\n<blockquote expandable>{html.escape(summary)}</blockquote>")

    return "\n\n".join(parts) if parts else html.escape(transcription)


def build_final_reply(media_emoji: str, duration_str: str, user_name: str, raw: str, mode: str) -> str:
    header = f"{media_emoji} <b>{duration_str}</b> — {html.escape(user_name)}\n\n"
    return header + format_response(raw, mode)


def friendly_error(error: Exception) -> str:
    err_str = str(error).lower()
    if is_model_overloaded_error(error):
        tried_models = " → ".join(GEMINI_MODEL_CHAIN)
        return (
            "⏳ Все доступные модели Gemini сейчас перегружены.\n"
            f"Пробовал по очереди: <code>{html.escape(tried_models)}</code>\n"
            "Попробуй ещё раз чуть позже."
        )
    if is_quota_error(error):
        return "⏳ Превышен лимит запросов к Gemini. Оба ключа исчерпаны. Попробуй через минуту."
    if "too large" in err_str or "file_too_large" in err_str or "size" in err_str:
        return "❌ Файл слишком большой (макс. 20 МБ)."
    if "invalid" in err_str or "unsupported" in err_str:
        return "❌ Формат файла не поддерживается."
    return f"⚠️ Что-то пошло не так. Попробуй ещё раз.\n<code>{html.escape(str(error)[:200])}</code>"


def is_admin(user_id: int) -> bool:
    return ADMIN_USER_ID != 0 and user_id == ADMIN_USER_ID


def get_chat_title(message) -> str:
    return message.chat.title or getattr(message.chat, "full_name", None) or "личка"


def get_media_metadata(message, media_type: str) -> dict[str, object]:
    if media_type == "voice":
        media = message.voice
        return {
            "media": media,
            "emoji": "🎙",
            "mime_type": "audio/ogg",
            "progress_text": f"🎙 Слушаю голосовое ({format_duration(media.duration)})...",
        }

    media = message.video_note
    return {
        "media": media,
        "emoji": "🔵",
        "mime_type": "video/mp4",
        "progress_text": f"🔵 Смотрю кружочек ({format_duration(media.duration)})...",
    }


def models_tried_text(run_meta: dict[str, object]) -> str:
    models = run_meta.get("models_tried", [])
    if not isinstance(models, list) or not models:
        return ""
    return " -> ".join(models)


async def safe_edit_text(message, text: str) -> None:
    try:
        await message.edit_text(text, parse_mode=ParseMode.HTML)
    except Exception as error:
        if "message is not modified" not in str(error).lower():
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


# ── Gemini call with fallback ─────────────────────────────────────────────────


async def call_gemini(
    contents: list,
    model_name: str,
    message_processing_id: int,
    run_meta: dict[str, object],
) -> str:
    last_error = None

    for client_index, client in enumerate(gemini_clients):
        api_key_slot = "primary" if client_index == 0 else "backup"
        attempt_no = int(run_meta["attempt_no"])
        started_at = utc_now()

        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
            )
            completed_at = utc_now()
            STORAGE.add_model_attempt(
                message_processing_id=message_processing_id,
                attempt_no=attempt_no,
                model_name=model_name,
                api_key_slot=api_key_slot,
                status="success",
                started_at=started_at,
                completed_at=completed_at,
            )
            run_meta["attempt_no"] = attempt_no + 1
            if client_index > 0:
                run_meta["fallback_key_used"] = True
            return response.text
        except Exception as error:
            completed_at = utc_now()
            STORAGE.add_model_attempt(
                message_processing_id=message_processing_id,
                attempt_no=attempt_no,
                model_name=model_name,
                api_key_slot=api_key_slot,
                status="error",
                started_at=started_at,
                completed_at=completed_at,
                error_text=shorten_error(error),
            )
            run_meta["attempt_no"] = attempt_no + 1
            if client_index > 0:
                run_meta["fallback_key_used"] = True

            if is_quota_error(error) and client_index < len(gemini_clients) - 1:
                logger.warning("Client %d quota exceeded, switching to backup key", client_index + 1)
                last_error = error
                continue

            last_error = error
            break

    raise last_error


async def call_gemini_with_retries(
    contents: list,
    processing_message,
    message_processing_id: int,
    run_meta: dict[str, object],
) -> tuple[str, str]:
    last_error = None

    for model_index, model_name in enumerate(GEMINI_MODEL_CHAIN):
        attempts_for_model = 2 if model_index == 0 else 1

        for attempt in range(attempts_for_model):
            models = run_meta.setdefault("models_tried", [])
            if isinstance(models, list):
                models.append(model_name)

            try:
                if model_index > 0 and attempt == 0:
                    await safe_edit_text(
                        processing_message,
                        "🔄 <b>Переключаюсь на резервную модель</b>\n"
                        f"<code>{html.escape(model_name)}</code>\n"
                        "Пробую обработать сообщение снова...",
                    )

                raw = await call_gemini(contents, model_name, message_processing_id, run_meta)
                return raw, model_name
            except Exception as error:
                last_error = error

                if not is_model_overloaded_error(error):
                    raise

                logger.warning(
                    "Model overloaded | model=%s | attempt=%d/%d | error=%s",
                    model_name,
                    attempt + 1,
                    attempts_for_model,
                    error,
                )

                if model_index == 0 and attempt == 0:
                    await show_overload_countdown(processing_message, model_name)
                    continue

                next_model_index = model_index + 1
                if next_model_index < len(GEMINI_MODEL_CHAIN):
                    next_model = GEMINI_MODEL_CHAIN[next_model_index]
                    await safe_edit_text(
                        processing_message,
                        "⚠️ <b>Модель всё ещё перегружена</b>\n"
                        f"<code>{html.escape(model_name)}</code>\n"
                        f"Переключаюсь на <code>{html.escape(next_model)}</code>...",
                    )
                    break

                raise

    raise last_error


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
        "/myid — узнать свой Telegram ID\n"
        "/changelog — что нового в боте\n"
        "/feedback <code>&lt;текст&gt;</code> — отправить пожелание или сообщение о проблеме\n",
        parse_mode=ParseMode.HTML,
    )


async def handle_changelog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(PUBLIC_CHANGELOG_TEXT, parse_mode=ParseMode.HTML)


async def handle_myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    name = update.effective_user.full_name
    await update.message.reply_text(
        f"👤 <b>{html.escape(name)}</b>\nTelegram ID: <code>{uid}</code>",
        parse_mode=ParseMode.HTML,
    )


async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Использование: <code>/feedback &lt;твой текст&gt;</code>\n\n"
            "Например:\n"
            "<code>/feedback Иногда слишком долго отвечает на кружочки</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if ADMIN_USER_ID == 0:
        await update.message.reply_text("⚠️ Команда временно недоступна: администратор не настроен.")
        return

    message = update.message
    chat = message.chat
    user = message.from_user
    feedback_text = " ".join(context.args).strip()

    chat_label = "личка" if chat.type == "private" else f"{chat.type}: {chat.title or chat.id}"
    admin_message = (
        "📨 <b>Новый feedback по боту</b>\n\n"
        f"<b>От:</b> {html.escape(user.full_name)}\n"
        f"<b>User ID:</b> <code>{user.id}</code>\n"
        f"<b>Username:</b> <code>{html.escape(user.username or '-')}</code>\n"
        f"<b>Чат:</b> {html.escape(str(chat_label))}\n"
        f"<b>Chat ID:</b> <code>{chat.id}</code>\n\n"
        f"<b>Текст:</b>\n<blockquote expandable>{html.escape(feedback_text)}</blockquote>"
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=admin_message,
            parse_mode=ParseMode.HTML,
        )
    except Exception as error:
        logger.error("FEEDBACK FORWARD ERROR | user=%d | chat=%d | error=%s", user.id, chat.id, error)
        await update.message.reply_text("⚠️ Не удалось отправить feedback администратору. Попробуй ещё раз позже.")
        return

    logger.info("FEEDBACK | from_user=%d | chat=%d | text=%s", user.id, chat.id, feedback_text[:300])
    await update.message.reply_text("✅ Спасибо. Я отправил твой feedback администратору.")


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("UNHANDLED ERROR | update=%s", update, exc_info=context.error)

    message = getattr(update, "effective_message", None)
    if message is None:
        return

    try:
        await message.reply_text("⚠️ Внутренняя ошибка. Попробуй ещё раз через пару секунд.")
    except Exception as error:
        logger.error("ERROR HANDLER FAILED | error=%s", error)


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Эта команда только для администратора.")
        return

    snapshot = STORAGE.get_stats_snapshot()
    backup = "✅ подключён" if GEMINI_API_KEY_2 else "❌ не настроен"

    top_text = "\n".join(
        f"  <code>{uid}</code>: {count}" for uid, count in snapshot["top_users"]
    ) or "  нет данных"

    blocked_text = "\n".join(
        f"  <code>{uid}</code>" for uid in snapshot["blocked_users"]
    ) or "  нет"

    await update.message.reply_text(
        f"🤖 <b>Статус и статистика</b>\n\n"
        f"<b>Система:</b>\n"
        f"  Модели: <code>{html.escape(' -> '.join(GEMINI_MODEL_CHAIN))}</code>\n"
        f"  Резервный ключ: {backup}\n"
        f"  База данных: <code>{html.escape(DATABASE_PATH)}</code>\n\n"
        f"<b>Запросы:</b>\n"
        f"  Сегодня: <b>{snapshot['today']}</b>\n"
        f"  Голосовых всего: <b>{snapshot['voice_total']}</b>\n"
        f"  Кружочков всего: <b>{snapshot['video_total']}</b>\n\n"
        f"<b>Топ пользователей:</b>\n{top_text}\n\n"
        f"<b>Заблокированы:</b>\n{blocked_text}",
        parse_mode=ParseMode.HTML,
    )


async def handle_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope_key, scope_label = get_settings_scope(update.message)
    scope_type, scope_id = scope_key

    if not context.args:
        _, current_language = STORAGE.get_settings(scope_type, scope_id)
        await update.message.reply_text(
            f"Текущий язык {scope_label}: <code>{current_language}</code>\n\n"
            "Использование: /language auto | ru | en | de | ...",
            parse_mode=ParseMode.HTML,
        )
        return

    language = context.args[0].lower()
    STORAGE.set_language(scope_type, scope_id, language)
    label = "язык оригинала" if language == "auto" else language
    await update.message.reply_text(
        f"✅ Язык ответа {scope_label}: <b>{html.escape(label)}</b>",
        parse_mode=ParseMode.HTML,
    )


async def handle_transcription_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope_key, scope_label = get_settings_scope(update.message)
    STORAGE.set_mode(scope_key[0], scope_key[1], "transcription_only")
    await update.message.reply_text(
        f"✅ Режим {scope_label}: только <b>транскрипция</b>",
        parse_mode=ParseMode.HTML,
    )


async def handle_summary_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope_key, scope_label = get_settings_scope(update.message)
    STORAGE.set_mode(scope_key[0], scope_key[1], "summary_only")
    await update.message.reply_text(
        f"✅ Режим {scope_label}: только <b>краткое содержание</b>",
        parse_mode=ParseMode.HTML,
    )


async def handle_tldr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope_key, scope_label = get_settings_scope(update.message)
    STORAGE.set_mode(scope_key[0], scope_key[1], "tldr")
    await update.message.reply_text(
        f"✅ Режим {scope_label}: <b>только главное</b> (одно предложение)",
        parse_mode=ParseMode.HTML,
    )


async def handle_both(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope_key, scope_label = get_settings_scope(update.message)
    STORAGE.set_mode(scope_key[0], scope_key[1], "both")
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

    STORAGE.add_admin_block(target_id, update.effective_user.id)
    logger.info("ADMIN BLOCK | admin=%d blocked user=%d", update.effective_user.id, target_id)
    await update.message.reply_text(
        f"🚫 Пользователь <code>{target_id}</code> заблокирован.",
        parse_mode=ParseMode.HTML,
    )


async def handle_unblock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Эта команда только для администратора.")
        return

    if not context.args:
        blocked = "\n".join(
            f"  <code>{uid}</code>" for uid in STORAGE.list_blocked_user_ids()
        ) or "  никого нет"
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

    if STORAGE.remove_admin_block(target_id):
        logger.info("ADMIN UNBLOCK | admin=%d unblocked user=%d", update.effective_user.id, target_id)
        await update.message.reply_text(
            f"✅ Пользователь <code>{target_id}</code> разблокирован.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            f"ℹ️ Пользователь <code>{target_id}</code> не был заблокирован.",
            parse_mode=ParseMode.HTML,
        )


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
    now_ignored = STORAGE.toggle_group_ignore(message.chat.id, target.id, message.from_user.id)
    if now_ignored:
        await message.reply_text(
            f"🚫 Сообщения от <b>{html.escape(target.full_name)}</b> теперь игнорируются.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await message.reply_text(
            f"✅ Пользователь <b>{html.escape(target.full_name)}</b> снова будет обрабатываться.",
            parse_mode=ParseMode.HTML,
        )


# ── Media handlers ────────────────────────────────────────────────────────────


async def handle_media(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    media_type: str,
) -> None:
    message = update.message
    user = message.from_user
    user_id = user.id
    user_name = user.full_name
    chat_id = message.chat.id
    chat_title = get_chat_title(message)

    STORAGE.upsert_user(user_id, user_name, user.username)
    STORAGE.upsert_chat(chat_id, message.chat.type, message.chat.title, message.chat.username)

    scope_key, _ = get_settings_scope(message)
    scope_type, scope_id = scope_key
    mode, language = STORAGE.get_settings(scope_type, scope_id)

    media_meta = get_media_metadata(message, media_type)
    media = media_meta["media"]
    duration = int(media.duration)
    duration_str = format_duration(duration)
    file_size_kb = int(media.file_size // 1024) if getattr(media, "file_size", None) else None

    if STORAGE.is_user_ignored(user_id, chat_id):
        STORAGE.create_message_processing(
            telegram_message_id=message.message_id,
            chat_id=chat_id,
            user_id=user_id,
            media_type=media_type,
            telegram_file_id=media.file_id,
            duration_seconds=duration,
            file_size_kb=file_size_kb,
            scope_type=scope_type,
            scope_id=scope_id,
            mode=mode,
            language=language,
            status="ignored",
            completed_at=utc_now(),
            processing_ms=0,
            error_code="ignored",
            error_text="Ignored by policy",
        )
        logger.info(
            "IGNORED | media=%s | chat=%s (%d) | user=%s (%d)",
            media_type,
            chat_title,
            chat_id,
            user_name,
            user_id,
        )
        return

    if not STORAGE.check_and_record_rate_limit(user_id, RATE_LIMIT, time.time()):
        rate_limit_text = "⏳ Слишком много запросов. Подожди минуту."
        STORAGE.create_message_processing(
            telegram_message_id=message.message_id,
            chat_id=chat_id,
            user_id=user_id,
            media_type=media_type,
            telegram_file_id=media.file_id,
            duration_seconds=duration,
            file_size_kb=file_size_kb,
            scope_type=scope_type,
            scope_id=scope_id,
            mode=mode,
            language=language,
            status="rate_limited",
            completed_at=utc_now(),
            processing_ms=0,
            final_reply_text=rate_limit_text,
            error_code="rate_limited",
            error_text="Rate limit exceeded",
        )
        await message.reply_text(rate_limit_text)
        return

    processing = await message.reply_text(str(media_meta["progress_text"]))
    t_start = time.monotonic()
    started_at = utc_now()
    message_processing_id = STORAGE.create_message_processing(
        telegram_message_id=message.message_id,
        chat_id=chat_id,
        user_id=user_id,
        media_type=media_type,
        telegram_file_id=media.file_id,
        duration_seconds=duration,
        file_size_kb=file_size_kb,
        scope_type=scope_type,
        scope_id=scope_id,
        mode=mode,
        language=language,
        status="started",
        started_at=started_at,
    )
    run_meta: dict[str, object] = {
        "attempt_no": 1,
        "models_tried": [],
        "fallback_key_used": False,
    }

    try:
        file = await context.bot.get_file(media.file_id)
        data = await file.download_as_bytearray()
        actual_file_size_kb = len(data) // 1024
        mime_type = str(media_meta["mime_type"])
        prompt = build_prompt(media_type, language, mode)

        raw, model_used = await call_gemini_with_retries(
            [
                types.Content(
                    parts=[
                        types.Part.from_bytes(data=bytes(data), mime_type=mime_type),
                        types.Part.from_text(text=prompt),
                    ]
                )
            ],
            processing,
            message_processing_id,
            run_meta,
        )

        elapsed_seconds = time.monotonic() - t_start
        elapsed_ms = int(elapsed_seconds * 1000)
        transcription, summary = parse_response_sections(raw, mode)
        final_reply = build_final_reply(str(media_meta["emoji"]), duration_str, user_name, raw, mode)
        await safe_edit_text(processing, final_reply)

        STORAGE.increment_stats(user_id, media_type)
        STORAGE.update_message_processing(
            message_processing_id,
            status="success",
            completed_at=utc_now(),
            processing_ms=elapsed_ms,
            file_size_kb=actual_file_size_kb,
            raw_model_response=raw,
            transcription_text=transcription,
            summary_text=summary,
            final_reply_text=final_reply,
            model_used=model_used,
            models_tried=models_tried_text(run_meta),
            fallback_key_used=1 if run_meta["fallback_key_used"] else 0,
        )

        logger.info(
            "✅ %s | chat=%s (%d) | user=%s (%d) | duration=%s | size=%dKB | mode=%s | lang=%s | model=%s | time=%.1fs | text: %s",
            media_type.upper(),
            chat_title,
            chat_id,
            user_name,
            user_id,
            duration_str,
            actual_file_size_kb,
            mode,
            language,
            model_used,
            elapsed_seconds,
            raw.replace("\n", " ")[:300],
        )
    except Exception as error:
        elapsed_seconds = time.monotonic() - t_start
        elapsed_ms = int(elapsed_seconds * 1000)
        user_error_text = friendly_error(error)

        STORAGE.update_message_processing(
            message_processing_id,
            status="failed",
            completed_at=utc_now(),
            processing_ms=elapsed_ms,
            final_reply_text=user_error_text,
            models_tried=models_tried_text(run_meta),
            fallback_key_used=1 if run_meta["fallback_key_used"] else 0,
            error_code=extract_error_code(error),
            error_text=shorten_error(error),
        )

        logger.error(
            "❌ %s ERROR | chat=%s (%d) | user=%s (%d) | time=%.1fs | error=%s",
            media_type.upper(),
            chat_title,
            chat_id,
            user_name,
            user_id,
            elapsed_seconds,
            error,
        )
        await safe_edit_text(processing, user_error_text)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_media(update, context, "voice")


async def handle_video_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_media(update, context, "video")


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    STORAGE.init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("changelog", handle_changelog))
    app.add_handler(CommandHandler("feedback", handle_feedback))
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
    app.add_error_handler(handle_error)

    logger.info(
        "Bot started (models: %s, backup key: %s, db: %s)",
        " -> ".join(GEMINI_MODEL_CHAIN),
        "yes" if GEMINI_API_KEY_2 else "no",
        DATABASE_PATH,
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
