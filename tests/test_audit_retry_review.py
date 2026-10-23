"""Regressions for independent review: callback provenance, recovery, log labels."""
import asyncio
import ast
from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from telegram import CallbackQuery, Chat, Message, Update, User
from telegram.ext import CallbackQueryHandler, MessageHandler, filters

import bot
from storage import Storage
from test_audit_core import job_fixture, message


@pytest.fixture
def retry_state(tmp_path, monkeypatch):
    store = Storage(str(tmp_path / "retry.sqlite3"))
    store.init_db()
    store.upsert_user(42, "Fixture source", None)
    store.upsert_user(99, "Fixture other", None)
    store.upsert_chat(-100, "supergroup", "Fixture group", None)
    source_id = store.create_message_processing(
        telegram_message_id=1, chat_id=-100, user_id=42, media_type="voice",
        telegram_file_id="fake-file", duration_seconds=1, file_size_kb=1,
        scope_type="chat", scope_id=-100, mode="both", language="auto", status="failed",
    )
    manager = bot.JobManager()
    manager._next_job_id = 8
    manager._start_job = Mock()  # Real admission, no media/model worker.
    monkeypatch.setattr(bot, "STORAGE", store)
    monkeypatch.setattr(bot, "JOB_MANAGER", manager)
    return store, manager, source_id


def stateful_target(source_id):
    target = message(chat_id=-100, message_id=200, chat_type="supergroup")
    target.reply_markup = bot.retry_keyboard(source_id)

    async def edit(text, **kwargs):
        target.reply_markup = kwargs.get("reply_markup")
        target.text = text

    target.edit_text = AsyncMock(side_effect=edit)
    return target


def query_for(target, source_id, user_id=42):
    return NS(callback_query=NS(data=f"retry:{source_id}", message=target,
                               from_user=NS(id=user_id, is_bot=False), answer=AsyncMock()))


@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("kind", ["other_active", "other_queued", "mismatch", "absent", "busy_retry_markup"])
def test_retry_requires_server_message_provenance(retry_state, admin, kind):
    store, manager, source_id = retry_state
    fake_bot = NS(edit_message_text=AsyncMock(), answer_callback_query=AsyncMock())
    markup = bot.job_keyboard(7)
    if kind == "mismatch":
        markup = bot.retry_keyboard(source_id + 1)
    elif kind == "absent":
        markup = None
    elif kind == "busy_retry_markup":
        markup = bot.retry_keyboard(source_id)
    target = Message(message_id=200, date=datetime.now(timezone.utc),
                     chat=Chat(-100, "supergroup"), from_user=User(777, "Fixture bot", True),
                     text="Working for another fixture user", reply_markup=markup)
    target.set_bot(fake_bot)
    if kind in ("other_active", "other_queued", "busy_retry_markup"):
        job = job_fixture(job_id=7, chat_id=-100, user_id=99, processing_message=target)
        if kind == "other_queued":
            manager.queue.append(job)
        else:
            manager.active_jobs[7] = job
    query = CallbackQuery(id="fixture-query", from_user=User(bot.ADMIN_USER_ID if admin else 42, "Fixture", False),
                          chat_instance="fixture-instance", message=target, data=f"retry:{source_id}")
    query.set_bot(fake_bot)
    update = Update(1, callback_query=query)
    assert not MessageHandler(filters.ALL, bot.guard_update).check_update(update)
    assert CallbackQueryHandler(bot.handle_retry_callback, pattern=r"^retry:\d+$").check_update(update)
    asyncio.run(bot.handle_retry_callback(update, NS()))
    fake_bot.edit_message_text.assert_not_awaited()
    manager._start_job.assert_not_called()
    assert not manager._retry_sources
    assert len(store.get_recent_processing(limit=10)) == 1


