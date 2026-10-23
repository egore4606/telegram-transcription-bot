"""Offline benchmark-order and independent Live-preview engine regressions."""
import asyncio
import csv
from pathlib import Path
import statistics
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

import bot
from integration_api import IntegrationJob, SilentProgress


RESULT = '{"transcription":"complete","summary":"gist"}'


def telegram_job(**overrides):
    fields = dict(job_id=1, context=NS(), message=NS(), processing_message=NS(),
                  media_type="voice", media_file_id="fixture", mime_type="audio/ogg",
                  progress_text="main", media_emoji="voice", duration_seconds=20,
                  duration_str="20s", file_size_kb=1, scope_type="user", scope_id=1,
                  mode="both", language="auto", transcription_type="verbatim",
                  chat_id=1, chat_title="", user_id=1, user_name="Test", user_username="",
                  message_processing_id=None)
    fields.update(overrides)
    return bot.MediaJob(**fields)


def progress():
    return NS(set_status_text=AsyncMock(), set_live_mode=AsyncMock(), set_live_transcript=AsyncMock())


def meta():
    return {"attempt_no": 1, "models_tried": [], "fallback_key_used": False}


@pytest.mark.parametrize("media_type,duration,sample", [
    ("voice", 0, "short_voice"), ("voice", 30, "short_voice"),
    ("voice", 31, "long_voice"), ("video", 20, "video_note"),
])
def test_default_chain_matches_successful_complete_json_medians(media_type, duration, sample):
    rows = list(csv.DictReader((Path(__file__).parents[1] / "docs/benchmarks/2026-10-15/raw-measurements.csv").open()))
    models = {"gemini-3.1-flash-lite", *bot.GEMINI_FALLBACK_MODELS}
    measured = {model: statistics.median(float(row["latency_seconds"]) for row in rows
                if row["model"] == model and row["track"] == "json_original"
                and row["input"] == sample and row["status"] == "success") for model in models}
    assert bot.model_chain_for_media(media_type, duration) == sorted(models, key=measured.get)
    assert bot.BENCHMARK_MODEL_MEDIANS[sample] == pytest.approx(measured)


def test_legacy_environment_override_requires_explicit_manual_order(monkeypatch):
    # Execute config-only code; never instantiate another provider client.
    source = Path(bot.__file__).read_text().split("# Gemini clients")[0]
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-transcribe-live")
    monkeypatch.delenv("MODEL_ORDER", raising=False)
    scope = {}
    exec(compile(source, bot.__file__, "exec"), scope)
    assert scope["model_chain_for_media"]("voice", 5)[0] == "gemini-2.5-flash-lite"
    assert all("transcribe" not in model for model in scope["GEMINI_MODEL_CHAIN"])
    monkeypatch.setenv("MODEL_ORDER", "manual")
    scope = {}
    exec(compile(source, bot.__file__, "exec"), scope)
    for media in ("voice", "video"):
        assert scope["model_chain_for_media"](media, 5)[0] == "gemini-3.5-transcribe"
        assert "gemini-3.5-transcribe-live" not in scope["model_chain_for_media"](media, 5)


@pytest.mark.parametrize("finish", ["result", "error", "stop", "cancel"])
def test_preview_parallel_and_drained_on_every_main_exit(monkeypatch, finish):
    async def scenario():
        job = telegram_job()
        entered, stopped, main_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
        preview_tasks = []
        async def live(key, data, observer, controls):
            preview_tasks.append(asyncio.current_task())
            assert controls.cancel_event is job.cancel_event
            assert controls.next_model_event is not job.next_model_event
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        async def main(*args, **kwargs):
            main_entered.set()
            await entered.wait()
            if finish == "error":
                raise ValueError("main failed")
            if finish == "stop":
                job.cancel_event.set()
                bot.ensure_job_can_continue(job)
            if finish == "cancel":
                await asyncio.Event().wait()
            return RESULT, "main"
        monkeypatch.setattr(bot, "transcribe_live_with_client", live)
        monkeypatch.setattr(bot, "call_gemini_with_retries", main)
        task = asyncio.create_task(bot.transcribe_media_bytes(job, b"media", progress(), meta()))
        await asyncio.wait_for(main_entered.wait(), 1)
        await asyncio.wait_for(entered.wait(), 1)
        if finish == "cancel":
            task.cancel()
        error = {"error": ValueError, "stop": bot.JobCancelled, "cancel": asyncio.CancelledError}.get(finish)
        if error:
            with pytest.raises(error):
                await asyncio.wait_for(task, 1)
        else:
            assert await asyncio.wait_for(task, 1) == (RESULT, "main")
        assert stopped.is_set()
        assert len(preview_tasks) == 1 and preview_tasks[0].done()
    asyncio.run(scenario())


