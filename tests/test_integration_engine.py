"""Engine/lifecycle/API visibility regressions, never external network."""
import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

import bot
from integration_api import APIConfig, IntegrationAPI, IntegrationJob, IntegrationStore, SOURCE
from test_integration_api import REQUEST_ID, TOKEN, payload, request, service


def test_enabled_hook_starts_same_process_service_and_default_does_not(monkeypatch, tmp_path):
    fake = NS(start=AsyncMock(), stop=AsyncMock(), store=Mock())
    factory = Mock(return_value=fake)
    monkeypatch.setattr(bot, "IntegrationAPI", factory)
    monkeypatch.setattr(bot, "sync_bot_commands", AsyncMock())
    async def scenario():
        app = NS(bot_data={})
        await bot.post_init(app)
        factory.assert_not_called()
        monkeypatch.setenv("INTEGRATION_API_ENABLED", "1")
        monkeypatch.setenv("INTEGRATION_API_TOKEN", TOKEN)
        monkeypatch.setenv("INTEGRATION_DATABASE_PATH", str(tmp_path / "hook.sqlite3"))
        await bot.post_init(app)
        assert app.bot_data["integration_api"] is fake
        assert factory.call_args.args[1] is bot.JOB_MANAGER
        assert factory.call_args.args[2] is bot.process_integration_media
        fake.start.assert_awaited_once()
    asyncio.run(scenario())


def test_shutdown_before_worker_starts_is_terminal_and_no_telegram_bookkeeping(monkeypatch, tmp_path):
    manager = bot.JobManager()
    monkeypatch.setattr(bot, "JOB_MANAGER", manager)
    store = Mock()
    monkeypatch.setattr(bot, "STORAGE", store)
    api = IntegrationAPI(APIConfig(token=TOKEN, database_path=str(tmp_path / "api.sqlite3")), manager,
                         AsyncMock(), admin_user_id=123, max_media_bytes=1024)
    async def scenario():
        await api.submit(request())
        await bot.post_stop(NS(bot_data={"integration_api": api}))
        assert api.store.get(REQUEST_ID)["status"] == "interrupted"
        assert not manager.active_jobs
        store.update_message_processing.assert_not_called()
    asyncio.run(scenario())


def test_api_processing_uses_shared_prompt_chain_and_chunks_without_telegram(monkeypatch):
    model = AsyncMock(return_value=('{"transcription":"<script>hi</script>","summary":"gist"}', "fixture"))
    monkeypatch.setattr(bot, "call_gemini_with_retries", model)
    monkeypatch.setattr(bot, "STORAGE", Mock())
    async def scenario():
        job = IntegrationJob(job_id=1, user_id=123, media_type="video", mime_type="video/mp4")
        result = await bot.process_integration_media(job, b"fake-video")
        assert result["model_used"] == "fixture"
        assert "&lt;script&gt;" in "".join(result["reply_chunks"])
        assert "<script>" not in "".join(result["reply_chunks"])
        assert model.call_args.kwargs["mime_type"] == "video/mp4"
        assert job.language == "auto"
    asyncio.run(scenario())
    bot.STORAGE.add_model_attempt.assert_not_called()


def test_integration_model_attempts_do_not_write_invalid_foreign_keys(monkeypatch):
    storage = Mock()
    monkeypatch.setattr(bot, "STORAGE", storage)
    meta = {}
    fields = dict(message_processing_id=None, attempt_no=1, model_name="fixture", status="error",
                  error_text="untrusted private provider text")
    bot.record_model_attempt(meta, **fields)
    storage.add_model_attempt.assert_not_called()
    assert meta == {"integration_attempts": [{"attempt_no": 1, "model_name": "fixture", "status": "error"}]}
    fields["message_processing_id"] = 42
    bot.record_model_attempt(meta, **fields)
    storage.add_model_attempt.assert_called_once_with(**fields)


