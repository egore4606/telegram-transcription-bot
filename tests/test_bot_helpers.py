import asyncio
from unittest.mock import AsyncMock, Mock

import bot
import pytest
from telegram.ext import ApplicationHandlerStop
from telegram.error import RetryAfter


class GuardStorage:
    def __init__(
        self,
        *,
        globally_blocked: bool = False,
        group_ignored: bool = False,
        command_rate_result: tuple[bool, bool] = (True, False),
    ) -> None:
        self.globally_blocked = globally_blocked
        self.group_ignored = group_ignored
        self.command_rate_result = command_rate_result
        self.cleared_pending_feedback: list[tuple[int, int]] = []
        self.recorded_commands: list[str] = []
        self.admin_blocks: list[tuple[int, int]] = []
        self.removed_all: list[int] = []
        self.remove_all_result = {"global": 0, "group": 0, "total": 0}

    def upsert_user(self, *args) -> None:
        return None

    def upsert_chat(self, *args) -> None:
        return None

    def is_globally_blocked(self, user_id: int) -> bool:
        return self.globally_blocked

    def is_group_ignored(self, chat_id: int, user_id: int) -> bool:
        return self.group_ignored

    def clear_pending_feedback(self, chat_id: int, user_id: int) -> None:
        self.cleared_pending_feedback.append((chat_id, user_id))

    def check_and_record_command_rate_limit(self, *args, **kwargs) -> tuple[bool, bool]:
        self.recorded_commands.append(kwargs["command_name"])
        return self.command_rate_result

    def add_admin_block(self, target_user_id: int, admin_user_id: int) -> None:
        self.admin_blocks.append((target_user_id, admin_user_id))

    def remove_all_blocks(self, target_user_id: int) -> dict[str, int]:
        self.removed_all.append(target_user_id)
        return self.remove_all_result

    def list_global_blocked_user_ids(self) -> list[int]:
        return []

    def list_global_blocks(self) -> list[dict[str, object]]:
        return []

    def list_group_ignores(self) -> list[dict[str, object]]:
        return []


def make_guard_update(*, text: str, chat_type: str = "private", user_id: int = 42):
    user = Mock()
    user.id = user_id
    user.full_name = "Test User"
    user.username = "tester"

    chat = Mock()
    chat.id = user_id if chat_type == "private" else -100
    chat.type = chat_type
    chat.title = "Test Group" if chat_type != "private" else None
    chat.username = None
    chat.get_member = AsyncMock()

    message = Mock()
    message.text = text
    message.caption = None
    message.from_user = user
    message.chat = chat
    message.reply_text = AsyncMock()

    update = Mock()
    update.effective_user = user
    update.effective_chat = chat
    update.effective_message = message
    update.message = message
    return update, message


def test_parse_response_sections_standard_response() -> None:
    raw = "ТРАНСКРИПЦИЯ:\nПривет, мир\n\nКРАТКОЕ СОДЕРЖАНИЕ:\nКороткое summary"

    transcription, summary = bot.parse_response_sections(raw, "both")

    assert transcription == "Привет, мир"
    assert summary == "Короткое summary"


def test_parse_response_sections_tldr_response() -> None:
    raw = "КРАТКОЕ СОДЕРЖАНИЕ:\nОдно главное предложение."

    transcription, summary = bot.parse_response_sections(raw, "tldr")

    assert transcription == ""
    assert summary == "Одно главное предложение."


def test_parse_response_sections_handles_partial_response() -> None:
    raw = "КРАТКОЕ СОДЕРЖАНИЕ:\nЕсть только summary без транскрипции."

    transcription, summary = bot.parse_response_sections(raw, "both")

    assert transcription == ""
    assert summary == "Есть только summary без транскрипции."


def test_parse_response_sections_handles_nonstandard_response() -> None:
    raw = "Просто свободный текст без ожидаемых секций."

    transcription, summary = bot.parse_response_sections(raw, "both")

    assert transcription == raw
    assert summary == ""


def test_format_response_escapes_html_for_both_mode() -> None:
    raw = "ТРАНСКРИПЦИЯ:\n<hello> & bye\n\nКРАТКОЕ СОДЕРЖАНИЕ:\nUse <b>tags</b>"

    formatted = bot.format_response(raw, "both")

    assert "📝 <b>Транскрипция:</b>" in formatted
    assert "📌 <b>Краткое содержание:</b>" in formatted
    assert "&lt;hello&gt; &amp; bye" in formatted
    assert "Use &lt;b&gt;tags&lt;/b&gt;" in formatted


def test_format_response_transcription_only_mode() -> None:
    raw = "ТРАНСКРИПЦИЯ:\nТолько текст\n\nКРАТКОЕ СОДЕРЖАНИЕ:\nНе должно попасть в ответ"

    formatted = bot.format_response(raw, "transcription_only")

    assert "Только текст" in formatted
    assert "Краткое содержание" not in formatted