@pytest.mark.parametrize("live_fails", [False, True])
def test_preview_completion_or_failure_never_replaces_main(monkeypatch, live_fails):
    async def scenario():
        preview_finished = asyncio.Event()
        async def live(*args):
            preview_finished.set()
            if live_fails:
                raise RuntimeError("preview failed")
            return "not the final result"
        async def main(*args, **kwargs):
            await preview_finished.wait()
            await asyncio.sleep(0)
            return RESULT, "main"
        monkeypatch.setattr(bot, "transcribe_live_with_client", live)
        monkeypatch.setattr(bot, "call_gemini_with_retries", main)
        assert await bot.transcribe_media_bytes(telegram_job(), b"media", progress(), meta()) == (RESULT, "main")
    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["integration", "silent", "too_long", "too_large"])
def test_preview_only_for_observed_safe_telegram_jobs(monkeypatch, case):
    live = AsyncMock()
    monkeypatch.setattr(bot, "transcribe_live_with_client", live)
    monkeypatch.setattr(bot, "call_gemini_with_retries", AsyncMock(return_value=(RESULT, "main")))
    job, observer = telegram_job(), progress()
    if case == "integration":
        job = IntegrationJob(job_id=1, user_id=123)
    if case == "silent":
        observer = SilentProgress()
    if case == "too_long":
        job.duration_seconds = 601
    if case == "too_large":
        monkeypatch.setattr(bot, "MAX_MEDIA_BYTES", 1)
        with pytest.raises(bot.MediaTooLarge):
            asyncio.run(bot.transcribe_media_bytes(job, b"media", observer, meta()))
    else:
        asyncio.run(bot.transcribe_media_bytes(job, b"media", observer, meta()))
    live.assert_not_awaited()


def test_next_and_automatic_fallback_do_not_restart_or_cancel_preview(monkeypatch):
    async def scenario():
        job = telegram_job(duration_seconds=600)
        live_entered, live_stopped = asyncio.Event(), asyncio.Event()
        calls = []
        async def live(key, data, observer, controls):
            live_entered.set()
            try:
                await job.next_model_event.wait()
                bot.ensure_job_can_continue(controls)
                await asyncio.Event().wait()
            finally:
                live_stopped.set()
        async def model(contents, name, *args, **kwargs):
            calls.append(name)
            await live_entered.wait()
            assert not live_stopped.is_set()
            if len(calls) == 1:
                job.next_model_event.set()
                raise bot.NextModelRequested("skip")
            if len(calls) == 2:
                raise RuntimeError("503 overloaded")
            return RESULT
        monkeypatch.setattr(bot, "GEMINI_MODEL_CHAIN", ["one", "two", "three"])
        monkeypatch.setattr(bot, "transcribe_live_with_client", live)
        monkeypatch.setattr(bot, "call_gemini", model)
        assert await bot.transcribe_media_bytes(job, b"media", progress(), meta()) == (RESULT, "three")
        assert calls == ["one", "two", "three"]
        assert live_stopped.is_set()
    asyncio.run(scenario())


def test_preview_proxy_preserves_status_and_forwards_transcripts(monkeypatch):
    async def scenario():
        job = telegram_job()
        observer = bot.ProcessingProgress(NS(message_id=1), "main status")
        monkeypatch.setattr(observer, "refresh", AsyncMock())
        monkeypatch.setattr(observer, "refresh_live_draft", AsyncMock())
        text_sent = asyncio.Event()
        async def live(key, data, proxy, controls):
            await proxy.set_live_mode(True, "must not overwrite main status")
            await proxy.set_live_transcript("live", "preview", force=True)
            text_sent.set()
            await asyncio.Event().wait()
        async def main(*args, **kwargs):
            await text_sent.wait()
            assert observer.status_text == "main status"
            await observer.set_status_text("fallback status")
            assert observer._live_mode_active
            assert observer._live_final_text == "live"
            return RESULT, "main"
        monkeypatch.setattr(bot, "transcribe_live_with_client", live)
        monkeypatch.setattr(bot, "call_gemini_with_retries", main)
        assert await bot.transcribe_media_bytes(job, b"media", observer, meta()) == (RESULT, "main")
        assert observer.status_text == "fallback status"
        assert not observer._live_mode_active
    asyncio.run(scenario())