def test_real_shared_engine_path_only_mocks_provider_and_keeps_storage_separate(monkeypatch):
    client = NS(models=NS(generate_content=AsyncMock(return_value=NS(
        text=json.dumps({"transcription": "Оригинал", "summary": "Суть"}, ensure_ascii=False)
    ))))
    monkeypatch.setattr(bot, "gemini_async_clients", [client])
    storage = Mock()
    monkeypatch.setattr(bot, "STORAGE", storage)
    result = asyncio.run(bot.process_integration_media(IntegrationJob(job_id=1, user_id=123), b"fake-ogg"))
    assert result["transcription"] == "Оригинал"
    assert result["model_used"] == bot.GEMINI_MODEL_CHAIN[0]
    client.models.generate_content.assert_awaited_once()
    storage.add_model_attempt.assert_not_called()


def test_api_cleanup_failure_still_drains_jobs(monkeypatch):
    manager = NS(shutdown=AsyncMock())
    api = NS(stop=AsyncMock(side_effect=RuntimeError("fixture")), store=Mock())
    api.store.interrupt_unfinished.side_effect = RuntimeError("fixture-db")
    monkeypatch.setattr(bot, "JOB_MANAGER", manager)
    asyncio.run(bot.post_stop(NS(bot_data={"integration_api": api})))
    manager.shutdown.assert_awaited_once()


def test_api_concurrency_rate_retention_and_result_bounds(tmp_path):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def blocked(*args):
            entered.set()
            await release.wait()
            return {"transcription": "x", "summary": "y", "model_used": "fixture", "elapsed_ms": 1, "reply_chunks": ["x"]}
        api = service(tmp_path, processor=blocked, requests_per_minute=1)
        assert (await api.submit(request())).status == 202
        await entered.wait()
        assert (await api.submit(request(request_id="b" * 64))).status == 503
        # Same request is allowed to read in-flight work despite capacity.
        assert (await api.submit(request())).status == 202
        release.set()
        await asyncio.gather(*api.manager.tasks)
        assert (await api.submit(request(request_id="b" * 64))).status == 429
        api._request_times.clear()
        limited = IntegrationAPI(APIConfig(token=TOKEN, database_path=api.config.database_path, max_records=1),
                                 api.manager, api.processor, admin_user_id=123, max_media_bytes=1024)
        assert payload(await limited.submit(request(request_id="b" * 64)))["error"] == "retention_capacity"
        assert (await limited.submit(request())).status == 200
        oversized = service(tmp_path / "huge", processor=AsyncMock(return_value={"model_used": "fixture", "transcription": "x" * 100}), max_result_bytes=50)
        await oversized.submit(request())
        await asyncio.gather(*oversized.manager.tasks)
        assert oversized.store.get(REQUEST_ID)["status"] == "failed"
    asyncio.run(scenario())


def test_metadata_is_read_only_no_transcript_and_html_safe(tmp_path):
    import admin_panel
    from storage import Storage
    main_path = tmp_path / "bot.sqlite3"
    Storage(str(main_path)).init_db()
    store = IntegrationStore(tmp_path / "integration.sqlite3")
    store.initialize()
    store.claim(REQUEST_ID, "fingerprint", "<script>version</script>")
    store.finish(REQUEST_ID, "succeeded", result={"transcription": "PRIVATE TRANSCRIPT"})
    app = admin_panel.create_app(str(main_path))
    app.testing = True
    response = app.test_client().get("/")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert SOURCE in text
    assert "PRIVATE TRANSCRIPT" not in text
    assert "&lt;script&gt;version&lt;/script&gt;" in text
    assert "result_json" not in str(store.recent_metadata(store.path))
    assert store.get(REQUEST_ID)["status"] == "succeeded"


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_compressed_uploads_rejected_without_reading(tmp_path, encoding):
    from aiohttp.test_utils import make_mocked_request
    api = service(tmp_path)
    req = make_mocked_request("POST", "/v1/transcriptions?media_type=voice", headers={
        "Authorization": "Bearer " + TOKEN, "X-Request-ID": REQUEST_ID,
        "Content-Type": "audio/ogg", "Content-Encoding": encoding,
    })
    req.read = AsyncMock()
    assert asyncio.run(api.submit(req)).status == 400
    req.read.assert_not_awaited()
