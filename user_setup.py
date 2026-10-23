"""Bounded, owner-bound setup wizard. Choices persist atomically at completion."""
from collections import OrderedDict
from dataclasses import dataclass, field
import html
import secrets
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


STEPS = ("mode", "language", "transcription_type", "technical_details", "context_enabled")
CHOICES = {
    "mode": [("Текст + краткое содержание", "both"), ("Только текст", "transcription_only"),
             ("Только краткое содержание", "summary_only"), ("Самая суть (TLDR)", "tldr")],
    "language": [("Язык оригинала", "auto"), ("Русский", "ru"), ("Українська", "uk"),
                 ("English", "en"), ("Deutsch", "de"), ("Другой язык / свой стиль", "custom")],
    "transcription_type": [("Очищенный текст", "clean"), ("Дословно, с повторами", "verbatim")],
    "technical_details": [("Простой — без технических названий", "simple"),
                          ("Технический — модели и безопасная диагностика", "technical")],
    "context_enabled": [("Не учитывать переписку", "off"), ("Включить короткий контекст", "on")],
}
DESCRIPTIONS = {
    "mode": "Какой ответ ты хочешь получать?",
    "language": "На каком языке отвечать? Дословная транскрипция сохраняет язык речи.",
    "transcription_type": "Очищенный текст убирает лишние повторы. Дословный сохраняет услышанные слова.",
    "technical_details": "Показывать названия моделей и безопасные подробности ошибок? В группе выбор виден всем.",
    "context_enabled": (
        "Учитывать недавнюю беседу? По умолчанию — нет.\n\n"
        "При включении после первого голосового бот временно запоминает доступные ему сообщения "
        "этого чата/темы за 5 минут. Следующее голосовое в пределах 2 минут может использовать их "
        "только при ясной связи по смыслу. Пересланные сообщения исключены.\n\n"
        "Текст хранится только в оперативной памяти; выбранный фрагмент отправляется сервису "
        "распознавания. Исходная речь не дополняется придуманными словами. "
        "/context off очищает буфер. /context clear очищает его без смены настройки. "
        "В группах изменение доступно администраторам; бот видит только сообщения, разрешённые Telegram."
    ),
}


@dataclass
class SetupSession:
    nonce: str
    chat_id: int
    user_id: int
    scope_type: str
    scope_id: int
    message_id: int
    updated: float
    thread_id: int = 0
    step: str = "mode"
    values: dict = field(default_factory=dict)


