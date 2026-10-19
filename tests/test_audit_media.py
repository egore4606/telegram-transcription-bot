"""Bounded synthetic subprocess / mocked SDK and websocket failure tests."""
import asyncio
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

import bot


class Stream:
    def __init__(self, data, *, blocked=False):
        self.data = data
        self.blocked = blocked
        self.sizes = []
        self.finished = asyncio.Event()

    async def read(self, size=-1):
        self.sizes.append(size)
        if self.blocked:
            await asyncio.Event().wait()
        if not self.data:
            self.finished.set()
            return b""
        count = len(self.data) if size < 0 else size
        result, self.data = self.data[:count], self.data[count:]
        return result


class Process:
    def __init__(self, output=b"a" * 200, stderr=b"", code=0, blocked=False, race=False):
        self.stdout = Stream(output, blocked=blocked)
        self.stderr = Stream(stderr)
        self.returncode = None
        self.code = code
        self.killed = False
        self.reaped = False
        self.race = race

    async def communicate(self):
        # Compatibility with the old implementation: demonstrate actual missing bounds.
        output, error = await asyncio.gather(self.stdout.read(), self.stderr.read())
        self.returncode = self.code
        self.reaped = True
        return output, error

    async def wait(self):
        if not self.killed:
            await self.stdout.finished.wait()
            await self.stderr.finished.wait()
        self.returncode = -9 if self.killed else self.code
        self.reaped = True
        return self.returncode

    def kill(self):
        self.killed = True
        self.stdout.blocked = False
        self.stderr.blocked = False
        if self.race:
            self.returncode = 0
            raise ProcessLookupError("already exited")


@pytest.mark.parametrize("case", ["success", "cap", "pressure", "nonzero", "timeout", "cancel", "kill_race", "missing"])
def test_conversion_is_bounded_and_always_cleans(monkeypatch, case):
    async def scenario():
        before = set(asyncio.all_tasks())
        process = Process(output=b"a" * (1000 if case == "cap" else 200),
                          stderr=b"private diagnostic" * (10000 if case == "pressure" else 1),
                          code=1 if case == "nonzero" else 0,
                          blocked=case in ("timeout", "cancel", "kill_race"), race=case == "kill_race")
        input_paths = []
        entered = asyncio.Event()
        async def spawn(*args, **kwargs):
            input_paths.append(Path(args[args.index("-i") + 1]))
            entered.set()
            if case == "missing":
                raise FileNotFoundError("fixture")
            return process
        monkeypatch.setattr(bot.asyncio, "create_subprocess_exec", spawn)
        monkeypatch.setattr(bot, "MAX_DECODED_AUDIO_BYTES", 500, raising=False)
        monkeypatch.setattr(bot, "FFMPEG_TIMEOUT_SECONDS", 0.01, raising=False)
        task = asyncio.create_task(bot.convert_media_audio(b"synthetic", pcm=True))
        await entered.wait()
        if case in ("cancel", "kill_race"):
            task.cancel()
        if case in ("success", "pressure"):
            output, mime = await task
            assert output == b"a" * 200
            assert mime == "audio/pcm;rate=16000"
            assert process.stdout.sizes and all(0 < size <= 65536 for size in process.stdout.sizes)
            assert process.stderr.sizes and all(0 < size <= 65536 for size in process.stderr.sizes)
        else:
            expected = (asyncio.CancelledError if case in ("cancel", "kill_race")
                        else bot.MediaTooLarge if case == "cap" else RuntimeError)
            try:
                with pytest.raises(expected):
                    await asyncio.wait_for(task, timeout=0.5)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert all(not path.exists() for path in input_paths)
        if case != "missing":
            assert process.reaped
        assert not (set(asyncio.all_tasks()) - before)
    asyncio.run(scenario())


@pytest.mark.parametrize("suffix", [".ogg", ".mp4"])
def test_synthetic_local_ogg_and_mp4_conversion(tmp_path, suffix):
    executable = shutil.which("ffmpeg")
    if executable is None:
        pytest.skip("optional local ffmpeg smoke test; fake-process bounds tests still run")
    source = tmp_path / ("synthetic" + suffix)
    command = [executable, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               "sine=frequency=440:duration=0.05", "-c:a", "libopus" if suffix == ".ogg" else "aac", str(source)]
    subprocess.run(command, check=True, capture_output=True, timeout=10)
    for pcm in (True, False):
        output, mime = asyncio.run(bot.convert_media_audio(source.read_bytes(), pcm=pcm))
        assert len(output) > 100
        assert mime == ("audio/pcm;rate=16000" if pcm else "audio/wav")


def test_conversion_disables_network_protocols(monkeypatch):
    process = Process()
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(bot.asyncio, "create_subprocess_exec", spawn)
    asyncio.run(bot.convert_media_audio(b"synthetic", pcm=False))
    args = spawn.await_args.args
    assert args[args.index("-protocol_whitelist") + 1] == "file,pipe"
    assert args.index("-protocol_whitelist") < args.index("-i")