@pytest.mark.parametrize("error", [
    RuntimeError("503 overloaded"), RuntimeError("model_request_timeout"),
    RuntimeError("Model is overloaded"),
    bot.InvalidStructuredResponse("invalid JSON"),
    RuntimeError("404 NOT_FOUND: models/old is not found for generateContent"),
    RuntimeError("400 model old does not support generateContent"),
    TimeoutError(),
])
def test_recoverable_model_errors_advance_chain(monkeypatch, error):
    monkeypatch.setattr(bot, "GEMINI_MODEL_CHAIN", ["first", "second"])
    call = AsyncMock(side_effect=[error, RESULT])
    monkeypatch.setattr(bot, "call_gemini", call)
    assert asyncio.run(bot.call_gemini_with_retries([], progress(), None, meta())) == (RESULT, "second")
    assert call.await_count == 2


@pytest.mark.parametrize("error", [
    RuntimeError("429 quota exhausted; please try again later"),
    RuntimeError("400 invalid media"), RuntimeError("403 permission denied"),
    RuntimeError("404 file resource not found"),
    RuntimeError("403 permission denied: model not available to this caller"),
    RuntimeError("400 unsupported media format for model"),
])
def test_quota_or_non_model_client_errors_do_not_advance_chain(monkeypatch, error):
    monkeypatch.setattr(bot, "GEMINI_MODEL_CHAIN", ["first", "second"])
    call = AsyncMock(side_effect=error)
    monkeypatch.setattr(bot, "call_gemini", call)
    with pytest.raises(RuntimeError):
        asyncio.run(bot.call_gemini_with_retries([], progress(), None, meta()))
    assert call.await_count == 1


@pytest.mark.parametrize("backup_succeeds", [False, True])
def test_true_quota_tries_backup_key_before_aborting_models(monkeypatch, backup_succeeds):
    quota = RuntimeError("429 quota exhausted; please try again later")
    primary = NS(models=NS(generate_content=AsyncMock(side_effect=quota)))
    backup = NS(models=NS(generate_content=AsyncMock(return_value=NS(text=RESULT),
                side_effect=None if backup_succeeds else quota)))
    monkeypatch.setattr(bot, "gemini_async_clients", [primary, backup])
    monkeypatch.setattr(bot, "GEMINI_MODEL_CHAIN", ["first", "second"])
    monkeypatch.setattr(bot, "STORAGE", Mock())
    run_meta = meta()
    if backup_succeeds:
        assert asyncio.run(bot.call_gemini_with_retries([], progress(), None, run_meta)) == (RESULT, "first")
    else:
        with pytest.raises(RuntimeError, match="quota"):
            asyncio.run(bot.call_gemini_with_retries([], progress(), None, run_meta))
    assert primary.models.generate_content.await_count == backup.models.generate_content.await_count == 1
    assert run_meta["fallback_key_used"] is True


def test_overload_429_switches_model_not_backup_key(monkeypatch):
    overload = bot.genai_errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Model is overloaded due to high demand"}})
    primary = NS(models=NS(generate_content=AsyncMock(side_effect=[overload, NS(text=RESULT)])))
    backup = NS(models=NS(generate_content=AsyncMock()))
    monkeypatch.setattr(bot, "gemini_async_clients", [primary, backup])
    monkeypatch.setattr(bot, "GEMINI_MODEL_CHAIN", ["first", "second"])
    assert asyncio.run(bot.call_gemini_with_retries([], progress(), None, meta())) == (RESULT, "second")
    backup.models.generate_content.assert_not_awaited()


def test_first_model_is_reported_to_technical_status_observer(monkeypatch):
    monkeypatch.setattr(bot, "GEMINI_MODEL_CHAIN", ["model<untrusted>"])
    monkeypatch.setattr(bot, "call_gemini", AsyncMock(return_value=RESULT))
    observer = progress()
    asyncio.run(bot.call_gemini_with_retries([], observer, None, meta()))
    status = observer.set_status_text.await_args_list[0].args[0]
    assert "<code>model&lt;untrusted&gt;</code>" in status


def test_manual_live_selection_is_only_file_stt_in_main(monkeypatch):
    monkeypatch.setattr(bot, "transcribe_live_with_client", AsyncMock())
    file_stt = AsyncMock(return_value="file transcript")
    monkeypatch.setattr(bot, "transcribe_file_with_client", file_stt)
    result = asyncio.run(bot.transcribe_with_client(NS(), "fixture", "gemini-3.5-transcribe-live",
                         b"media", "audio/ogg", 1, "verbatim", progress(), telegram_job()))
    assert result == ("file transcript", "gemini-3.5-transcribe")
    bot.transcribe_live_with_client.assert_not_awaited()
    assert file_stt.await_args.args[1] == "gemini-3.5-transcribe"


