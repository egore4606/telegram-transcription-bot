"""Offline lifecycle, retry authorization and shutdown regressions."""
import asyncio
import sqlite3
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from telegram.error import Forbidden

import bot
from test_audit_core import job_fixture, message


def callback(data, target=None, user_id=42):
    query = NS(data=data, message=target or message(), from_user=NS(id=user_id, is_bot=False), answer=AsyncMock())
    return NS(callback_query=query)


def source_row():
    return dict(id=9, status="failed", user_id=42, chat_id=42, telegram_message_id=1,
                telegram_file_id="fake-file", media_type="voice", duration_seconds=1,
                file_size_kb=1, scope_type="user", scope_id=42, mode="both", language="auto",
                transcription_type="clean", full_name="Fixture", username=None)


def retry_storage(monkeypatch):
    store = Mock()
    store.get_processing_detail.return_value = source_row()
    store.is_user_ignored.return_value = False
    store.is_globally_blocked.return_value = False
    store.is_group_ignored.return_value = False
    store.check_and_record_rate_limit.return_value = True
    store.create_message_processing.return_value = 10
    monkeypatch.setattr(bot, "STORAGE", store)
    monkeypatch.setattr(bot, "JOB_MANAGER", bot.JobManager())
    return store


@pytest.mark.parametrize("case", ["blocked", "ignored", "limited", "cross_chat", "admin_cross_chat", "unauthorized", "not_failed", "missing_file", "bad_media", "bad_message", "inaccessible", "admin_ignored_source"])
def test_retry_rejects_invalid_policy_before_enqueue(monkeypatch, case):
    store = retry_storage(monkeypatch)
    update = callback("retry:9")
    if case in ("blocked", "ignored", "admin_ignored_source"):
        store.is_user_ignored.return_value = True
    if case == "limited":
        store.check_and_record_rate_limit.return_value = False
    if case in ("cross_chat", "admin_cross_chat"):
        update.callback_query.message.chat.id = -200
    if case in ("admin_cross_chat", "admin_ignored_source"):
        update.callback_query.from_user.id = bot.ADMIN_USER_ID
    if case == "unauthorized":
        update.callback_query.from_user.id = 99
    if case == "not_failed":
        store.get_processing_detail.return_value["status"] = "success"
    if case == "missing_file":
        store.get_processing_detail.return_value["telegram_file_id"] = ""
    if case == "bad_media":
        store.get_processing_detail.return_value["media_type"] = "document"
    if case == "bad_message":
        store.get_processing_detail.return_value["telegram_message_id"] = 0
    if case == "inaccessible":
        update.callback_query.message.is_accessible = False
    enqueue = AsyncMock(return_value="started")
    monkeypatch.setattr(bot, "enqueue_retry_processing", enqueue)
    asyncio.run(bot.handle_retry_callback(update, NS()))
    enqueue.assert_not_awaited()
    update.callback_query.answer.assert_awaited_once()


@pytest.mark.parametrize("admin", [False, True])
def test_retry_owner_admin_and_concurrent_click_claim(monkeypatch, admin):
    store = retry_storage(monkeypatch)
    manager = bot.JOB_MANAGER
    user_id = bot.ADMIN_USER_ID if admin else 42
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def enqueue(*args, **kwargs):
            calls.append(args)
            entered.set()
            if len(calls) > 1:
                release.set()
            await release.wait()
            return "started"
        monkeypatch.setattr(bot, "enqueue_retry_processing", enqueue)
        first = asyncio.create_task(bot.handle_retry_callback(callback("retry:9", user_id=user_id), NS()))
        await entered.wait()
        await bot.handle_retry_callback(callback("retry:9", user_id=user_id), NS())
        release.set()
        await first
        assert len(calls) == 1
        # Accepted work still holds its claim, not just the duration of the callback.
        await bot.handle_retry_callback(callback("retry:9", user_id=user_id), NS())
        assert len(calls) == 1
    asyncio.run(scenario())
    if admin:
        store.check_and_record_rate_limit.assert_not_called()
    else:
        store.check_and_record_rate_limit.assert_called_once()
    assert manager is bot.JOB_MANAGER


@pytest.mark.parametrize("outcome", ["rejected", "error"])
def test_retry_rejection_error_allows_later_recovery(monkeypatch, outcome):
    retry_storage(monkeypatch)
    enqueue = AsyncMock(side_effect=[RuntimeError("fixture") if outcome == "error" else "rejected", "started"])
    monkeypatch.setattr(bot, "enqueue_retry_processing", enqueue)
    async def scenario():
        await bot.handle_retry_callback(callback("retry:9"), NS())
        await bot.handle_retry_callback(callback("retry:9"), NS())
        assert enqueue.await_count == 2
    asyncio.run(scenario())


def test_retry_claim_released_on_terminal_completion(monkeypatch):
    retry_storage(monkeypatch)
    manager = bot.JOB_MANAGER
    accepted = []
    manager._start_job = lambda job: accepted.append(job)
    async def scenario():
        await bot.handle_retry_callback(callback("retry:9"), NS())
        assert len(accepted) == 1
        await bot.handle_retry_callback(callback("retry:9"), NS())
        assert len(accepted) == 1
        await manager.finish(accepted[0])
        await bot.handle_retry_callback(callback("retry:9"), NS())
        assert len(accepted) == 2
        await manager.finish(accepted[1])
    asyncio.run(scenario())