@pytest.mark.parametrize("failure", ["queue_full", "db_error", "cancel_edit", "cancel_submit"])
def test_retry_admission_restores_button_and_recovers(retry_state, monkeypatch, failure):
    store, manager, source_id = retry_state
    target = stateful_target(source_id)
    create = store.create_message_processing
    if failure == "queue_full":
        monkeypatch.setattr(bot, "MAX_ACTIVE_JOBS_GLOBAL", 1)
        monkeypatch.setattr(bot, "MAX_QUEUED_JOBS", 0)
        manager.active_jobs[7] = job_fixture(job_id=7, chat_id=-100, user_id=99)
    elif failure == "db_error":
        monkeypatch.setattr(store, "create_message_processing", Mock(side_effect=sqlite3.OperationalError("fixture admission error")))

    async def scenario():
        submit = manager.submit
        if failure in ("cancel_edit", "cancel_submit"):
            entered = asyncio.Event()
            edit = target.edit_text.side_effect

            async def first_blocks(text, **kwargs):
                await edit(text, **kwargs)
                if target.edit_text.await_count == 1 and failure == "cancel_edit":
                    entered.set()
                    await asyncio.Event().wait()

            target.edit_text.side_effect = first_blocks
            if failure == "cancel_submit":
                await manager._lock.acquire()
                async def blocked_submit(job):
                    entered.set()
                    return await submit(job)

                monkeypatch.setattr(manager, "submit", blocked_submit)
            task = asyncio.create_task(bot.handle_retry_callback(query_for(target, source_id), NS()))
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            if failure == "cancel_submit":
                manager._lock.release()
                monkeypatch.setattr(manager, "submit", submit)
            target.edit_text.side_effect = edit
        else:
            await bot.handle_retry_callback(query_for(target, source_id), NS())
        assert not manager._retry_sources
        assert not manager.retry_has_job(source_id)
        assert target.reply_markup == bot.retry_keyboard(source_id)
        # A normal user clicks the actual server-visible remaining button.
        manager.active_jobs.clear()
        monkeypatch.setattr(store, "create_message_processing", create)
        button = target.reply_markup.inline_keyboard[0][0]
        update = query_for(target, source_id)
        update.callback_query.data = button.callback_data
        await bot.handle_retry_callback(update, NS())
        assert manager.retry_has_job(source_id)
        assert target.reply_markup != bot.retry_keyboard(source_id)
        manager._start_job.assert_called_once()
        await manager.finish(next(iter(manager.active_jobs.values())))

    asyncio.run(scenario())


def test_retry_callback_cancel_after_admission_never_restores_over_active_job(retry_state, monkeypatch):
    _, manager, source_id = retry_state
    target = stateful_target(source_id)
    submit = manager.submit

    async def admitted_then_cancelled(job):
        assert await submit(job) == "started"
        raise asyncio.CancelledError()

    monkeypatch.setattr(manager, "submit", admitted_then_cancelled)

    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await bot.handle_retry_callback(query_for(target, source_id), NS())
        assert manager.retry_has_job(source_id)
        assert target.reply_markup == bot.job_keyboard(8)
        assert source_id in manager._retry_sources
        await manager.finish(next(iter(manager.active_jobs.values())))
        assert not manager._retry_sources

    asyncio.run(scenario())


@pytest.mark.parametrize("policy", ["global", "group", "rate"])
@pytest.mark.parametrize("caption", [False, True])
@pytest.mark.parametrize("known", [False, True])
def test_policy_logs_only_allowlisted_command_labels(monkeypatch, caplog, policy, caption, known):
    store = Mock()
    store.is_globally_blocked.return_value = policy == "global"
    store.is_group_ignored.return_value = policy == "group"
    store.check_and_record_command_rate_limit.return_value = (False, False)
    monkeypatch.setattr(bot, "STORAGE", store)
    target = message(chat_type="supergroup")
    marker = "PRIVATE_SLASH_MARKER_b8f9"
    token = "help" if known else marker
    text = f"/{token}@fixture_bot"
    target.text = None if caption else text
    target.caption = text if caption else None
    update = NS(message=target, effective_message=target, effective_user=target.from_user, effective_chat=target.chat)
    caplog.set_level(logging.INFO, logger="bot")
    with pytest.raises(bot.ApplicationHandlerStop):
        asyncio.run(bot.guard_update(update, NS()))
    assert marker.lower() not in caplog.text.lower()
    assert "command=" + ("help" if known else "unknown") in caplog.text


@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("queued", [False, True])
def test_valid_retry_real_admission_owner_and_admin(retry_state, monkeypatch, admin, queued):
    store, manager, source_id = retry_state
    target = stateful_target(source_id)
    if queued:
        monkeypatch.setattr(bot, "MAX_ACTIVE_JOBS_GLOBAL", 1)
        manager.active_jobs[7] = job_fixture(job_id=7, user_id=99)
    quota = Mock(wraps=store.check_and_record_rate_limit)
    monkeypatch.setattr(store, "check_and_record_rate_limit", quota)

    async def scenario():
        await bot.handle_retry_callback(query_for(target, source_id, bot.ADMIN_USER_ID if admin else 42), NS())
        assert manager.retry_has_job(source_id)
        job = manager.queue[0] if queued else manager.active_jobs[8]
        assert job.admitted
        assert job.processing_message is target
        assert job.user_id == 42
        assert target.reply_markup == bot.job_keyboard(job.job_id)
        assert source_id in manager._retry_sources
        assert len(store.get_recent_processing(limit=10)) == 2

    asyncio.run(scenario())
    assert quota.call_count == (0 if admin else 1)