@pytest.mark.parametrize("parent_cancel", [False, True])
def test_repeated_parent_cancel_during_preview_cleanup_does_not_leak(monkeypatch, parent_cancel):
    async def scenario():
        baseline = asyncio.all_tasks()
        entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def live(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
        async def main(*args, **kwargs):
            await entered.wait()
            if parent_cancel:
                await asyncio.Event().wait()
            return RESULT, "main"
        monkeypatch.setattr(bot, "transcribe_live_with_client", live)
        monkeypatch.setattr(bot, "call_gemini_with_retries", main)
        task = asyncio.create_task(bot.transcribe_media_bytes(telegram_job(), b"media", progress(), meta()))
        await entered.wait()
        if parent_cancel:
            task.cancel()
        await cleaning.wait()
        # A second cancellation while draining must not orphan the Live worker.
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert not (asyncio.all_tasks() - baseline)
    asyncio.run(scenario())


def test_slow_preview_close_has_bounded_drain_and_keeps_success(monkeypatch):
    async def scenario():
        baseline = asyncio.all_tasks()
        entered, cleaning = asyncio.Event(), asyncio.Event()
        async def live(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await asyncio.Event().wait()  # interrupted by cleanup deadline
        async def main(*args, **kwargs):
            await entered.wait()
            return RESULT, "main"
        monkeypatch.setattr(bot, "LIVE_PREVIEW_CLEANUP_TIMEOUT", 0.01)
        monkeypatch.setattr(bot, "transcribe_live_with_client", live)
        monkeypatch.setattr(bot, "call_gemini_with_retries", main)
        assert await asyncio.wait_for(bot.transcribe_media_bytes(
            telegram_job(), b"media", progress(), meta()), 0.5) == (RESULT, "main")
        assert cleaning.is_set()
        assert not (asyncio.all_tasks() - baseline)
    asyncio.run(scenario())


@pytest.mark.parametrize("finish", ["success", "stop", "parent", "recv_error"])
def test_real_live_protocol_worker_drains_sender_receiver_and_connection(monkeypatch, finish):
    async def scenario():
        baseline = asyncio.all_tasks()
        sending, receiving, closed, main_release = (asyncio.Event() for _ in range(4))
        child_tasks = []
        job = telegram_job()
        class Socket:
            setup = True
            async def send(self, payload):
                if "realtimeInput" in bot.json.loads(payload):
                    child_tasks.append(asyncio.current_task())
                    sending.set()
                    await asyncio.Event().wait()
            async def recv(self):
                if self.setup:
                    self.setup = False
                    return '{"setupComplete":{}}'
                child_tasks.append(asyncio.current_task())
                receiving.set()
                if finish == "recv_error":
                    raise RuntimeError("mock connection failed")
                await asyncio.Event().wait()
        class Connection:
            async def __aenter__(self):
                return Socket()
            async def __aexit__(self, *args):
                closed.set()
        monkeypatch.setattr(bot.websockets, "connect", Mock(return_value=Connection()))
        monkeypatch.setattr(bot, "convert_media_audio", AsyncMock(return_value=(b"x" * 3200, "audio/pcm;rate=16000")))
        async def main(*args, **kwargs):
            await sending.wait()
            await receiving.wait()
            if finish == "stop":
                job.cancel_event.set()
                bot.ensure_job_can_continue(job)
            if finish == "parent":
                main_release.set()
                await asyncio.Event().wait()
            if finish == "recv_error":
                await closed.wait()
            return RESULT, "main"
        monkeypatch.setattr(bot, "call_gemini_with_retries", main)
        task = asyncio.create_task(bot.transcribe_media_bytes(job, b"media", progress(), meta()))
        if finish == "parent":
            await main_release.wait()
            task.cancel()
        if finish in ("parent", "stop"):
            with pytest.raises(asyncio.CancelledError if finish == "parent" else bot.JobCancelled):
                await asyncio.wait_for(task, 1)
        else:
            assert await asyncio.wait_for(task, 1) == (RESULT, "main")
        assert closed.is_set()
        assert child_tasks and all(child.done() for child in child_tasks)
        assert not (asyncio.all_tasks() - baseline)
    asyncio.run(scenario())


@pytest.mark.parametrize("has_job", [False, True])
def test_main_worker_cleanup_survives_repeated_parent_cancellation(has_job):
    async def scenario():
        baseline = asyncio.all_tasks()
        entered, cleaning, release, cleaned = (asyncio.Event() for _ in range(4))
        async def worker():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
                cleaned.set()
        child = asyncio.create_task(worker())
        parent = asyncio.create_task(bot.wait_for_model_response(child, telegram_job() if has_job else None))
        await entered.wait()
        parent.cancel()
        await cleaning.wait()
        parent.cancel()
        await asyncio.sleep(0)
        parent.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(parent, 1)
        assert cleaned.is_set() and child.done()
        assert not (asyncio.all_tasks() - baseline)
    asyncio.run(scenario())
