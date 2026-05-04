import asyncio
import html
import logging
import os
import re
import time
from datetime import datetime, timezone

from google import genai
from google.genai import types
from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, Update
from telegram.constants import ParseMode
from telegram.error import RetryAfter
from telegram.ext import Application, ApplicationHandlerStop, CommandHandler, ContextTypes, MessageHandler, filters

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
MODEL_REQUEST_TIMEOUT = int(os.environ.get("MODEL_REQUEST_TIMEOUT", "45"))
PENDING_FEEDBACK_TTL_SECONDS = int(os.environ.get("PENDING_FEEDBACK_TTL_SECONDS", "900"))
COMMAND_RATE_LIMIT = int(os.environ.get("COMMAND_RATE_LIMIT", "10"))
COMMAND_RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("COMMAND_RATE_LIMIT_WINDOW_SECONDS", "300"))
ADMIN_HISTORY_DEFAULT_LIMIT = 10
ADMIN_HISTORY_MAX_LIMIT = 20
ADMIN_PANEL_REPLY_LIMIT = 3500
KNOWN_PROCESSING_STATUSES = {"started", "success", "failed", "ignored", "rate_limited"}

GEMINI_MODEL_CHAIN: list[str] = []
for model_name in [GEMINI_MODEL, *GEMINI_FALLBACK_MODELS]:
    if model_name not in GEMINI_MODEL_CHAIN:
        GEMINI_MODEL_CHAIN.append(model_name)

# Gemini clients — основной + резервный
gemini_clients = [genai.Client(api_key=GEMINI_API_KEY)]
if GEMINI_API_KEY_2:
    gemini_clients.append(genai.Client(api_key=GEMINI_API_KEY_2))

STORAGE = Storage(DATABASE_PATH)
PUBLIC_CHANGELOG_VERSION = "2026-05-04"

PUBLIC_CHANGELOG_TEXT = """🆕 <b>Что нового в боте</b>

Вот что стало лучше:
- исправлена команда <code>/ignore</code> в группах: теперь игнорируемый человек не сможет спамить команды и feedback в этой группе;
- глобальная блокировка через админскую команду <code>/block</code> теперь блокирует пользователя везде, а <code>/unblock</code> снимает и глобальную блокировку, и групповые игноры;
- добавлена защита от спама командами: если слишком часто тыкать команды, бот попросит подождать;
- таймер обработки стал устойчивее к ограничениям Telegram на частое редактирование сообщений.

Если заметишь что-то странное в работе бота, отправь <code>/feedback твой текст</code>."""

USER_COMMANDS = [
    BotCommand("start", "Запустить бота"),
    BotCommand("help", "Показать команды и подсказки"),
    BotCommand("both", "Транскрипция и краткое содержание"),
    BotCommand("transcription_only", "Только транскрипция"),
    BotCommand("summary_only", "Только краткое содержание"),
    BotCommand("tldr", "Одно предложение с самой сутью"),
    BotCommand("language", "Настроить язык ответа"),
    BotCommand("myid", "Показать ваш Telegram ID"),
    BotCommand("feedback", "Отправить feedback администратору"),
    BotCommand("changelog", "Показать последние изменения"),
    BotCommand("ignore", "Игнорировать пользователя в группе по reply"),
]

ADMIN_COMMANDS = [
    BotCommand("stats", "Показать статистику бота"),
    BotCommand("history", "Показать последние обработки"),
    BotCommand("last_errors", "Показать последние ошибки моделей"),
    BotCommand("block", "Глобально заблокировать пользователя"),
    BotCommand("unblock", "Снять глобальный блок и групповые игноры"),
    BotCommand("broadcast_changelog", "Разослать текущий changelog в лички"),
]

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


def extract_section(raw: str, start_label: str, end_labels: tuple[str, ...]) -> str:
    upper = raw.upper()
    start_idx = upper.find(start_label)
    if start_idx == -1:
        return ""

    content_start = start_idx + len(start_label)
    content_end = len(raw)
    for end_label in end_labels:
        end_idx = upper.find(end_label, content_start)
        if end_idx != -1:
            content_end = min(content_end, end_idx)
    return raw[content_start:content_end].strip()


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
        "model_request_timeout" in err_str
        or
        "503" in str(error)
        or "status': 'unavailable'" in err_str
        or '"status": "unavailable"' in err_str
        or "high demand" in err_str
        or "currently experiencing high demand" in err_str
        or "please try again later" in err_str
    )