def test_format_response_summary_only_mode() -> None:
    raw = "ТРАНСКРИПЦИЯ:\nНе нужен\n\nКРАТКОЕ СОДЕРЖАНИЕ:\nНужен только summary"

    formatted = bot.format_response(raw, "summary_only")

    assert "Нужен только summary" in formatted
    assert "Транскрипция" not in formatted


def test_format_response_tldr_mode() -> None:
    raw = "КРАТКОЕ СОДЕРЖАНИЕ:\nСамая важная мысль."

    formatted = bot.format_response(raw, "tldr")

    assert formatted == "💡 Самая важная мысль."


def test_build_prompt_differs_for_voice_and_video() -> None:
    voice_prompt = bot.build_prompt("voice", "auto", "both")
    video_prompt = bot.build_prompt("video", "auto", "both")

    assert "голосовое сообщение" in voice_prompt
    assert "видео-кружочек" in video_prompt
    assert "что происходит на видео" in video_prompt


def test_build_prompt_differs_for_auto_and_fixed_language() -> None:
    auto_prompt = bot.build_prompt("voice", "auto", "both")
    fixed_prompt = bot.build_prompt("voice", "de", "both")

    assert "Сохраняй язык оригинала." in auto_prompt
    assert "Переведи ответ на язык: de." in fixed_prompt


def test_build_prompt_differs_for_tldr_and_regular_modes() -> None:
    tldr_prompt = bot.build_prompt("voice", "auto", "tldr")
    regular_prompt = bot.build_prompt("voice", "auto", "both")

    assert "ОДНО короткое предложение" in tldr_prompt
    assert "Выполни две задачи" not in tldr_prompt
    assert "Выполни две задачи" in regular_prompt


def test_parse_limit_arg_default_and_clamp() -> None:
    assert bot.parse_limit_arg([], default=10, maximum=20, command_name="history") == (10, None)
    assert bot.parse_limit_arg(["50"], default=10, maximum=20, command_name="history") == (20, None)


def test_parse_limit_arg_rejects_bad_values() -> None:
    assert bot.parse_limit_arg(["0"], default=10, maximum=20, command_name="history") == (
        None,
        "Количество должно быть положительным числом.",
    )
    assert bot.parse_limit_arg(["abc"], default=10, maximum=20, command_name="history") == (
        None,
        "Использование: /history [количество]",
    )


def test_format_history_entry_escapes_and_formats_fields() -> None:
    entry = {
        "id": 7,
        "created_at": "2026-04-21T19:31:13+00:00",
        "user_id": 1,
        "full_name": "Alice <Admin>",
        "username": None,
        "chat_id": -100,
        "chat_type": "supergroup",
        "title": "Group & Friends",
        "chat_username": None,
        "media_type": "voice",
        "status": "failed",
        "model_used": "gemini-2.5-flash",
        "processing_ms": 4200,
    }

    rendered = bot.format_history_entry(entry)

    assert "<b>#7</b>" in rendered
    assert "Alice &lt;Admin&gt;" in rendered
    assert "Group &amp; Friends" in rendered
    assert "🎙 voice" in rendered
    assert "❌ failed" in rendered


def test_format_last_error_entry_escapes_error_text() -> None:
    entry = {
        "attempt_id": 11,
        "attempt_started_at": "2026-04-21T19:31:13+00:00",
        "model_name": "gemini-2.5-flash",
        "attempt_no": 3,
        "api_key_slot": "backup",
        "processing_id": 7,
        "user_id": 1,
        "full_name": "Alice",
        "username": "alice",
        "chat_id": 1,
        "chat_type": "private",
        "title": None,
        "chat_username": "alice",
        "telegram_message_id": 500,
        "attempt_error_text": "bad <tag> & boom",
    }

    rendered = bot.format_last_error_entry(entry)

    assert "Attempt #11" in rendered
    assert "@alice" in rendered
    assert "msg <code>500</code>" in rendered
    assert "bad &lt;tag&gt; &amp; boom" in rendered


def test_friendly_error_unknown_suggests_feedback() -> None:
    rendered = bot.friendly_error(RuntimeError("boom"))

    assert "Внутренняя ошибка" in rendered
    assert "/feedback" in rendered


def test_get_retry_after_seconds_from_retry_after_error() -> None:
    assert bot.get_retry_after_seconds(RetryAfter(24)) == 24


def test_processing_progress_handles_flood_control_without_crashing() -> None:
    message = Mock()
    message.message_id = 777
    message.edit_text = AsyncMock(side_effect=RetryAfter(24))
    message.reply_text = AsyncMock()
    progress = bot.ProcessingProgress(message, "⏱ Обработка...")

    asyncio.run(progress.refresh())
    asyncio.run(progress.refresh())

    assert message.edit_text.await_count == 1
    assert message.reply_text.await_count == 1


