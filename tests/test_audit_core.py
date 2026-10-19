"""Offline regressions for progress, delivery, storage and structured output."""
import asyncio
from datetime import timedelta
import html
import json
import sqlite3
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

import bot
from storage import Storage


def message(chat_id=42, message_id=10, chat_type="private"):
    return NS(chat=NS(id=chat_id, type=chat_type, title=None), chat_id=chat_id,
              message_id=message_id, message_thread_id=None, sender_chat=None,
              from_user=NS(id=42, full_name="Fixture", username="fixture", is_bot=False),
              edit_text=AsyncMock(), reply_text=AsyncMock(), delete=AsyncMock())


def job_fixture(**overrides):
    values = dict(job_id=1, context=NS(bot=NS(get_file=AsyncMock())), message=message(),
                  processing_message=message(message_id=20), media_type="voice", media_file_id="fake-file",
                  mime_type="audio/ogg", progress_text="Working", media_emoji="🎙", duration_seconds=1,
                  duration_str="0:01", file_size_kb=1, scope_type="user", scope_id=42, mode="both",
                  language="auto", transcription_type="clean", chat_id=42, chat_title="Fixture chat",
                  user_id=42, user_name="Fixture user", user_username="fixture", message_processing_id=1)
    values.update(overrides)
    return bot.MediaJob(**values)


@pytest.mark.parametrize("error", [TimedOut(), NetworkError("offline"), Forbidden("offline"), BadRequest("offline")])
def test_progress_telegram_errors_are_retryable_best_effort(error):
    async def scenario():
        target = message()
        target.edit_text.side_effect = [error, None]
        progress = bot.ProcessingProgress(target, "Working")
        await progress.set_status_text("Next")
        assert progress._last_rendered_text == ""
        await progress.refresh()
        assert progress._last_rendered_text == progress.render()
        assert target.edit_text.await_count == 2
        target.reply_text.assert_not_awaited()
    asyncio.run(scenario())


def test_progress_programming_errors_propagate():
    target = message()
    target.edit_text.side_effect = RuntimeError("programming defect")
    with pytest.raises(RuntimeError, match="programming defect"):
        asyncio.run(bot.ProcessingProgress(target, "Working").refresh())


def test_fallback_survives_failed_progress_edit(monkeypatch):
    target = message()
    target.edit_text.side_effect = TimedOut()
    monkeypatch.setattr(bot, "GEMINI_MODEL_CHAIN", ["first", "second"])
    call = AsyncMock(side_effect=[RuntimeError("503 unavailable"), '{"transcription":"ok","summary":"ok"}'])
    monkeypatch.setattr(bot, "call_gemini", call)
    result = asyncio.run(bot.call_gemini_with_retries([], bot.ProcessingProgress(target, "Working"), 1,
                                                    {"attempt_no": 1, "models_tried": []}))
    assert result[1] == "second"
    assert call.await_count == 2


@pytest.mark.parametrize("control", ["outer", "stop", "next", "timeout", "success", "error"])
def test_request_and_watchers_are_drained(control):
    async def scenario():
        before = set(asyncio.all_tasks())
        entered, released, request_exit = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def request():
            entered.set()
            try:
                await released.wait()
                if control == "error":
                    raise ValueError("fixture error")
                return "result"
            finally:
                request_exit.set()
        request_task = asyncio.create_task(request())
        job = NS(cancel_event=asyncio.Event(), next_model_event=asyncio.Event())
        waiter = asyncio.create_task(bot.wait_for_model_response(request_task, job, timeout=0 if control == "timeout" else 20))
        await entered.wait()
        if control == "outer":
            waiter.cancel()
            expected = asyncio.CancelledError
        elif control == "stop":
            job.cancel_event.set()
            expected = bot.JobCancelled
        elif control == "next":
            job.next_model_event.set()
            expected = bot.NextModelRequested
        elif control == "timeout":
            expected = TimeoutError
        elif control == "error":
            released.set()
            expected = ValueError
        else:
            released.set()
            expected = None
        try:
            if expected:
                with pytest.raises(expected):
                    await waiter
            else:
                assert await waiter == "result"
            assert request_exit.is_set()
            assert request_task.done()
            assert not (set(asyncio.all_tasks()) - before)
        finally:
            request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize("value,expected", [(3, 3), (1.1, 2), (0.1, 1), (timedelta(seconds=3.2), 4)])
def test_retry_after_rounds_up(value, expected, monkeypatch):
    monkeypatch.setenv("PTB_TIMEDELTA", "1")
    assert bot.get_retry_after_seconds(RetryAfter(value)) == expected


def test_retry_after_string_fraction():
    assert bot.get_retry_after_seconds(RuntimeError("Retry in 2.2 seconds")) == 3


def test_storage_closes_success_and_rollback(tmp_path):
    store = Storage(str(tmp_path / "test.sqlite3"))
    with store._connect() as connection:
        connection.execute("CREATE TABLE example (value TEXT)")
        connection.execute("INSERT INTO example VALUES ('keep')")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with pytest.raises(ValueError):
        with store._connect() as failed:
            failed.execute("INSERT INTO example VALUES ('rollback')")
            raise ValueError("body")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        failed.execute("SELECT 1")
    with store._connect() as check:
        assert [row[0] for row in check.execute("SELECT * FROM example")] == ["keep"]