def extract_error_code(error: Exception) -> str:
    err_str = str(error).lower()
    if "model_request_timeout" in err_str:
        return "model_request_timeout"
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


def format_processing_time(seconds: float) -> str:
    total_seconds = max(1, int(seconds))
    minutes, remaining_seconds = divmod(total_seconds, 60)
    if minutes == 0:
        return f"{remaining_seconds} сек"
    return f"{minutes} мин {remaining_seconds:02d} сек"


def format_timestamp(timestamp: str | None) -> str:
    if not timestamp:
        return "-"
    try:
        dt = datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def format_processing_ms(processing_ms: int | None) -> str:
    if processing_ms is None:
        return "-"
    return format_processing_time(processing_ms / 1000)


def parse_limit_arg(args: list[str], default: int, maximum: int, command_name: str) -> tuple[int | None, str | None]:
    if not args:
        return default, None
    if len(args) != 1:
        return None, f"Использование: /{command_name} [количество]"
    try:
        limit = int(args[0])
    except ValueError:
        return None, f"Использование: /{command_name} [количество]"
    if limit < 1:
        return None, "Количество должно быть положительным числом."
    return min(limit, maximum), None


def format_user_label(user_id: int | None, full_name: str | None, username: str | None) -> str:
    if user_id is None:
        return "без пользователя"
    if username:
        label = f"@{username}"
    elif full_name:
        label = full_name
    else:
        label = "без имени"
    return f"{html.escape(label)} (<code>{user_id}</code>)"


def format_chat_label(chat_id: int | None, chat_type: str | None, title: str | None, chat_username: str | None) -> str:
    if chat_id is None:
        return "без чата"
    if chat_type == "private":
        return f"личка (<code>{chat_id}</code>)"
    if chat_username:
        label = f"@{chat_username}"
    elif title:
        label = title
    elif chat_type:
        label = chat_type
    else:
        label = "неизвестный чат"
    return f"{html.escape(label)} (<code>{chat_id}</code>)"


def format_processing_status(status: str) -> str:
    labels = {
        "success": "✅ success",
        "failed": "❌ failed",
        "ignored": "🚫 ignored",
        "rate_limited": "⏳ rate_limited",
        "started": "⚙️ started",
    }
    return labels.get(status, html.escape(status))


def shorten_text(text: str | None, limit: int = 180) -> str:
    if not text:
        return "-"
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


def format_history_entry(entry: dict[str, object]) -> str:
    media_icons = {"voice": "🎙", "video": "🔵"}
    media_type = str(entry["media_type"])
    model_used = entry["model_used"] or "-"
    return (
        f"<b>#{entry['id']}</b> — {html.escape(format_timestamp(entry['created_at']))}\n"
        f"👤 {format_user_label(entry['user_id'], entry.get('full_name'), entry.get('username'))}\n"
        f"💬 {format_chat_label(entry['chat_id'], entry.get('chat_type'), entry.get('title'), entry.get('chat_username'))}\n"
        f"{media_icons.get(media_type, '📄')} {html.escape(media_type)} | "
        f"{format_processing_status(str(entry['status']))} | "
        f"<code>{html.escape(str(model_used))}</code> | "
        f"{html.escape(format_processing_ms(entry.get('processing_ms')))}"
    )


def format_last_error_entry(entry: dict[str, object]) -> str:
    error_text = shorten_text(str(entry.get("attempt_error_text") or "-"))
    return (
        f"<b>Attempt #{entry['attempt_id']}</b> — {html.escape(format_timestamp(entry['attempt_started_at']))}\n"
        f"🤖 <code>{html.escape(str(entry['model_name']))}</code> | try {entry['attempt_no']} | "
        f"{html.escape(str(entry['api_key_slot']))} | processing <code>#{entry['processing_id']}</code>\n"
        f"👤 {format_user_label(entry['user_id'], entry.get('full_name'), entry.get('username'))}\n"
        f"💬 {format_chat_label(entry['chat_id'], entry.get('chat_type'), entry.get('title'), entry.get('chat_username'))} | "
        f"msg <code>{entry['telegram_message_id']}</code>\n"
        f"⚠️ {html.escape(error_text)}"
    )