class SetupWizard:
    def __init__(self, storage, *, clock=time.monotonic, max_sessions=512, on_saved=None):
        self.storage = storage
        self.clock = clock
        self.max_sessions = max_sessions
        self.on_saved = on_saved
        self.sessions = OrderedDict()

    def purge(self):
        for nonce, session in list(self.sessions.items()):
            if self.clock() - session.updated >= 900:
                self.sessions.pop(nonce, None)

    def render(self, state):
        if state.step == "custom_language":
            return ("✍️ Напиши следующим сообщением язык или стиль ответа (до 200 символов). "
                    "Это сообщение не попадёт в контекст. /cancel — отменить настройку.", None)
        title = f"⚙️ Настройка — шаг {STEPS.index(state.step) + 1}/{len(STEPS)}\n\n"
        choices = list(CHOICES[state.step])
        if state.step == "language" and state.values["language"] not in {v for _, v in choices}:
            choices.insert(0, ("Оставить текущий язык / стиль", "keep"))
        rows = [[InlineKeyboardButton(label, callback_data=f"setup:{state.nonce}:{value}")]
                for label, value in choices]
        rows.append([InlineKeyboardButton("Отмена", callback_data=f"setup:{state.nonce}:cancel")])
        return title + DESCRIPTIONS[state.step], InlineKeyboardMarkup(rows)

    async def start(self, message, user_id, scope_type, scope_id):
        self.purge()
        for nonce, session in list(self.sessions.items()):
            if session.chat_id == message.chat.id and session.user_id == user_id:
                self.sessions.pop(nonce, None)
        mode, language, transcription_type = self.storage.get_settings(scope_type, scope_id)
        state = SetupSession(secrets.token_hex(5), message.chat.id, user_id, scope_type, scope_id,
                             0, self.clock(), thread_id=getattr(message, "message_thread_id", None) or 0,
                             values={"mode": mode, "language": language,
                             "transcription_type": transcription_type,
                             **self.storage.get_preferences(scope_type, scope_id)})
        text, keyboard = self.render(state)
        intro = ("👋 Я превращаю голосовые и кружочки в текст и краткое содержание. "
                 "Настроим формат, язык и приватность. Изменения сохранятся только после последнего шага.\n\n")
        sent = await message.reply_text(intro + text, reply_markup=keyboard)
        state.message_id = sent.message_id
        self.sessions[state.nonce] = state
        while len(self.sessions) > self.max_sessions:
            self.sessions.popitem(last=False)

    async def callback(self, query, authorize):
        self.purge()
        parts = (query.data or "").split(":")
        state = self.sessions.get(parts[1]) if len(parts) == 3 and parts[0] == "setup" else None
        if state is None:
            await query.answer("Настройка устарела. Открой /settings заново.", show_alert=True)
            return
        msg = query.message
        if (msg is None or getattr(msg, "is_accessible", True) is False
                or getattr(getattr(msg, "chat", None), "id", None) != state.chat_id
                or (getattr(msg, "message_thread_id", None) or 0) != state.thread_id
                or getattr(msg, "message_id", None) != state.message_id
                or getattr(query.from_user, "id", None) != state.user_id):
            await query.answer("Эта настройка открыта другим пользователем или в другом сообщении.", show_alert=True)
            return
        if not await authorize(msg, state.user_id):
            await query.answer("Настройку группы может изменить только её администратор.", show_alert=True)
            return
        value = parts[2]
        if value == "cancel":
            self.sessions.pop(state.nonce, None)
            await query.answer()
            await msg.edit_text("Настройка отменена. Прежние значения сохранены.", reply_markup=None)
            return
        allowed = {v for _, v in CHOICES.get(state.step, [])}
        if state.step == "language" and state.values["language"] not in {v for _, v in CHOICES["language"]}:
            allowed.add("keep")
        if value not in allowed:
            await query.answer("Этот вариант больше не доступен. Используй текущие кнопки.", show_alert=True)
            return
        if state.step == "language" and value == "custom":
            state.step = "custom_language"
        else:
            if state.step == "technical_details":
                state.values[state.step] = value == "technical"
            elif state.step == "context_enabled":
                state.values[state.step] = value == "on"
            elif value != "keep":
                state.values[state.step] = value
            state.step = self.next_step(state.step)
        state.updated = self.clock()
        await query.answer()
        await self.display_or_save(state, msg)

    @staticmethod
    def next_step(step):
        index = STEPS.index(step) + 1
        return STEPS[index] if index < len(STEPS) else "done"

    async def display_or_save(self, state, message):
        if state.step == "done":
            values = {name: state.values[name] for name in STEPS}
            self.storage.save_profile(state.scope_type, state.scope_id, **values)
            self.sessions.pop(state.nonce, None)
            if self.on_saved is not None:
                self.on_saved(state.scope_type, state.scope_id)
            language_label = state.values["language"][:80]
            if len(state.values["language"]) > 80:
                language_label += "…"
            await message.edit_text(
                "✅ Настройки сохранены. Отправь голосовое или кружочек!\n\n"
                f"Язык / стиль: {html.escape(language_label)}\n"
                f"Контекст: {'включён' if state.values['context_enabled'] else 'выключен'}\n"
                f"Интерфейс: {'технический' if state.values['technical_details'] else 'простой'}\n\n"
                "/settings — настроить заново; /help — все команды.",
                parse_mode="HTML", reply_markup=None)
        else:
            text, keyboard = self.render(state)
            await message.edit_text(text, reply_markup=keyboard)

    async def language_message(self, message, authorize):
        self.purge()
        state = next((s for s in self.sessions.values() if s.chat_id == message.chat.id
                      and s.user_id == message.from_user.id and s.step == "custom_language"
                      and s.thread_id == (getattr(message, "message_thread_id", None) or 0)), None)
        if state is None:
            return False
        if not await authorize(message, state.user_id):
            self.sessions.pop(state.nonce, None)
            await message.reply_text("Настройка группы доступна только её администратору.")
            return True
        value = (message.text or "").strip()
        if not value or len(value) > 200 or any(ord(c) < 32 for c in value):
            await message.reply_text("Нужен язык или стиль одним сообщением до 200 символов.")
            return True
        state.values["language"] = value
        state.step = "transcription_type"
        state.updated = self.clock()
        text, keyboard = self.render(state)
        sent = await message.reply_text(text, reply_markup=keyboard)
        state.message_id = sent.message_id
        return True

    def cancel(self, chat_id, user_id):
        for nonce, state in list(self.sessions.items()):
            if state.chat_id == chat_id and state.user_id == user_id:
                self.sessions.pop(nonce, None)
