"""Offline privacy, command authorization and long untrusted text tests."""
import asyncio
import html
import json
import logging
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from telegram.ext import ApplicationHandlerStop

import bot
from test_audit_core import job_fixture, message, units
from test_audit_lifecycle import processing_setup


def update_fixture(target=None):
    target = target or message()
    target.text = "fixture feedback"
    target.caption = None
    return NS(message=target, effective_message=target, effective_user=target.from_user, effective_chat=target.chat)


@pytest.mark.parametrize("read", [False, True])
@pytest.mark.parametrize("value", ["<b>bad</b> & tags", "😀<&>" * 3000])
def test_language_set_and_legacy_read_are_escaped_bounded(monkeypatch, read, value):
    store = Mock()
    store.get_settings.return_value = ("both", value, "clean")
    monkeypatch.setattr(bot, "STORAGE", store)
    update = update_fixture()
    asyncio.run(bot.handle_language(update, NS(args=[] if read else [value])))
    payloads = [call.args[0] for call in update.message.reply_text.await_args_list]
    assert payloads and all(units(text) <= bot.TELEGRAM_SAFE_MESSAGE_LIMIT for text in payloads)
    assert all("<b>bad</b>" not in text for text in payloads)
    joined = "".join(html.unescape(text) for text in payloads)
    # Tags used by the bot are allowed; arbitrary user tags must remain escaped.
    assert html.escape(value.lower() if not read else value)[:30] in "".join(payloads)
    if not read:
        store.set_language.assert_called_once_with("user", 42, value.lower())
    assert joined


@pytest.mark.parametrize("handler,reader", [("handle_stats", "get_stats_snapshot"), ("handle_history", "get_recent_processing"), ("handle_last_errors", "get_recent_failed_attempts")])
@pytest.mark.parametrize("case", ["nonadmin", "admin_group", "admin_private"])
def test_global_reports_are_private_and_admin_only(monkeypatch, handler, reader, case):
    store = Mock()
    store.get_recent_processing.return_value = []
    store.get_recent_failed_attempts.return_value = []
    store.get_stats_snapshot.return_value = dict(top_users=[], global_blocked_users=[], group_ignored_count=0,
                                                 today=0, voice_total=0, video_total=0)
    monkeypatch.setattr(bot, "STORAGE", store)
    target = message(chat_type="supergroup" if case == "admin_group" else "private")
    target.from_user.id = 42 if case == "nonadmin" else bot.ADMIN_USER_ID
    asyncio.run(getattr(bot, handler)(update_fixture(target), NS(args=[])))
    assert getattr(store, reader).call_count == (1 if case == "admin_private" else 0)
    target.reply_text.assert_awaited()


@pytest.mark.parametrize("fail", [False, True])
def test_feedback_long_metadata_text_and_pending_delivery(monkeypatch, fail, caplog):
    store = Mock()
    monkeypatch.setattr(bot, "STORAGE", store)
    target = message()
    target.from_user.full_name = "name" + "😀<&>" * 1000
    target.chat.title = "title" + "😀<&>" * 1000
    target.chat.type = "supergroup"
    text = "FEEDBACK_CONTENT_MARKER " + "😀<&> " * 2000
    send = AsyncMock(side_effect=[None, RuntimeError("fixture failure")] if fail else None)
    caplog.set_level(logging.INFO, logger="bot")
    asyncio.run(bot.forward_feedback(update_fixture(target), NS(bot=NS(send_message=send)), text))
    chunks = [call.kwargs["text"] for call in send.await_args_list]
    assert all(units(chunk) <= bot.TELEGRAM_SAFE_MESSAGE_LIMIT for chunk in chunks)
    if fail:
        store.clear_pending_feedback.assert_not_called()
    else:
        store.clear_pending_feedback.assert_called_once()
        # All feedback codepoints survive. Metadata is separate from content blocks.
        assert sum(html.unescape(chunk).count("😀") for chunk in chunks) == 4000
        assert "FEEDBACK_CONTENT_MARKER" not in caplog.text
        assert target.from_user.full_name not in caplog.text


def test_split_preserves_whitespace_and_valid_entities():
    text = "  😀<&>\n" * 2000 + "end  "
    pieces = bot.split_plain_text_for_html(text, 3000)
    assert "".join(pieces) == text
    assert all(units(html.escape(piece)) <= 3000 for piece in pieces)