async def reply_html_entries(message, heading: str, entries: list[str]) -> None:
    if not entries:
        await message.reply_text(heading, parse_mode=ParseMode.HTML)
        return

    chunks: list[str] = []
    current = heading
    for entry in entries:
        candidate = f"{current}\n\n{entry}"
        if len(candidate) > ADMIN_PANEL_REPLY_LIMIT and current != heading:
            chunks.append(current)
            current = f"{heading}\n\n{entry}"
            continue
        current = candidate
    chunks.append(current)

    for chunk in chunks:
        await message.reply_text(chunk, parse_mode=ParseMode.HTML)


def get_settings_scope(message) -> tuple[tuple[str, int], str]:
    if message.chat.type in ("group", "supergroup"):
        return ("chat", message.chat.id), "для этой группы"
    return ("user", message.from_user.id), "для тебя"


def remember_context(update: Update) -> None:
    user = update.effective_user
    chat = update.effective_chat

    if user is not None:
        STORAGE.upsert_user(user.id, user.full_name, user.username)

    if chat is not None:
        STORAGE.upsert_chat(
            chat.id,
            chat.type,
            getattr(chat, "title", None),
            getattr(chat, "username", None),
        )


def extract_command_name(message) -> str | None:
    text = message.text or message.caption or ""
    if not text.startswith("/"):
        return None
    command = text.split(maxsplit=1)[0][1:]
    if not command:
        return None
    return command.split("@", maxsplit=1)[0].lower()


def is_private_chat(message) -> bool:
    return message.chat.type == "private"


def is_group_chat(message) -> bool:
    return message.chat.type in ("group", "supergroup")


async def is_group_admin_for_message(message) -> bool:
    if not is_group_chat(message):
        return False
    member = await message.chat.get_member(message.from_user.id)
    return member.status in ("administrator", "creator")


async def should_skip_command_rate_limit(message, command_name: str) -> bool:
    if is_admin(message.from_user.id):
        return True
    if command_name == "ignore" and is_group_chat(message):
        try:
            return await is_group_admin_for_message(message)
        except Exception as error:
            logger.warning(
                "COMMAND RATE ADMIN CHECK FAILED | chat=%d | user=%d | error=%s",
                message.chat.id,
                message.from_user.id,
                error,
            )
    return False


async def guard_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None:
        return

    remember_context(update)
    command_name = extract_command_name(message)
    is_text_feedback_candidate = message.text is not None and command_name is None
    should_guard = command_name is not None or is_text_feedback_candidate
    if not should_guard or is_admin(user.id):
        return

    if STORAGE.is_globally_blocked(user.id):
        if is_text_feedback_candidate:
            STORAGE.clear_pending_feedback(chat.id, user.id)
        logger.info(
            "BLOCKED UPDATE IGNORED | user=%d | chat=%d | command=%s | scope=global",
            user.id,
            chat.id,
            command_name or "text",
        )
        raise ApplicationHandlerStop

    if is_group_chat(message) and STORAGE.is_group_ignored(chat.id, user.id):
        if is_text_feedback_candidate:
            STORAGE.clear_pending_feedback(chat.id, user.id)
        logger.info(
            "BLOCKED UPDATE IGNORED | user=%d | chat=%d | command=%s | scope=group",
            user.id,
            chat.id,
            command_name or "text",
        )
        raise ApplicationHandlerStop

    if command_name is None or await should_skip_command_rate_limit(message, command_name):
        return

    allowed, should_warn = STORAGE.check_and_record_command_rate_limit(
        user_id=user.id,
        command_name=command_name,
        rate_limit=COMMAND_RATE_LIMIT,
        now_ts=time.time(),
        window_seconds=COMMAND_RATE_LIMIT_WINDOW_SECONDS,
    )
    if allowed:
        return

    logger.info(
        "COMMAND RATE LIMITED | user=%d | chat=%d | command=%s",
        user.id,
        chat.id,
        command_name,
    )
    if should_warn:
        await message.reply_text("⏳ Слишком много команд. Подожди несколько минут.")
    raise ApplicationHandlerStop