@pytest.mark.parametrize("case", ["interaction_cancel", "delete_cancel", "delete_failure", "upload_failure", "interaction_error_delete_error", "delete_timeout"])
def test_file_upload_local_cleanup_survives_remote_cleanup(monkeypatch, case):
    async def scenario():
        paths = []
        delete_entered, interaction_entered = asyncio.Event(), asyncio.Event()
        async def upload(**kwargs):
            paths.append(Path(kwargs["file"]))
            if case == "upload_failure":
                raise ValueError("upload failed")
            return NS(uri="fake-uri", name="fake-handle", mime_type="audio/ogg")
        async def interaction(**kwargs):
            interaction_entered.set()
            if case == "interaction_cancel":
                await asyncio.Event().wait()
            if case == "interaction_error_delete_error":
                raise ValueError("original interaction")
            return NS(output_text="fixture transcript")
        async def delete(**kwargs):
            delete_entered.set()
            if case in ("delete_cancel", "delete_timeout"):
                await asyncio.Event().wait()
            if case in ("delete_failure", "interaction_error_delete_error"):
                raise RuntimeError("cleanup error")
        client = NS(files=NS(upload=upload, delete=delete), interactions=NS(create=interaction))
        monkeypatch.setattr(bot, "REMOTE_FILE_CLEANUP_TIMEOUT", 0.01, raising=False)
        task = asyncio.create_task(bot.transcribe_file_with_client(client, "fake-model", b"synthetic", "audio/ogg", "clean"))
        if case == "interaction_cancel":
            await interaction_entered.wait()
            task.cancel()
        elif case == "delete_cancel":
            await delete_entered.wait()
            task.cancel()
        try:
            if case in ("interaction_cancel", "delete_cancel"):
                with pytest.raises(asyncio.CancelledError):
                    await task
            elif case in ("upload_failure", "interaction_error_delete_error"):
                with pytest.raises(ValueError):
                    await task
            else:
                assert await asyncio.wait_for(task, 0.5) == "fixture transcript"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert paths and all(not path.exists() for path in paths)
    asyncio.run(scenario())


@pytest.mark.parametrize("side", ["sender", "receiver"])
@pytest.mark.parametrize("kind", ["service", "stop", "next", "cancel", "cleanup", "cleanup_cancel"])
def test_live_errors_preserve_identity_and_drain_siblings(monkeypatch, side, kind):
    async def scenario():
        entered = {"sender": asyncio.Event(), "receiver": asyncio.Event()}
        exited = {"sender": asyncio.Event(), "receiver": asyncio.Event()}
        release = asyncio.Event()
        error = {"service": RuntimeError("503 key=fake-live-key"), "stop": bot.JobCancelled("stop"),
                 "next": bot.NextModelRequested("next"), "cleanup": RuntimeError("503 originating"),
                 "cleanup_cancel": RuntimeError("503 originating"),
                 "cancel": asyncio.CancelledError()}[kind]
        class Socket:
            setup = True
            async def send(self, payload):
                if "setup" in json.loads(payload):
                    return
                entered["sender"].set()
                try:
                    await entered["receiver"].wait()
                    if side == "sender" and kind != "cancel":
                        raise error
                    await release.wait()
                finally:
                    exited["sender"].set()
            async def recv(self):
                if self.setup:
                    self.setup = False
                    return '{"setupComplete":{}}'
                entered["receiver"].set()
                try:
                    await entered["sender"].wait()
                    if side == "receiver" and kind != "cancel":
                        raise error
                    await release.wait()
                finally:
                    exited["receiver"].set()
        class Connection:
            async def __aenter__(self):
                return Socket()
            async def __aexit__(self, *args):
                return None
        monkeypatch.setattr(bot.websockets, "connect", Mock(return_value=Connection()))
        monkeypatch.setattr(bot, "convert_media_audio", AsyncMock(return_value=(b"a" * 3200, "audio/pcm;rate=16000")))
        async def live_mode(active, *args):
            if not active and kind == "cleanup":
                raise ValueError("secondary cleanup")
            if not active and kind == "cleanup_cancel":
                raise asyncio.CancelledError("secondary cleanup cancellation")
        progress = NS(set_live_mode=AsyncMock(side_effect=live_mode), set_live_transcript=AsyncMock())
        before = set(asyncio.all_tasks())
        task = asyncio.create_task(bot.transcribe_live_with_client("fake-live-key", b"synthetic", progress, None))
        if kind == "cancel":
            await entered["sender"].wait()
            await entered["receiver"].wait()
            task.cancel()
        try:
            with pytest.raises(type(error)) as captured:
                await task
            if kind in ("service", "cleanup", "cleanup_cancel"):
                assert bot.is_model_overloaded_error(captured.value)
                assert "fake-live-key" not in str(captured.value)
            assert all(event.is_set() for event in exited.values())
            assert progress.set_live_mode.await_args.args == (False,)
            assert not (set(asyncio.all_tasks()) - before)
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
