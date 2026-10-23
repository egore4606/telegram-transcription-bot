"""Private API boundaries: offline, fake engine, temporary SQLite only."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp.test_utils import make_mocked_request

from integration_api import APIConfig, IntegrationAPI, IntegrationStore, SOURCE


TOKEN = "offline-test-token-" + "x" * 32
REQUEST_ID = "a" * 64


class Manager:
    def __init__(self):
        self.jobs = []
        self.tasks = []
        self.busy = False

    def allocate_job_id(self):
        return len(self.jobs) + 1

    async def submit_external(self, job, run):
        if self.busy:
            return False
        self.jobs.append(job)
        self.tasks.append(asyncio.create_task(run()))
        return True

    async def finish(self, job):
        pass


def service(tmp_path, processor=None, **options):
    config = APIConfig(token=TOKEN, database_path=str(tmp_path / "integration.sqlite3"), **options)
    return IntegrationAPI(config, Manager(), processor or AsyncMock(return_value={
        "transcription": "Привет", "summary": "Суть", "model_used": "fixture",
        "elapsed_ms": 1, "reply_chunks": ["<b>Привет</b>"],
    }), admin_user_id=123, max_media_bytes=1024)


def request(*, request_id=REQUEST_ID, body=b"fake-audio", token=TOKEN, query="media_type=voice&mode=both&duration_seconds=2"):
    req = make_mocked_request("POST", "/v1/transcriptions?" + query, headers={
        "Authorization": "Bearer " + token,
        "X-Request-ID": request_id,
        "Content-Type": "audio/ogg",
        "Content-Length": str(len(body)),
    })
    req.read = AsyncMock(return_value=body)
    return req


def payload(response):
    import json
    return json.loads(response.body)


def test_disabled_default_and_validation():
    assert APIConfig.from_env({}) is None
    with pytest.raises(ValueError):
        APIConfig.from_env({"INTEGRATION_API_ENABLED": "1", "INTEGRATION_API_TOKEN": "short"})
    with pytest.raises(ValueError):
        APIConfig(token=TOKEN, host="8.8.8.8")
    with pytest.raises(ValueError):
        APIConfig(token=TOKEN, processing_timeout=0)


def test_authentication_precedes_body_and_engine(tmp_path):
    api = service(tmp_path)
    async def scenario():
        req = request(token="wrong")
        result = await api.submit(req)
        assert result.status == 401
        req.read.assert_not_awaited()
        api.processor.assert_not_awaited()
    asyncio.run(scenario())


def test_success_duplicate_and_persisted_result(tmp_path):
    api = service(tmp_path)
    async def scenario():
        first = await api.submit(request())
        assert first.status == 202
        await asyncio.gather(*api.manager.tasks)
        second = await api.submit(request())
        assert second.status == 200
        data = payload(second)
        assert data["source"] == SOURCE
        assert data["api_version"] == 1
        assert data["status"] == "succeeded"
        assert data["result"]["transcription"] == "Привет"
        api.processor.assert_awaited_once()
        conflict = await api.submit(request(body=b"other-audio"))
        assert conflict.status == 409
        restarted = service(tmp_path)
        assert restarted.store.get(REQUEST_ID)["status"] == "succeeded"
        replay = await restarted.submit(request())
        assert replay.status == 200
        restarted.processor.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize("query", ["media_type=document", "media_type=voice&url=http://x", "media_type=voice&mode=bogus", "media_type=voice&duration_seconds=-1", "media_type=voice&duration_seconds=3601", "media_type=voice&media_type=video", "media_type=voice&language=ru"])
def test_rejects_bad_metadata_before_body(tmp_path, query):
    api = service(tmp_path)
    async def scenario():
        req = request(query=query)
        assert (await api.submit(req)).status == 400
        req.read.assert_not_awaited()
    asyncio.run(scenario())


def test_size_empty_ids_and_busy_are_bounded(tmp_path):
    api = service(tmp_path)
    async def scenario():
        assert (await api.submit(request(body=b"x" * 1025))).status == 413
        assert (await api.submit(request(body=b""))).status == 400
        assert (await api.submit(request(request_id="../bad"))).status == 400
        api.manager.busy = True
        assert (await api.submit(request())).status == 503
        assert api.store.get(REQUEST_ID) is None
        api.processor.assert_not_awaited()
        api.manager.busy = False
        assert (await api.submit(request())).status == 202
        await asyncio.gather(*api.manager.tasks)
    asyncio.run(scenario())


def test_failure_and_shutdown_do_not_reexecute_or_leak(tmp_path):
    api = service(tmp_path, processor=AsyncMock(side_effect=RuntimeError("SECRET transcript token")))
    async def scenario():
        await api.submit(request())
        await asyncio.gather(*api.manager.tasks)
        row = api.store.get(REQUEST_ID)
        assert row["status"] == "failed"
        assert row["error"] == "processing_failed"
        assert "SECRET" not in str(row)
        await api.submit(request())
        api.processor.assert_awaited_once()
    asyncio.run(scenario())
    api.store.claim("b" * 64, "fingerprint", "unversioned")
    IntegrationStore(api.config.database_path).initialize()
    assert api.store.get("b" * 64)["status"] == "interrupted"


def test_result_size_and_processing_timeout(tmp_path):
    async def slow(*args):
        await asyncio.sleep(1)
    api = service(tmp_path, processor=slow, processing_timeout=0.01)
    async def scenario():
        await api.submit(request())
        await asyncio.gather(*api.manager.tasks)
        assert api.store.get(REQUEST_ID)["error"] == "processing_timeout"
    asyncio.run(scenario())


def test_read_status_and_result_require_auth(tmp_path):
    api = service(tmp_path)
    async def scenario():
        status = make_mocked_request("GET", "/v1/status", headers={"Authorization": "Bearer " + TOKEN})
        data = payload(await api.status(status))
        assert data["engine"]["name"] == "telegram-transcription-bot"
        assert data["max_media_bytes"] == 1024
        unauthorized = make_mocked_request("GET", "/v1/status")
        assert (await api.status(unauthorized)).status == 401
        missing = make_mocked_request("GET", "/v1/transcriptions/" + REQUEST_ID,
                                      headers={"Authorization": "Bearer " + TOKEN}, match_info={"request_id": REQUEST_ID})
        assert (await api.get_result(missing)).status == 404
    asyncio.run(scenario())


def test_global_manager_capacity_includes_api_and_releases_to_telegram(monkeypatch):
    import bot
    from integration_api import IntegrationJob
    from test_audit_core import job_fixture
    manager = bot.JobManager()
    monkeypatch.setattr(bot, "MAX_ACTIVE_JOBS_GLOBAL", 1)
    monkeypatch.setattr(bot, "STORAGE", Mock())
    async def scenario():
        gate = asyncio.Event()
        external = IntegrationJob(job_id=manager.allocate_job_id(), user_id=123)
        async def work():
            try:
                await gate.wait()
            finally:
                await manager.finish(external)
        assert await manager.submit_external(external, work)
        normal = job_fixture()
        normal.job_id = manager.allocate_job_id()
        manager._start_job = Mock()
        assert await manager.submit(normal) == "queued"
        assert not await manager.submit_external(IntegrationJob(job_id=3, user_id=123), work)
        gate.set()
        await external.task
        manager._start_job.assert_called_once_with(normal)
        await manager.finish(normal)
    asyncio.run(scenario())


def test_shared_engine_helper_is_used_by_telegram_and_integration(monkeypatch):
    import bot
    from integration_api import IntegrationJob, SilentProgress
    from test_audit_core import job_fixture
    common = AsyncMock(return_value=('{"transcription":"hello","summary":"gist"}', "fixture"))
    monkeypatch.setattr(bot, "call_gemini_with_retries", common)
    async def scenario():
        for job in [job_fixture(), IntegrationJob(job_id=1, user_id=123)]:
            result = await bot.transcribe_media_bytes(job, b"fake", SilentProgress(), {"attempt_no": 1})
            assert result[1] == "fixture"
        assert common.await_count == 2
    asyncio.run(scenario())