def parse_response_sections(raw: str, mode: str) -> tuple[str, str]:
    raw = raw.strip()

    if mode == "tldr":
        summary = extract_section(raw, "КРАТКОЕ СОДЕРЖАНИЕ:", tuple())
        if summary:
            return "", summary
        return "", raw

    transcription = extract_section(raw, "ТРАНСКРИПЦИЯ:", ("КРАТКОЕ СОДЕРЖАНИЕ:",))
    summary = extract_section(raw, "КРАТКОЕ СОДЕРЖАНИЕ:", ("ТРАНСКРИПЦИЯ:",))

    if transcription or summary:
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


def build_final_reply(
    media_emoji: str,
    duration_str: str,
    user_name: str,
    raw: str,
    mode: str,
    processing_time_text: str,
) -> str:
    header = (
        f"{media_emoji} <b>{duration_str}</b> — {html.escape(user_name)} "
        f"<i>(обрабатывалось: {html.escape(processing_time_text)})</i>\n\n"
    )
    return header + format_response(raw, mode)


def build_help_text(user_id: int) -> str:
    sections = [
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
        "/feedback — бот попросит следующим сообщением написать feedback\n"
        "/feedback <code>&lt;текст&gt;</code> — отправить feedback сразу одной командой\n"
        "/changelog — посмотреть последние изменения\n"
        "/ignore — ответить в группе на сообщение пользователя, чтобы игнорировать/вернуть его"
    ]

    if is_admin(user_id):
        sections.append(
            "\n\n<b>Команды администратора:</b>\n"
            "/stats — статистика и состояние бота\n"
            "/history <code>[N]</code> — последние обработки из БД\n"
            "/last_errors <code>[N]</code> — последние ошибки моделей\n"
            "/block <code>user_id</code> — глобально заблокировать пользователя (только в личке)\n"
            "/unblock <code>user_id</code> — снять глобальный блок и все групповые игноры (только в личке)\n"
            "/broadcast_changelog — разослать текущий changelog в личные чаты"
        )

    return "".join(sections)


async def sync_bot_commands(app: Application) -> None:
    try:
        await app.bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeDefault())
    except Exception as error:
        logger.warning("BOT COMMAND SYNC ERROR | scope=default | error=%s", error)

    if ADMIN_USER_ID:
        try:
            await app.bot.set_my_commands(
                [*USER_COMMANDS, *ADMIN_COMMANDS],
                scope=BotCommandScopeChat(chat_id=ADMIN_USER_ID),
            )
        except Exception as error:
            logger.warning("BOT COMMAND SYNC ERROR | scope=admin | error=%s", error)


async def post_init(app: Application) -> None:
    await sync_bot_commands(app)


def feedback_hint_text() -> str:
    return (
        "Если проблема повторится, отправь <code>/feedback</code>, "
        "и следующим сообщением я перешлю описание администратору."
    )


def unknown_internal_error_text() -> str:
    return (
        "⚠️ Внутренняя ошибка. Попробуй ещё раз через пару секунд.\n"
        f"{feedback_hint_text()}"
    )


def get_retry_after_seconds(error: Exception) -> int | None:
    if isinstance(error, RetryAfter):
        try:
            return max(1, int(float(error.retry_after)))
        except (TypeError, ValueError):
            return 1

    match = re.search(r"retry in (\d+) seconds?", str(error).lower())
    if match:
        return max(1, int(match.group(1)))
    return None


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
    return unknown_internal_error_text()


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