@pytest.mark.parametrize("queued", [False, True])
def test_retry_admission_cancel_during_queue_ui_never_restores(retry_state, monkeypatch, queued):
    _, manager, source_id = retry_state
    target = stateful_target(source_id)
    if queued:
        monkeypatch.setattr(bot, "MAX_ACTIVE_JOBS_GLOBAL", 1)
        manager.active_jobs[7] = job_fixture(job_id=7, user_id=99)
    submit = manager.submit

    async def scenario():
        entered = asyncio.Event()

        async def queue_ui():
            entered.set()
            await asyncio.Event().wait()

        async def after_active_admission(job):
            result = await submit(job)
            entered.set()
            await asyncio.Event().wait()
            return result

        if queued:
            monkeypatch.setattr(manager, "refresh_queue_positions", queue_ui)
        else:
            monkeypatch.setattr(manager, "submit", after_active_admission)
        task = asyncio.create_task(bot.handle_retry_callback(query_for(target, source_id), NS()))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert manager.retry_has_job(source_id)
        assert target.reply_markup == bot.job_keyboard(8)
        assert target.edit_text.await_count == 1
        assert source_id in manager._retry_sources

    asyncio.run(scenario())


def test_recovery_holds_claim_until_retry_keyboard_is_restored(retry_state, monkeypatch):
    store, manager, source_id = retry_state
    target = stateful_target(source_id)
    monkeypatch.setattr(store, "create_message_processing", Mock(side_effect=sqlite3.OperationalError("fixture")))
    edit = target.edit_text.side_effect

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def restoring(text, **kwargs):
            if kwargs.get("reply_markup") == bot.retry_keyboard(source_id):
                entered.set()
                await release.wait()
            await edit(text, **kwargs)

        target.edit_text.side_effect = restoring
        task = asyncio.create_task(bot.handle_retry_callback(query_for(target, source_id), NS()))
        await entered.wait()
        assert source_id in manager._retry_sources
        # A stale callback still carrying the original server keyboard cannot
        # take the claim while the original target is being restored.
        await bot.handle_retry_callback(query_for(stateful_target(source_id), source_id), NS())
        assert store.create_message_processing.call_count == 1
        release.set()
        await task
        assert not manager._retry_sources
        assert target.reply_markup == bot.retry_keyboard(source_id)

    asyncio.run(scenario())


def test_command_log_allowlist_matches_registered_commands():
    tree = ast.parse(Path(bot.__file__).read_text())
    registered = {node.args[0].value for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id == "CommandHandler" and isinstance(node.args[0], ast.Constant)}
    assert registered == bot.LOG_COMMAND_NAMES


def test_restore_failure_does_not_keep_claim_or_mask_cancellation(retry_state):
    _, manager, source_id = retry_state
    target = stateful_target(source_id)
    target.edit_text.side_effect = [asyncio.CancelledError(), bot.TelegramError("fixture restore error")]

    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await bot.handle_retry_callback(query_for(target, source_id), NS())
        assert not manager._retry_sources
        assert not manager.retry_has_job(source_id)
        assert target.edit_text.await_count == 2

    asyncio.run(scenario())


def test_completed_admission_does_not_restore_or_release_a_new_claim(retry_state, monkeypatch):
    _, manager, source_id = retry_state
    target = stateful_target(source_id)
    submit = manager.submit
    new_identity = (-100, 1, "voice")

    async def completed_then_error(job):
        assert await submit(job) == "started"
        await manager.finish(job)
        assert manager.claim_retry(source_id, new_identity)
        raise RuntimeError("fixture UI error after completed admission")

    monkeypatch.setattr(manager, "submit", completed_then_error)
    asyncio.run(bot.handle_retry_callback(query_for(target, source_id), NS()))
    assert target.edit_text.await_count == 1
    assert manager._retry_sources.get(source_id) is new_identity
