import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

import bot
from storage import Storage
from test_audit_core import message


def test_default_progress_and_errors_hide_provider_names_and_secrets():
    progress = bot.ProcessingProgress(message(), "Распознаю через Gemini Live: <code>gemini-test</code>")
    assert "gemini" not in progress.render().lower()
    assert "Live" not in progress.render()
    error = RuntimeError("503 unavailable Gemini gemini-test https://secret.invalid/ private prompt " + bot.GEMINI_API_KEY)
    assert "Gemini" not in bot.friendly_error(error)
    technical = bot.friendly_error(error, technical_details=True, model_name="gemini-test")
    assert "gemini-test" in technical
    assert "model_overloaded" in technical
    assert "RuntimeError" in technical
    assert "private prompt" not in technical and "secret.invalid" not in technical
    assert bot.GEMINI_API_KEY not in technical
    detail = bot.ProcessingProgress(message(), "<code>gemini-test</code>", technical_details=True)
    assert "gemini-test" in detail.render()
    assert "Gemini" not in bot.PUBLIC_CHANGELOG_TEXT


@pytest.fixture
def settings_store(tmp_path, monkeypatch):
    store = Storage(str(tmp_path / "ui.sqlite3"))
    store.init_db()
    monkeypatch.setattr(bot, "STORAGE", store)
    return store


@pytest.mark.parametrize("status,allowed", [("member", False), ("administrator", True), ("creator", True)])
def test_group_setting_authorization_is_explicit(settings_store, status, allowed):
    target = message(chat_id=-100, chat_type="supergroup")
    target.chat.get_member = AsyncMock(return_value=NS(status=status))
    assert asyncio.run(bot.can_manage_settings(target, 42)) is allowed
    if allowed:
        settings_store.add_admin_block(42, 123)
        assert not asyncio.run(bot.can_manage_settings(target, 42))


def test_private_settings_cannot_be_changed_from_another_chat(settings_store):
    assert asyncio.run(bot.can_manage_settings(message(chat_id=42), 42))
    assert not asyncio.run(bot.can_manage_settings(message(chat_id=42), 99))


@pytest.mark.parametrize("handler,args", [
    (bot.handle_language, ["de"]), (bot.handle_transcription_type, ["verbatim"]),
    (bot.handle_both, []), (bot.handle_details, ["technical"]),
])
def test_nonadmin_cannot_change_group_via_legacy_commands(settings_store, handler, args):
    target = message(chat_id=-100, chat_type="supergroup")
    target.chat.get_member = AsyncMock(return_value=NS(status="member"))
    update = NS(message=target, effective_user=target.from_user, effective_chat=target.chat)
    asyncio.run(handler(update, NS(args=args)))
    assert settings_store.get_settings("chat", -100) == ("both", "auto", "clean")
    assert not settings_store.get_preferences("chat", -100)["technical_details"]


def test_start_opens_owner_bound_setup_not_a_broadcast(settings_store):
    target = message()
    target.reply_text.return_value = message(message_id=20)
    update = NS(message=target, effective_user=target.from_user, effective_chat=target.chat)
    fake_bot = NS(send_message=AsyncMock())
    asyncio.run(bot.handle_start(update, NS(bot=fake_bot)))
    assert "Настроим" in target.reply_text.call_args.args[0]
    assert "reply_markup" in target.reply_text.call_args.kwargs
    assert not settings_store.get_preferences("user", 42)["setup_completed"]
    fake_bot.send_message.assert_not_awaited()