class ProcessingProgress:
    def __init__(self, message, initial_status_text: str) -> None:
        self.message = message
        self.initial_status_text = initial_status_text
        self.status_text = initial_status_text
        self.started_monotonic = time.monotonic()
        self._last_rendered_text = ""
        self._stop_event = asyncio.Event()
        self._refresh_lock = asyncio.Lock()
        self._retry_after_until = 0.0
        self._flood_notice_sent = False

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_monotonic

    def elapsed_text(self) -> str:
        return format_processing_time(self.elapsed_seconds())

    def render(self) -> str:
        return (
            f"{self.status_text}\n\n"
            f"⏱ <b>Обрабатывается:</b> {html.escape(self.elapsed_text())}"
        )

    async def refresh(self) -> None:
        async with self._refresh_lock:
            rendered = self.render()
            if rendered == self._last_rendered_text:
                return
            if time.monotonic() < self._retry_after_until:
                return
            try:
                await safe_edit_text(self.message, rendered)
            except Exception as error:
                retry_after = get_retry_after_seconds(error)
                if retry_after is None:
                    raise
                await self.handle_flood_control(retry_after)
                return
            self._last_rendered_text = rendered

    async def set_status_text(self, status_text: str) -> None:
        self.status_text = status_text
        await self.refresh()

    async def handle_flood_control(self, retry_after: int) -> None:
        self._retry_after_until = max(self._retry_after_until, time.monotonic() + retry_after)
        logger.warning(
            "PROGRESS MESSAGE FLOOD CONTROL | retry_after=%ss | message_id=%s",
            retry_after,
            getattr(self.message, "message_id", "unknown"),
        )
        if self._flood_notice_sent:
            return
        self._flood_notice_sent = True
        try:
            await self.message.reply_text(
                "⏳ Telegram временно ограничил обновление таймера.\n"
                "Обработка продолжается. Готовый результат я всё равно отправлю, как только лимит спадёт."
            )
        except Exception as notify_error:
            logger.warning("PROGRESS FLOOD NOTICE FAILED | error=%s", notify_error)

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.refresh()
            except Exception as error:
                logger.warning("PROGRESS REFRESH ERROR | error=%s", error)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=1)
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        self._stop_event.set()


async def show_overload_countdown(progress: ProcessingProgress, model_name: str) -> None:
    for seconds_left in range(MODEL_OVERLOAD_RETRY_DELAY, 0, -1):
        await progress.set_status_text(
            "⚠️ <b>Модель перегружена</b>\n"
            f"<code>{html.escape(model_name)}</code>\n"
            f"Пробую снова через <b>{seconds_left}</b> сек...",
        )
        await asyncio.sleep(1)


async def stop_progress(progress: ProcessingProgress, progress_task: asyncio.Task) -> None:
    progress.stop()
    try:
        await progress_task
    except Exception as error:
        logger.warning("PROGRESS TASK ERROR | error=%s", error)