@pytest.mark.parametrize("handler", ["handle_start", "handle_help", "handle_myid", "handle_feedback", "handle_language", "handle_ignore", "handle_stats", "handle_pending_feedback_message", "handle_stop", "handle_next"])
@pytest.mark.parametrize("case", ["absent_message", "absent_user", "anonymous", "bot_sender"])
def test_commands_without_usable_human_sender_do_nothing(monkeypatch, handler, case):
    store = Mock()
    monkeypatch.setattr(bot, "STORAGE", store)
    update = update_fixture()
    if case == "absent_message":
        update.message = None
    if case == "absent_user":
        update.message.from_user = None
        update.effective_user = None
    if case == "anonymous":
        update.message.sender_chat = NS(id=-100)
    if case == "bot_sender":
        update.message.from_user.is_bot = True
    asyncio.run(getattr(bot, handler)(update, NS(args=[])))
    assert store.mock_calls == []


def test_guard_stops_dispatch_for_anonymous_sender(monkeypatch):
    store = Mock()
    monkeypatch.setattr(bot, "STORAGE", store)
    target = message(chat_type="supergroup")
    target.sender_chat = NS(id=-100)
    update = update_fixture(target)
    update.message.text = "/ignore"
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(bot.guard_update(update, NS()))
    assert store.mock_calls == []


def test_ignore_channel_target_is_refused_without_policy_write(monkeypatch):
    store = Mock()
    monkeypatch.setattr(bot, "STORAGE", store)
    target = message(chat_type="supergroup")
    target.chat.get_member = AsyncMock(return_value=NS(status="administrator"))
    target.reply_to_message = NS(from_user=None, sender_chat=NS(id=-100))
    asyncio.run(bot.handle_ignore(update_fixture(target), NS(args=[])))
    store.toggle_group_ignore.assert_not_called()
    target.reply_text.assert_awaited_once()


def test_success_feedback_and_unhandled_logs_exclude_content(monkeypatch, caplog):
    store, manager, job = processing_setup(monkeypatch)
    marker = "PRIVATE_CONTENT_MARKER_6ae8"
    job.user_name = job.chat_title = job.language = marker
    monkeypatch.setattr(bot, "call_gemini_with_retries", AsyncMock(return_value=(json.dumps({"transcription": marker, "summary": marker}), "fake-model")))
    caplog.set_level(logging.INFO, logger="bot")
    async def scenario():
        await bot.process_media_job(job)
        update = update_fixture()
        update.message.text = marker
        await bot.handle_error(update, NS(error=ValueError(marker)))
    asyncio.run(scenario())
    assert marker not in caplog.text
    assert "JOB SUCCESS" in caplog.text
    assert "UNHANDLED ERROR" in caplog.text


def test_sdk_credentials_are_redacted_before_storage_and_logs(monkeypatch, caplog):
    secret = "FAKE_CONFIGURED_SECRET_6ae8"
    token = "FAKE_CONFIGURED_TOKEN_6ae8"
    monkeypatch.setattr(bot, "GEMINI_API_KEY", secret)
    monkeypatch.setattr(bot, "GEMINI_API_KEY_2", "FAKE_BACKUP_SECRET_6ae8")
    monkeypatch.setattr(bot, "TELEGRAM_TOKEN", token)
    monkeypatch.setattr(bot, "gemini_api_keys", [secret])
    store = Mock()
    monkeypatch.setattr(bot, "STORAGE", store)
    error = RuntimeError("503 " + secret + " " + token + " FAKE_BACKUP_SECRET_6ae8")
    client = NS(models=NS(generate_content=AsyncMock(side_effect=error)))
    monkeypatch.setattr(bot, "gemini_async_clients", [client])
    async def scenario():
        with pytest.raises(RuntimeError):
            await bot.call_gemini([], "fake-model", 1, {"attempt_no": 1})
        await bot.handle_error(update_fixture(), NS(error=error))
    asyncio.run(scenario())
    persisted = store.add_model_attempt.call_args.kwargs["error_text"]
    assert all(value not in persisted + caplog.text for value in (secret, token, "FAKE_BACKUP_SECRET_6ae8"))
    assert len(persisted) <= 1000
