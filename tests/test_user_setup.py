"""Offline setup, durable preferences, callback ownership and privacy defaults."""
import asyncio
import sqlite3
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from storage import Storage
from user_setup import SetupWizard


@pytest.fixture
def store(tmp_path):
    value = Storage(str(tmp_path / "settings.sqlite3"))
    value.init_db()
    return value


def message(chat_id=42, message_id=10):
    sent = NS(message_id=message_id + 1, chat=NS(id=chat_id), edit_text=AsyncMock())
    return NS(chat=NS(id=chat_id), message_id=message_id, from_user=NS(id=42),
              reply_text=AsyncMock(return_value=sent))


def test_preferences_default_off_and_do_not_change_legacy_settings(store):
    assert store.get_preferences("user", 42) == {
        "technical_details": False, "context_enabled": False, "setup_completed": False,
    }
    store.save_settings("user", 42, "tldr", "de", "verbatim")
    store.set_preference("user", 42, "context_enabled", True)
    assert store.get_settings("user", 42) == ("tldr", "de", "verbatim")
    assert store.get_preferences("user", 42)["context_enabled"] is True
    assert not store.get_preferences("chat", -100)["context_enabled"]
    with pytest.raises(ValueError):
        store.set_preference("user", 42, "invented_column", True)


def test_upgrade_v5_preserves_existing_choices_and_is_idempotent(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    store = Storage(str(path))
    store.init_db()
    store.save_settings("chat", -100, "summary_only", "uk", "verbatim")
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE interface_preferences")
        conn.execute("UPDATE schema_version SET version=5")
    store.init_db()
    store.init_db()
    assert store.get_settings("chat", -100) == ("summary_only", "uk", "verbatim")
    assert not store.get_preferences("chat", -100)["context_enabled"]


def test_wizard_commit_only_after_all_steps_and_rejects_replay(store):
    wizard = SetupWizard(store)
    msg = message()
    allowed = AsyncMock(return_value=True)

    async def scenario():
        await wizard.start(msg, 42, "user", 42)
        state = next(iter(wizard.sessions.values()))
        target = msg.reply_text.return_value
        query = NS(message=target, from_user=NS(id=42), answer=AsyncMock())
        for value in ["both", "de", "verbatim", "simple", "off"]:
            query.data = f"setup:{state.nonce}:{value}"
            await wizard.callback(query, allowed)
        assert store.get_preferences("user", 42)["setup_completed"]
        assert not store.get_preferences("user", 42)["context_enabled"]
        assert store.get_settings("user", 42) == ("both", "de", "verbatim")
        before = target.edit_text.await_count
        await wizard.callback(query, allowed)
        assert target.edit_text.await_count == before
    asyncio.run(scenario())


def test_wizard_checks_owner_message_chat_and_current_permission(store):
    wizard = SetupWizard(store)
    msg = message(chat_id=-100)
    allowed = AsyncMock(return_value=True)

    async def scenario():
        await wizard.start(msg, 42, "chat", -100)
        state = next(iter(wizard.sessions.values()))
        query = NS(message=msg.reply_text.return_value, from_user=NS(id=99),
                   data=f"setup:{state.nonce}:both", answer=AsyncMock())
        await wizard.callback(query, allowed)
        assert state.step == "mode"
        query.from_user.id = 42
        query.message = NS(message_id=999, chat=NS(id=-100))
        await wizard.callback(query, allowed)
        assert state.step == "mode"
        query.message = msg.reply_text.return_value
        allowed.return_value = False
        await wizard.callback(query, allowed)
        assert state.step == "mode"
        assert not store.get_preferences("chat", -100)["setup_completed"]
    asyncio.run(scenario())


def test_setup_expiry_custom_language_and_bounded_sessions(store):
    now = [1000.0]
    wizard = SetupWizard(store, clock=lambda: now[0], max_sessions=2)
    allowed = AsyncMock(return_value=True)
    msg = message()

    async def scenario():
        await wizard.start(msg, 42, "user", 42)
        state = next(iter(wizard.sessions.values()))
        query = NS(message=msg.reply_text.return_value, from_user=NS(id=42),
                   data=f"setup:{state.nonce}:both", answer=AsyncMock())
        await wizard.callback(query, allowed)
        query.data = f"setup:{state.nonce}:custom"
        await wizard.callback(query, allowed)
        typed = message(message_id=20)
        typed.text = "en, informal"
        assert await wizard.language_message(typed, allowed)
        assert state.values["language"] == "en, informal"
        assert state.step == "transcription_type"
        now[0] += 901
        query.data = f"setup:{state.nonce}:clean"
        await wizard.callback(query, allowed)
        assert not wizard.sessions
        for i in range(3):
            await wizard.start(message(chat_id=100+i), 42, "user", 42)
        assert len(wizard.sessions) <= 2
    asyncio.run(scenario())


def test_keeping_long_legacy_language_is_lossless_and_confirmation_is_bounded(store):
    legacy = "😀<&>" * 3000
    store.save_settings("user", 42, "tldr", legacy, "verbatim")
    wizard = SetupWizard(store)
    msg = message()

    async def scenario():
        await wizard.start(msg, 42, "user", 42)
        session = next(iter(wizard.sessions.values()))
        target = msg.reply_text.return_value
        query = NS(message=target, from_user=NS(id=42), answer=AsyncMock())
        for value in ["tldr", "keep", "verbatim", "simple", "off"]:
            query.data = f"setup:{session.nonce}:{value}"
            await wizard.callback(query, AsyncMock(return_value=True))
        assert store.get_settings("user", 42)[1] == legacy
        assert len(target.edit_text.call_args.args[0].encode("utf-16-le")) // 2 < 3800
    asyncio.run(scenario())