def test_deliver_processing_reply_retries_after_flood(monkeypatch) -> None:
    sleep_calls = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(bot.asyncio, "sleep", fake_sleep)

    message = Mock()
    message.message_id = 888
    message.edit_text = AsyncMock(side_effect=[RetryAfter(3), None])
    message.reply_text = AsyncMock()

    asyncio.run(bot.deliver_processing_reply(message, "<b>done</b>"))

    assert message.edit_text.await_count == 2
    assert message.reply_text.await_count == 1
    assert sleep_calls == [3]


def test_guard_blocks_group_ignored_user_command_in_group(monkeypatch) -> None:
    storage = GuardStorage(group_ignored=True)
    monkeypatch.setattr(bot, "STORAGE", storage)
    update, message = make_guard_update(text="/feedback spam", chat_type="supergroup")

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(bot.guard_update(update, Mock()))

    assert message.reply_text.await_count == 0
    assert storage.recorded_commands == []


def test_guard_allows_group_ignored_user_in_private_chat(monkeypatch) -> None:
    storage = GuardStorage(group_ignored=True)
    monkeypatch.setattr(bot, "STORAGE", storage)
    update, message = make_guard_update(text="/help", chat_type="private")

    asyncio.run(bot.guard_update(update, Mock()))

    assert message.reply_text.await_count == 0
    assert storage.recorded_commands == ["help"]


def test_guard_blocks_globally_blocked_user_everywhere(monkeypatch) -> None:
    storage = GuardStorage(globally_blocked=True)
    monkeypatch.setattr(bot, "STORAGE", storage)
    update, message = make_guard_update(text="/help", chat_type="private")

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(bot.guard_update(update, Mock()))

    assert message.reply_text.await_count == 0
    assert storage.recorded_commands == []


def test_guard_does_not_forward_pending_feedback_from_group_ignored_user(monkeypatch) -> None:
    storage = GuardStorage(group_ignored=True)
    monkeypatch.setattr(bot, "STORAGE", storage)
    update, message = make_guard_update(text="this should not become feedback", chat_type="supergroup")

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(bot.guard_update(update, Mock()))

    assert storage.cleared_pending_feedback == [(-100, 42)]
    assert message.reply_text.await_count == 0


def test_guard_rate_limits_ordinary_user_command(monkeypatch) -> None:
    storage = GuardStorage(command_rate_result=(False, True))
    monkeypatch.setattr(bot, "STORAGE", storage)
    update, message = make_guard_update(text="/feedback spam", chat_type="private")

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(bot.guard_update(update, Mock()))

    assert storage.recorded_commands == ["feedback"]
    message.reply_text.assert_awaited_once()


def test_guard_exempts_admin_from_command_rate_limit(monkeypatch) -> None:
    storage = GuardStorage(command_rate_result=(False, True))
    monkeypatch.setattr(bot, "STORAGE", storage)
    update, _ = make_guard_update(text="/stats", chat_type="private", user_id=bot.ADMIN_USER_ID)

    asyncio.run(bot.guard_update(update, Mock()))

    assert storage.recorded_commands == []


def test_handle_block_rejects_group_usage(monkeypatch) -> None:
    storage = GuardStorage()
    monkeypatch.setattr(bot, "STORAGE", storage)
    update, message = make_guard_update(text="/block 42", chat_type="supergroup", user_id=bot.ADMIN_USER_ID)
    context = Mock()
    context.args = ["42"]

    asyncio.run(bot.handle_block(update, context))

    assert storage.admin_blocks == []
    message.reply_text.assert_awaited_once()
    assert "личном чате" in message.reply_text.await_args.args[0]


def test_handle_unblock_removes_all_blocks_in_private(monkeypatch) -> None:
    storage = GuardStorage()
    storage.remove_all_result = {"global": 1, "group": 2, "total": 3}
    monkeypatch.setattr(bot, "STORAGE", storage)
    update, message = make_guard_update(text="/unblock 42", chat_type="private", user_id=bot.ADMIN_USER_ID)
    context = Mock()
    context.args = ["42"]

    asyncio.run(bot.handle_unblock(update, context))

    assert storage.removed_all == [42]
    message.reply_text.assert_awaited_once()
    assert "Снято групповых игноров" in message.reply_text.await_args.args[0]


def test_sync_bot_commands_does_not_raise_on_bot_api_error(caplog) -> None:
    app = Mock()
    app.bot = Mock()
    app.bot.set_my_commands = AsyncMock(side_effect=[RuntimeError("default fail"), RuntimeError("admin fail")])

    asyncio.run(bot.sync_bot_commands(app))

    assert app.bot.set_my_commands.await_count == 2
    assert "BOT COMMAND SYNC ERROR | scope=default" in caplog.text
    assert "BOT COMMAND SYNC ERROR | scope=admin" in caplog.text