@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("case", ["valid", "old_message", "other_chat", "absent", "inaccessible", "unauthorized"])
def test_job_controls_bind_exact_processing_message(monkeypatch, admin, case):
    job = job_fixture()
    target = message(message_id=20)
    if case == "old_message":
        target.message_id = 19
    if case == "other_chat":
        target.chat.id = -200
    if case == "inaccessible":
        target.is_accessible = False
    user_id = 99 if case == "unauthorized" else bot.ADMIN_USER_ID if admin else 42
    update = callback("job:stop:1", target, user_id)
    if case == "absent":
        update.callback_query.message = None
    manager = NS(get_job=AsyncMock(return_value=job), cancel_job=AsyncMock(return_value="active_cancelling"))
    monkeypatch.setattr(bot, "JOB_MANAGER", manager)
    asyncio.run(bot.handle_job_callback(update, NS()))
    assert manager.cancel_job.await_count == (1 if case == "valid" else 0)


def processing_setup(monkeypatch):
    store = Mock()
    monkeypatch.setattr(bot, "STORAGE", store)
    manager = bot.JobManager()
    monkeypatch.setattr(bot, "JOB_MANAGER", manager)
    job = job_fixture()
    job.context.bot.get_file.return_value = NS(download_as_bytearray=AsyncMock(return_value=b"synthetic"))
    monkeypatch.setattr(bot, "call_gemini_with_retries", AsyncMock(return_value=('{"transcription":"fixture","summary":"summary"}', "fake-model")))
    return store, manager, job


@pytest.mark.parametrize("case", ["initial_db", "failure_db", "cleanup", "cancel", "delivery", "finish"])
def test_job_lifecycle_always_releases_and_drains(monkeypatch, case):
    store, manager, job = processing_setup(monkeypatch)
    started, release = asyncio.Event(), asyncio.Event()
    if case == "initial_db":
        store.update_message_processing.side_effect = sqlite3.OperationalError("database unavailable")
    if case == "failure_db":
        store.update_message_processing.side_effect = [None, sqlite3.OperationalError("secondary DB failure")]
        job.context.bot.get_file.side_effect = ValueError("original failure")
    if case == "cleanup":
        monkeypatch.setattr(bot, "stop_progress", AsyncMock(side_effect=RuntimeError("cleanup failed")))
    if case == "delivery":
        monkeypatch.setattr(bot, "build_final_reply_chunks", Mock(return_value=["first", "second"]))
        job.processing_message.reply_text.side_effect = Forbidden("second chunk failed")
    if case == "finish":
        real_finish = manager.finish
        async def failed_finish(value):
            await real_finish(value)
            raise RuntimeError("finish notification failed")
        manager.finish = failed_finish
    async def waiting_file(*args):
        started.set()
        await release.wait()
    if case == "cancel":
        job.context.bot.get_file.side_effect = waiting_file
    async def scenario():
        before = set(asyncio.all_tasks())
        manager.active_jobs[job.job_id] = job
        task = asyncio.create_task(bot.process_media_job(job))
        if case == "cancel":
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
        assert not manager.active_jobs
        assert job.progress is None
        assert not (set(asyncio.all_tasks()) - before)
        if case in ("initial_db", "failure_db", "cleanup", "delivery", "cancel"):
            store.increment_stats.assert_not_called()
            assert not any(call.kwargs.get("status") == "success" for call in store.update_message_processing.call_args_list)
    asyncio.run(scenario())


def test_initial_db_failure_promotes_next_queued_job(monkeypatch):
    store, manager, job = processing_setup(monkeypatch)
    store.update_message_processing.side_effect = sqlite3.OperationalError("initial failure")
    next_job = job_fixture(job_id=2)
    manager.active_jobs[1] = job
    manager.queue.append(next_job)
    started = []
    manager._start_job = lambda value: started.append(value.job_id)
    asyncio.run(bot.process_media_job(job))
    assert started == [2]


def test_manager_shutdown_owns_active_queued_jobs_and_stops_before_clients(monkeypatch):
    store, manager, job = processing_setup(monkeypatch)
    monkeypatch.setattr(bot, "MAX_ACTIVE_JOBS_GLOBAL", 1)
    async def scenario():
        entered, drained = asyncio.Event(), asyncio.Event()
        async def work(value):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                drained.set()
                await manager.finish(value)
        monkeypatch.setattr(bot, "process_media_job", work)
        await manager.submit(job)
        await entered.wait()
        queued = job_fixture(job_id=2)
        assert await manager.submit(queued) == "queued"
        async def close():
            assert drained.is_set()
            assert not manager.active_jobs and not manager.queue
        client = NS(aclose=AsyncMock(side_effect=close))
        monkeypatch.setattr(bot, "gemini_async_clients", [client])
        await bot.post_shutdown(NS())
        assert job.task.done()
        assert queued.task is None
        assert await manager.submit(job_fixture(job_id=3)) == "rejected"
        assert any(call.kwargs.get("status") == "cancelled" for call in store.update_message_processing.call_args_list)
        client.aclose.assert_awaited_once()
    asyncio.run(scenario())


def test_background_task_errors_are_consumed(monkeypatch, caplog):
    async def scenario():
        manager = bot.JobManager()
        exited = asyncio.Event()
        async def failure(job):
            exited.set()
            raise ValueError("fixture failure")
        monkeypatch.setattr(bot, "process_media_job", failure)
        observed = asyncio.Event()
        original_done = getattr(manager, "_task_done", None)
        if original_done is not None:
            def observe(task):
                original_done(task)
                observed.set()
            manager._task_done = observe
        job = job_fixture()
        await manager.submit(job)
        await exited.wait()
        if original_done is not None:
            await observed.wait()
            assert job.task._log_traceback is False
        else:
            await asyncio.gather(job.task, return_exceptions=True)
        assert "JOB TASK FAILED" in caplog.text
    asyncio.run(scenario())