async def deliver_processing_reply(message, text: str) -> None:
    try:
        await safe_edit_text(message, text)
        return
    except Exception as error:
        retry_after = get_retry_after_seconds(error)
        if retry_after is None:
            logger.warning("FINAL MESSAGE EDIT FAILED | message_id=%s | error=%s", getattr(message, "message_id", "unknown"), error)
            await message.reply_text(text, parse_mode=ParseMode.HTML)
            return

        logger.warning(
            "FINAL MESSAGE FLOOD CONTROL | retry_after=%ss | message_id=%s",
            retry_after,
            getattr(message, "message_id", "unknown"),
        )
        try:
            await message.reply_text(
                "⏳ Telegram временно ограничил обновление этого сообщения.\n"
                "Подожди немного, я пришлю готовый результат сразу после ограничения."
            )
        except Exception as notify_error:
            logger.warning("FINAL FLOOD NOTICE FAILED | error=%s", notify_error)

        await asyncio.sleep(retry_after)
        try:
            await safe_edit_text(message, text)
            return
        except Exception as second_error:
            logger.warning("FINAL EDIT RETRY FAILED | error=%s", second_error)

        await message.reply_text(text, parse_mode=ParseMode.HTML)


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
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    client.models.generate_content,
                    model=model_name,
                    contents=contents,
                ),
                timeout=MODEL_REQUEST_TIMEOUT,
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
        except asyncio.TimeoutError:
            error = RuntimeError(
                f"model_request_timeout: generate_content exceeded {MODEL_REQUEST_TIMEOUT}s for {model_name}"
            )
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
            last_error = error
            break
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
    progress: ProcessingProgress,
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
                    await progress.set_status_text(
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
                    await show_overload_countdown(progress, model_name)
                    continue

                next_model_index = model_index + 1
                if next_model_index < len(GEMINI_MODEL_CHAIN):
                    next_model = GEMINI_MODEL_CHAIN[next_model_index]
                    await progress.set_status_text(
                        "⚠️ <b>Модель всё ещё перегружена</b>\n"
                        f"<code>{html.escape(model_name)}</code>\n"
                        f"Переключаюсь на <code>{html.escape(next_model)}</code>...",
                    )
                    break

                raise

    raise last_error


# ── Command handlers ──────────────────────────────────────────────────────────


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_context(update)
    await update.message.reply_text(
        "👋 Привет! Я бот для расшифровки голосовых сообщений и кружочков.\n\n"
        "Просто отправь мне 🎙 голосовое или 🔵 кружочек — я:\n"
        "• переведу речь в текст\n"
        "• сделаю краткое содержание\n"
        "• для кружочков учту и видеоряд\n\n"
        "Используй /help для списка команд."
    )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_context(update)
    await update.message.reply_text(
        build_help_text(update.effective_user.id),
        parse_mode=ParseMode.HTML,
    )


async def handle_changelog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_context(update)
    await update.message.reply_text(PUBLIC_CHANGELOG_TEXT, parse_mode=ParseMode.HTML)


async def handle_myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_context(update)
    uid = update.effective_user.id
    name = update.effective_user.full_name
    await update.message.reply_text(
        f"👤 <b>{html.escape(name)}</b>\nTelegram ID: <code>{uid}</code>",
        parse_mode=ParseMode.HTML,
    )


async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_context(update)
    if ADMIN_USER_ID == 0:
        await update.message.reply_text("⚠️ Команда временно недоступна: администратор не настроен.")
        return

    message = update.message
    chat = message.chat
    user = message.from_user
    if not context.args:
        STORAGE.set_pending_feedback(chat.id, user.id)
        await update.message.reply_text(
            "✍️ Следующее текстовое сообщение в этом чате в течение 15 минут "
            "я отправлю администратору как feedback.\n\n"
            "Если хочешь, можешь и сразу одной командой:\n"
            "<code>/feedback Иногда слишком долго отвечает на кружочки</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    feedback_text = " ".join(context.args).strip()
    await forward_feedback(update, context, feedback_text)


async def forward_feedback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    feedback_text: str,
) -> None:
    message = update.message
    chat = message.chat
    user = message.from_user

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

    STORAGE.clear_pending_feedback(chat.id, user.id)
    logger.info("FEEDBACK | from_user=%d | chat=%d | text=%s", user.id, chat.id, feedback_text[:300])
    await update.message.reply_text("✅ Спасибо. Я отправил твой feedback администратору.")


async def handle_pending_feedback_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None or message.text is None:
        return

    remember_context(update)
    chat_id = message.chat.id
    user_id = message.from_user.id
    if not STORAGE.has_pending_feedback(chat_id, user_id, max_age_seconds=PENDING_FEEDBACK_TTL_SECONDS):
        return

    feedback_text = message.text.strip()
    if not feedback_text:
        await message.reply_text("⚠️ Feedback получился пустым. Напиши текстом, что именно хочешь передать.")
        return

    await forward_feedback(update, context, feedback_text)


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("UNHANDLED ERROR | update=%s", update, exc_info=context.error)

    message = getattr(update, "effective_message", None)
    if message is None:
        return

    try:
        await message.reply_text(unknown_internal_error_text(), parse_mode=ParseMode.HTML)
    except Exception as error:
        logger.error("ERROR HANDLER FAILED | error=%s", error)


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_context(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Эта команда только для администратора.")
        return

    snapshot = STORAGE.get_stats_snapshot()
    backup = "✅ подключён" if GEMINI_API_KEY_2 else "❌ не настроен"

    def format_top_user(entry: dict[str, object]) -> str:
        username = entry.get("username")
        full_name = entry.get("full_name")
        user_id = entry["user_id"]
        total_requests = entry["total_requests"]

        if username:
            label = f"@{username}"
        elif full_name:
            label = str(full_name)
        else:
            label = "без имени"

        return f"  {html.escape(label)} (<code>{user_id}</code>): {total_requests}"

    top_text = "\n".join(
        format_top_user(entry) for entry in snapshot["top_users"]
    ) or "  нет данных"

    blocked_text = "\n".join(
        f"  <code>{uid}</code>" for uid in snapshot["global_blocked_users"]
    ) or "  нет"
    group_ignored_count = snapshot["group_ignored_count"]

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
        f"<b>Глобально заблокированы:</b>\n{blocked_text}\n"
        f"<b>Групповых игноров:</b> <code>{group_ignored_count}</code>",
        parse_mode=ParseMode.HTML,
    )


async def handle_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_context(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Эта команда только для администратора.")
        return

    limit, error_text = parse_limit_arg(
        context.args,
        default=ADMIN_HISTORY_DEFAULT_LIMIT,
        maximum=ADMIN_HISTORY_MAX_LIMIT,
        command_name="history",
    )
    if error_text:
        await update.message.reply_text(error_text)
        return

    entries = STORAGE.get_recent_processing(limit=limit or ADMIN_HISTORY_DEFAULT_LIMIT)
    if not entries:
        await update.message.reply_text("ℹ️ В истории обработок пока нет записей.")
        return

    heading = (
        "🗂 <b>Последние обработки</b>\n"
        f"Показываю: <b>{len(entries)}</b>"
    )
    await reply_html_entries(update.message, heading, [format_history_entry(entry) for entry in entries])


async def handle_last_errors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_context(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Эта команда только для администратора.")
        return

    limit, error_text = parse_limit_arg(
        context.args,
        default=ADMIN_HISTORY_DEFAULT_LIMIT,
        maximum=ADMIN_HISTORY_MAX_LIMIT,
        command_name="last_errors",
    )
    if error_text:
        await update.message.reply_text(error_text)
        return

    entries = STORAGE.get_recent_failed_attempts(limit=limit or ADMIN_HISTORY_DEFAULT_LIMIT)
    if not entries:
        await update.message.reply_text("✅ Ошибок model_attempts пока нет.")
        return

    heading = (
        "🚨 <b>Последние ошибки моделей</b>\n"
        f"Показываю: <b>{len(entries)}</b>"
    )
    await reply_html_entries(update.message, heading, [format_last_error_entry(entry) for entry in entries])


async def handle_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_context(update)
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
    remember_context(update)
    scope_key, scope_label = get_settings_scope(update.message)
    STORAGE.set_mode(scope_key[0], scope_key[1], "transcription_only")
    await update.message.reply_text(
        f"✅ Режим {scope_label}: только <b>транскрипция</b>",
        parse_mode=ParseMode.HTML,
    )


async def handle_summary_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_context(update)
    scope_key, scope_label = get_settings_scope(update.message)
    STORAGE.set_mode(scope_key[0], scope_key[1], "summary_only")
    await update.message.reply_text(
        f"✅ Режим {scope_label}: только <b>краткое содержание</b>",
        parse_mode=ParseMode.HTML,
    )


async def handle_tldr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_context(update)
    scope_key, scope_label = get_settings_scope(update.message)
    STORAGE.set_mode(scope_key[0], scope_key[1], "tldr")
    await update.message.reply_text(
        f"✅ Режим {scope_label}: <b>только главное</b> (одно предложение)",
        parse_mode=ParseMode.HTML,
    )


async def handle_both(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_context(update)
    scope_key, scope_label = get_settings_scope(update.message)
    STORAGE.set_mode(scope_key[0], scope_key[1], "both")
    await update.message.reply_text(
        f"✅ Режим {scope_label}: <b>транскрипция + саммари</b>",
        parse_mode=ParseMode.HTML,
    )


async def handle_block(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_context(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Эта команда только для администратора.")
        return

    if not is_private_chat(update.message):
        await update.message.reply_text("⚠️ /block работает только в личном чате с ботом.")
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
    remember_context(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Эта команда только для администратора.")
        return

    if not is_private_chat(update.message):
        await update.message.reply_text("⚠️ /unblock работает только в личном чате с ботом.")
        return

    if not context.args:
        blocked = "\n".join(
            f"  <code>{uid}</code>" for uid in STORAGE.list_global_blocked_user_ids()
        ) or "  никого нет"
        group_ignored = STORAGE.list_group_ignores()
        group_ignored_text = "\n".join(
            f"  <code>{entry['user_id']}</code> в чате <code>{entry['chat_id']}</code>"
            for entry in group_ignored[:20]
        ) or "  никого нет"
        await update.message.reply_text(
            f"Использование: /unblock <code>user_id</code>\n\n"
            f"<b>Глобально заблокированы:</b>\n{blocked}\n\n"
            f"<b>Групповые игноры:</b>\n{group_ignored_text}",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный ID. Должно быть число.")
        return

    removed = STORAGE.remove_all_blocks(target_id)
    if removed["total"]:
        logger.info(
            "ADMIN UNBLOCK | admin=%d unblocked user=%d | global=%d | group=%d",
            update.effective_user.id,
            target_id,
            removed["global"],
            removed["group"],
        )
        await update.message.reply_text(
            f"✅ Пользователь <code>{target_id}</code> разблокирован.\n"
            f"Снято глобальных блокировок: <code>{removed['global']}</code>\n"
            f"Снято групповых игноров: <code>{removed['group']}</code>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            f"ℹ️ У пользователя <code>{target_id}</code> не было блокировок или групповых игноров.",
            parse_mode=ParseMode.HTML,
        )


async def handle_ignore(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_context(update)
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


async def handle_broadcast_changelog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_context(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Эта команда только для администратора.")
        return

    recipients = STORAGE.list_private_chat_users()
    if not recipients:
        await update.message.reply_text("ℹ️ В базе пока нет пользователей, которым можно отправить changelog в личку.")
        return

    sent_count = 0
    skipped_count = 0
    failed_count = 0

    for recipient in recipients:
        user_id = int(recipient["user_id"])
        if STORAGE.has_changelog_been_sent(PUBLIC_CHANGELOG_VERSION, user_id):
            skipped_count += 1
            continue

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=PUBLIC_CHANGELOG_TEXT,
                parse_mode=ParseMode.HTML,
            )
        except Exception as error:
            failed_count += 1
            logger.warning(
                "CHANGELOG BROADCAST ERROR | version=%s | user=%d | error=%s",
                PUBLIC_CHANGELOG_VERSION,
                user_id,
                error,
            )
            continue

        STORAGE.mark_changelog_sent(PUBLIC_CHANGELOG_VERSION, user_id)
        sent_count += 1

    await update.message.reply_text(
        "📣 <b>Рассылка changelog завершена</b>\n\n"
        f"Версия: <code>{html.escape(PUBLIC_CHANGELOG_VERSION)}</code>\n"
        f"Отправлено: <b>{sent_count}</b>\n"
        f"Пропущено как уже отправленное: <b>{skipped_count}</b>\n"
        f"Ошибок доставки: <b>{failed_count}</b>",
        parse_mode=ParseMode.HTML,
    )


# ── Media handlers ────────────────────────────────────────────────────────────


async def handle_media(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    media_type: str,
) -> None:
    message = update.message
    remember_context(update)
    user = message.from_user
    user_id = user.id
    user_name = user.full_name
    chat_id = message.chat.id
    chat_title = get_chat_title(message)

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

    processing = await message.reply_text("⏱ Запускаю обработку...")
    progress = ProcessingProgress(processing, str(media_meta["progress_text"]))
    progress_task = asyncio.create_task(progress.run())
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
            progress,
            message_processing_id,
            run_meta,
        )

        elapsed_seconds = time.monotonic() - t_start
        elapsed_ms = int(elapsed_seconds * 1000)
        processing_time_text = format_processing_time(elapsed_seconds)
        transcription, summary = parse_response_sections(raw, mode)
        final_reply = build_final_reply(
            str(media_meta["emoji"]),
            duration_str,
            user_name,
            raw,
            mode,
            processing_time_text,
        )
        await stop_progress(progress, progress_task)
        await deliver_processing_reply(processing, final_reply)

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
        await stop_progress(progress, progress_task)

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
        await deliver_processing_reply(processing, user_error_text)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_media(update, context, "voice")


async def handle_video_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_media(update, context, "video")


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    STORAGE.init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    app.add_handler(MessageHandler(filters.ALL, guard_update), group=-1)
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("changelog", handle_changelog))
    app.add_handler(CommandHandler("feedback", handle_feedback))
    app.add_handler(CommandHandler("myid", handle_myid))
    app.add_handler(CommandHandler("stats", handle_stats))
    app.add_handler(CommandHandler("history", handle_history))
    app.add_handler(CommandHandler("last_errors", handle_last_errors))
    app.add_handler(CommandHandler("block", handle_block))
    app.add_handler(CommandHandler("unblock", handle_unblock))
    app.add_handler(CommandHandler("broadcast_changelog", handle_broadcast_changelog))
    app.add_handler(CommandHandler("language", handle_language))
    app.add_handler(CommandHandler("transcription_only", handle_transcription_only))
    app.add_handler(CommandHandler("summary_only", handle_summary_only))
    app.add_handler(CommandHandler("tldr", handle_tldr))
    app.add_handler(CommandHandler("both", handle_both))
    app.add_handler(CommandHandler("ignore", handle_ignore))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.VIDEO_NOTE, handle_video_note))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_pending_feedback_message))
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
