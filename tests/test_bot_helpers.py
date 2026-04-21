import asyncio
from unittest.mock import AsyncMock, Mock

import bot


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


def test_sync_bot_commands_does_not_raise_on_bot_api_error(caplog) -> None:
    app = Mock()
    app.bot = Mock()
    app.bot.set_my_commands = AsyncMock(side_effect=[RuntimeError("default fail"), RuntimeError("admin fail")])

    asyncio.run(bot.sync_bot_commands(app))

    assert app.bot.set_my_commands.await_count == 2
    assert "BOT COMMAND SYNC ERROR | scope=default" in caplog.text
    assert "BOT COMMAND SYNC ERROR | scope=admin" in caplog.text