def test_storage_setup_error_closes_connection(tmp_path, monkeypatch):
    connection = Mock()
    connection.execute.side_effect = sqlite3.OperationalError("pragma failed")
    monkeypatch.setattr(sqlite3, "connect", Mock(return_value=connection))
    with pytest.raises(sqlite3.OperationalError):
        with Storage(str(tmp_path / "test.sqlite3"))._connect():
            pytest.fail("setup should fail")
    connection.close.assert_called_once()


def test_storage_readonly_rejects_writes(tmp_path):
    path = str(tmp_path / "test.sqlite3")
    Storage(path).init_db()
    readonly = Storage(path, read_only=True)
    assert readonly.get_recent_processing(limit=10) == []
    with pytest.raises(sqlite3.OperationalError):
        readonly.set_language("user", 42, "en")


def test_followup_delivery_failure_propagates():
    target = message()
    target.reply_text.side_effect = Forbidden("cannot send second chunk")
    with pytest.raises(Forbidden):
        asyncio.run(bot.deliver_processing_reply(target, ["first", "second"]))
    target.edit_text.assert_awaited_once()


def test_native_fallback_does_not_duplicate_confirmed_prefix():
    async def scenario():
        job = job_fixture()
        job.message.reply_text.side_effect = [None, Forbidden("second failed")]
        progress = bot.ProcessingProgress(job.processing_message, "Working")
        progress._native_live_draft_used = True
        await bot.deliver_job_reply(job, progress, ["first", "second", "third"])
        assert job.processing_message.edit_text.await_args.args[0] == "second"
        assert [call.args[0] for call in job.processing_message.reply_text.await_args_list] == ["third"]
    asyncio.run(scenario())


def test_native_retry_uses_processing_target_and_cleanup_is_best_effort():
    async def scenario():
        job = job_fixture(message=None)
        job.processing_message.delete.side_effect = Forbidden("cleanup failed")
        progress = bot.ProcessingProgress(job.processing_message, "Working")
        progress._native_live_draft_used = True
        await bot.deliver_job_reply(job, progress, ["one", "two"])
        assert [call.args[0] for call in job.processing_message.reply_text.await_args_list] == ["one", "two"]
        job.processing_message.edit_text.assert_not_awaited()
    asyncio.run(scenario())


def test_native_flood_retry_and_failed_fallback(monkeypatch):
    async def scenario():
        job = job_fixture()
        progress = bot.ProcessingProgress(job.processing_message, "Working")
        progress._native_live_draft_used = True
        job.message.reply_text.side_effect = [RetryAfter(1), None, Forbidden("later")]
        job.processing_message.edit_text.side_effect = Forbidden("fallback")
        job.processing_message.reply_text.side_effect = Forbidden("fallback")
        monkeypatch.setattr(bot.asyncio, "sleep", AsyncMock())
        with pytest.raises(Forbidden):
            await bot.deliver_job_reply(job, progress, ["one", "two"])
        assert job.processing_message.edit_text.await_args.args[0] == "two"
    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["transcription", "summary"])
@pytest.mark.parametrize("value", [True, ["text"], {"text": "value"}, 7, None])
def test_structured_response_rejects_nonstring_fields(field, value):
    payload = {"transcription": "valid", "summary": "valid", field: value}
    assert bot.parse_structured_response(json.dumps(payload)) is None


@pytest.mark.parametrize("mode,transcript,summary,valid", [
    ("both", "text", "", False), ("both", "", "summary", False),
    ("summary_only", "text", "", False), ("tldr", "text", "", False),
    ("transcription_only", "", "summary", False),
    ("transcription_only", "text", "", True), ("summary_only", "", "summary", True),
    ("tldr", "", "summary", True), ("both", "text", "summary", True),
])
def test_request_validates_selected_mode(monkeypatch, mode, transcript, summary, valid):
    response = json.dumps({"transcription": transcript, "summary": summary})
    monkeypatch.setattr(bot, "gemini_async_clients", [NS(models=NS(generate_content=AsyncMock(return_value=NS(text=response))))])
    monkeypatch.setattr(bot, "STORAGE", Mock())
    job = job_fixture(mode=mode)
    async def run():
        return await bot.call_gemini([], "fake-model", 1, {"attempt_no": 1}, job)
    if valid:
        assert asyncio.run(run()) == response
    else:
        with pytest.raises(bot.InvalidStructuredResponse):
            asyncio.run(run())


def units(text):
    return len(text.encode("utf-16-le")) // 2


def test_unicode_html_chunk_and_draft_budgets():
    text = "😀<&>" * 3000
    chunks = bot.build_final_reply_chunks("🎙", "0:01", "😀" * 3000, text, "summary", "both", "1 sec")
    assert all(units(chunk) <= bot.TELEGRAM_SAFE_MESSAGE_LIMIT for chunk in chunks)
    plain = bot.split_plain_text_for_html(text, 3000)
    assert "".join(plain) == text
    assert all(units(html.escape(part)) <= 3000 for part in plain)
    progress = bot.ProcessingProgress(message(), "Working")
    progress._live_final_text = "😀" * 5000
    assert units(progress.live_draft_text()) <= bot.TELEGRAM_DRAFT_TEXT_LIMIT
