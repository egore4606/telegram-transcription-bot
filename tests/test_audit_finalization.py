"""Admission cancellation, shutdown failure and final HTML checks; no services."""
import asyncio
from html.parser import HTMLParser
import html
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

import bot
from test_audit_core import job_fixture, message, units
from test_audit_lifecycle import callback, processing_setup, retry_storage


@pytest.mark.parametrize("admitted", [False, True])
def test_retry_callback_cancellation_releases_only_unowned_claim(monkeypatch, admitted):
    retry_storage(monkeypatch)
    manager = bot.JOB_MANAGER
    job = job_fixture(retry_source_id=9)
    manager._start_job = lambda value: None

    async def enqueue(*args):
        if admitted:
            assert await manager.submit(job) == "started"
        raise asyncio.CancelledError()

    monkeypatch.setattr(bot, "enqueue_retry_processing", enqueue)

    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await bot.handle_retry_callback(callback("retry:9"), NS())
        if admitted:
            assert not manager.claim_retry(9, (42, 1, "voice"))
            await manager.finish(job)
        assert manager.claim_retry(9, (42, 1, "voice"))
        manager.release_retry(9)

    asyncio.run(scenario())


def test_shutdown_drains_even_with_failed_bookkeeping_and_finish(monkeypatch):
    store, manager, job = processing_setup(monkeypatch)
    monkeypatch.setattr(bot, "MAX_ACTIVE_JOBS_GLOBAL", 1)
    entered, exited = asyncio.Event(), asyncio.Event()

    async def work(value):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()
            await manager.finish(value)

    monkeypatch.setattr(bot, "process_media_job", work)
    manager.finish = AsyncMock(side_effect=RuntimeError("finish failed"))
    store.update_message_processing.side_effect = RuntimeError("database failed")

    async def scenario():
        before = set(asyncio.all_tasks())
        await manager.submit(job)
        await entered.wait()
        queued = job_fixture(job_id=2)
        assert await manager.submit(queued) == "queued"
        client = NS(aclose=AsyncMock())
        monkeypatch.setattr(bot, "gemini_async_clients", [client])
        await bot.post_stop(NS())
        assert exited.is_set() and job.task.done()
        assert not manager.active_jobs and not manager.queue
        assert queued.task is None
        client.aclose.assert_not_awaited()
        await bot.post_shutdown(NS())
        client.aclose.assert_awaited_once()
        assert not (set(asyncio.all_tasks()) - before)

    asyncio.run(scenario())


class ValidHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.text = []
        self.quoted_text = []

    def handle_starttag(self, tag, attrs):
        assert tag in {"b", "i", "code", "blockquote"}
        self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack.pop() == tag

    def handle_data(self, data):
        self.text.append(data)
        if "blockquote" in self.stack:
            self.quoted_text.append(data)


@pytest.mark.parametrize("mode", ["both", "summary_only", "transcription_only", "tldr"])
def test_final_html_is_balanced_and_retains_each_content_codepoint(mode):
    transcript = "<not-a-tag> & 😀\n  " * 1200
    summary = "<summary> & 🛫\n  " * 900
    chunks = bot.build_final_reply_chunks("🎙", "1:00", "fixture", transcript, summary, mode, "1 sec")
    all_text = []
    quoted_text = []
    for chunk in chunks:
        assert units(chunk) <= bot.TELEGRAM_SAFE_MESSAGE_LIMIT
        parser = ValidHTML()
        parser.feed(chunk)
        parser.close()
        assert not parser.stack
        all_text.extend(parser.text)
        quoted_text.extend(parser.quoted_text)
    if mode == "tldr":
        combined = "".join(all_text).removeprefix("🎙 1:00 — fixture (обрабатывалось: 1 sec)")
        assert combined.replace("💡 ", "").strip() == summary.strip()
    else:
        expected = (transcript if mode in ("both", "transcription_only") else "")
        expected += summary if mode in ("both", "summary_only") else ""
        assert "".join(quoted_text) == expected
    assert "&amp;" in "".join(chunks)
    assert "<not-a-tag>" not in "".join(chunks)


def test_live_group_preview_uses_escaped_utf16_budget():
    progress = bot.ProcessingProgress(message(chat_type="supergroup"), "Working")
    progress._live_mode_active = True
    progress._live_final_text = "😀<&>" * 5000
    rendered = progress.render()
    assert units(rendered) <= bot.TELEGRAM_SAFE_MESSAGE_LIMIT
    parser = ValidHTML()
    parser.feed(rendered)
    assert not parser.stack
    assert html.unescape("&lt;") in "".join(parser.text)
