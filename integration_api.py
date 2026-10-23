"""Opt-in, private side entrance to the running bot's transcription engine.

No Telegram transport or Gemini implementation lives here. The host supplies
one shared processor and its JobManager. Only bounded media bytes enter;
request fingerprints and results survive restart in a separate SQLite file.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import math
import os
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiohttp import web

SOURCE = "personal-auto-transcriber"
API_VERSION = 1
REQUEST_ID_RE = re.compile(r"[a-f0-9]{64}\Z")
MIME_TYPES = {"audio/ogg", "audio/mpeg", "audio/mp4", "audio/wav", "audio/x-wav", "audio/webm", "video/mp4", "video/webm"}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class APIConfig:
    token: str = field(repr=False)
    database_path: str = "data/integration.sqlite3"
    host: str = "127.0.0.1"
    port: int = 8082
    version: str = "unversioned"
    processing_timeout: float = 900
    max_uploads: int = 1
    max_active_jobs: int = 1
    max_records: int = 1000
    requests_per_minute: int = 5
    max_result_bytes: int = 512 * 1024

    def __post_init__(self):
        if len(self.token) < 32 or any(c.isspace() for c in self.token):
            raise ValueError("INTEGRATION_API_TOKEN must contain at least 32 non-whitespace characters")
        address = ipaddress.ip_address(self.host)
        if not (address.is_loopback or address.is_private or address.is_unspecified):
            raise ValueError("Integration API must bind a local/private address")
        if not (1 <= self.port <= 65535) or min(self.processing_timeout, self.max_uploads, self.max_active_jobs, self.max_records, self.requests_per_minute, self.max_result_bytes) <= 0:
            raise ValueError("Integration API limits must be positive")
        if not math.isfinite(self.processing_timeout):
            raise ValueError("Integration timeout must be finite")
        if len(self.version) > 100 or not self.version.isprintable():
            raise ValueError("Invalid engine version")

    @classmethod
    def from_env(cls, env=None):
        source = os.environ if env is None else env
        enabled = source.get("INTEGRATION_API_ENABLED", "0")
        if enabled == "0":
            return None
        if enabled != "1":
            raise ValueError("INTEGRATION_API_ENABLED must be 0 or 1")
        return cls(
            token=source.get("INTEGRATION_API_TOKEN", ""),
            database_path=source.get("INTEGRATION_DATABASE_PATH", str(Path(source.get("DATABASE_PATH", "data/bot.sqlite3")).with_name("integration.sqlite3"))),
            host=source.get("INTEGRATION_API_HOST", "127.0.0.1"),
            port=int(source.get("INTEGRATION_API_PORT", "8082")),
            version=source.get("ENGINE_VERSION", "unversioned"),
            processing_timeout=float(source.get("INTEGRATION_PROCESSING_TIMEOUT", "900")),
            requests_per_minute=int(source.get("INTEGRATION_REQUESTS_PER_MINUTE", "5")),
        )


class IntegrationStore:
    def __init__(self, path):
        self.path = Path(path)

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation avoids permissive temporary file modes.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS integration_requests (
                request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                status TEXT NOT NULL, result_json TEXT, error TEXT,
                engine_version TEXT NOT NULL, created_at REAL NOT NULL,
                updated_at REAL NOT NULL)""")
        self.interrupt_unfinished("service_restarted")

    def interrupt_unfinished(self, error):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE integration_requests SET status='interrupted', error=?, updated_at=? WHERE status='processing'", (error, time.time()))

    def get(self, request_id):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM integration_requests WHERE request_id=?", (request_id,)).fetchone()
        return dict(row) if row else None

    def count(self):
        with closing(sqlite3.connect(self.path)) as conn:
            return conn.execute("SELECT count(*) FROM integration_requests").fetchone()[0]

    def active_count(self):
        with closing(sqlite3.connect(self.path)) as conn:
            return conn.execute("SELECT count(*) FROM integration_requests WHERE status='processing'").fetchone()[0]

    def claim(self, request_id, fingerprint, version):
        now = time.time()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("INSERT INTO integration_requests VALUES (?,?,'processing',NULL,NULL,?,?,?)", (request_id, fingerprint, version, now, now))

    def finish(self, request_id, status, *, result=None, error=None):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE integration_requests SET status=?,result_json=?,error=?,updated_at=? WHERE request_id=?",
                         (status, json.dumps(result, ensure_ascii=False) if result is not None else None, error, time.time(), request_id))

    def unclaim(self, request_id):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("DELETE FROM integration_requests WHERE request_id=? AND status='processing'", (request_id,))

    @staticmethod
    def recent_metadata(path, limit=10):
        path = Path(path)
        if not path.exists():
            return []
        try:
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT request_id,status,engine_version,created_at,updated_at,error FROM integration_requests ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error:
            return []


class SilentProgress:
    """Engine progress sink: never sends Telegram messages or records content."""
    async def set_status_text(self, *args, **kwargs):
        pass

    async def set_live_transcript(self, *args, **kwargs):
        pass

    async def set_live_mode(self, *args, **kwargs):
        pass


@dataclass
class IntegrationJob:
    job_id: int
    user_id: int
    media_type: str = "voice"
    mode: str = "both"
    duration_seconds: int = 0
    mime_type: str = "audio/ogg"
    transcription_type: str = "clean"
    chat_id: int = 0  # Transport-local scope, not a real Telegram destination.
    language: str = "auto"
    user_name: str = "Вы"
    user_username: str | None = None
    chat_title: str = "Personal Auto Transcriber"
    message_processing_id: None = None
    processing_message: None = None
    progress: None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    next_model_event: asyncio.Event = field(default_factory=asyncio.Event)
    status: str = "active"
    current_model_index: int = -1
    current_model_name: str | None = None
    task: asyncio.Task | None = None
    manager: Any = None


class IntegrationAPI:
    def __init__(self, config, manager, processor, *, admin_user_id, max_media_bytes):
        if admin_user_id <= 0:
            raise ValueError("Integration API requires a configured ADMIN_USER_ID")
        self.config = config
        self.manager = manager
        self.processor = processor
        self.admin_user_id = admin_user_id
        self.max_media_bytes = max_media_bytes
        self.store = IntegrationStore(config.database_path)
        self.store.initialize()
        self._uploads = 0
        self._request_times = []
        self._runner = None
        self._accepting = True

    def _authorized(self, request):
        # Compare bytes: hmac handles arbitrary non-ASCII header input safely.
        actual = request.headers.get("Authorization", "").encode("utf-8")
        expected = ("Bearer " + self.config.token).encode("utf-8")
        return hmac.compare_digest(actual, expected)

    @property
    def engine(self):
        return {"name": "telegram-transcription-bot", "version": self.config.version}

    @staticmethod
    def _error(code, status, *, retry=False):
        return web.json_response({"api_version": API_VERSION, "error": code}, status=status,
                                 headers={"Retry-After": "2"} if retry else None)

    def _record_response(self, row):
        body = {"api_version": API_VERSION, "source": SOURCE,
                "engine": {"name": "telegram-transcription-bot", "version": row["engine_version"]},
                "request_id": row["request_id"], "status": row["status"]}
        if row["result_json"] is not None:
            body["result"] = json.loads(row["result_json"])
        if row["error"]:
            body["error"] = row["error"]
        return web.json_response(body, status=202 if row["status"] == "processing" else 200)

    async def status(self, request):
        if not self._authorized(request):
            return self._error("unauthorized", 401)
        return web.json_response({"api_version": API_VERSION, "source": SOURCE,
                                  "engine": self.engine, "max_media_bytes": self.max_media_bytes})

    async def get_result(self, request):
        if not self._authorized(request):
            return self._error("unauthorized", 401)
        request_id = request.match_info["request_id"]
        if not REQUEST_ID_RE.fullmatch(request_id):
            return self._error("invalid_request_id", 400)
        row = self.store.get(request_id)
        if row is None:
            return self._error("not_found", 404)
        # Polling is always 200, including in-progress records.
        response = self._record_response(row)
        response.set_status(200)
        return response

    async def submit(self, request):
        if not self._authorized(request):
            return self._error("unauthorized", 401)
        request_id = request.headers.get("X-Request-ID", "")
        query = request.query
        allowed = {"media_type", "mode", "duration_seconds", "transcription_type"}
        try:
            if not REQUEST_ID_RE.fullmatch(request_id) or set(query) - allowed or any(len(query.getall(k)) != 1 for k in query):
                raise ValueError
            meta = {"media_type": query.get("media_type", ""), "mode": query.get("mode", "both"),
                    "duration_seconds": int(query.get("duration_seconds", "0")),
                    "transcription_type": query.get("transcription_type", "clean")}
            if (meta["media_type"] not in ("voice", "video") or meta["mode"] not in ("both", "transcription_only")
                    or meta["transcription_type"] not in ("clean", "verbatim") or not 0 <= meta["duration_seconds"] <= 3600
                    or request.content_type not in MIME_TYPES or request.headers.get("Content-Encoding", "identity") != "identity"):
                raise ValueError
        except (ValueError, TypeError):
            return self._error("invalid_request", 400)
        if request.content_length is not None and request.content_length > self.max_media_bytes:
            return self._error("media_too_large", 413)
        if not self._accepting or self._uploads >= self.config.max_uploads:
            return self._error("busy", 503, retry=True)
        self._uploads += 1
        try:
            try:
                async with asyncio.timeout(30):
                    data = await request.read()
            except web.HTTPRequestEntityTooLarge:
                return self._error("media_too_large", 413)
            except (TimeoutError, ConnectionError):
                return self._error("upload_failed", 408)
            if len(data) > self.max_media_bytes:
                return self._error("media_too_large", 413)
            if not data:
                return self._error("empty_media", 400)
            fingerprint = hashlib.sha256(json.dumps(meta, sort_keys=True).encode() + b"\0" + request.content_type.encode() + b"\0" + data).hexdigest()
            row = self.store.get(request_id)
            if row:
                if not hmac.compare_digest(row["fingerprint"], fingerprint):
                    return self._error("idempotency_conflict", 409)
                return self._record_response(row)
            if self.store.active_count() >= self.config.max_active_jobs:
                return self._error("busy", 503, retry=True)
            now = time.monotonic()
            self._request_times = [stamp for stamp in self._request_times if stamp > now - 60]
            if len(self._request_times) >= self.config.requests_per_minute:
                return self._error("rate_limited", 429, retry=True)
            if self.store.count() >= self.config.max_records:
                return self._error("retention_capacity", 503)
            self.store.claim(request_id, fingerprint, self.config.version)
            job = IntegrationJob(job_id=self.manager.allocate_job_id(), user_id=self.admin_user_id,
                                 mime_type=request.content_type, **meta)
            try:
                admitted = await self.manager.submit_external(job, lambda: self._run(request_id, job, data))
            except BaseException:
                self.store.unclaim(request_id)
                raise
            if not admitted:
                self.store.unclaim(request_id)
                return self._error("busy", 503, retry=True)
            self._request_times.append(now)
            logger.info("INTEGRATION ACCEPTED | source=%s | request=%s", SOURCE, request_id)
            return self._record_response(self.store.get(request_id))
        finally:
            self._uploads -= 1

    async def _run(self, request_id, job, data):
        try:
            async with asyncio.timeout(self.config.processing_timeout):
                result = await self.processor(job, data)
            if len(json.dumps(result, ensure_ascii=False).encode()) > self.config.max_result_bytes:
                raise ValueError("result_too_large")
            self.store.finish(request_id, "succeeded", result=result)
            logger.info("INTEGRATION SUCCESS | source=%s | request=%s | model=%s", SOURCE, request_id, result["model_used"])
        except asyncio.CancelledError:
            self.store.finish(request_id, "interrupted", error="service_stopped")
            raise
        except Exception as error:
            code = "processing_timeout" if isinstance(error, TimeoutError) else "processing_failed"
            self.store.finish(request_id, "failed", error=code)
            logger.warning("INTEGRATION FAILED | source=%s | request=%s | type=%s", SOURCE, request_id, type(error).__name__)
        finally:
            await self.manager.finish(job)

    def application(self):
        @web.middleware
        async def safe_errors(request, handler):
            try:
                return await handler(request)
            except web.HTTPException as error:
                return self._error("http_error", error.status)
            except Exception as error:
                logger.warning("INTEGRATION HTTP ERROR | type=%s", type(error).__name__)
                return self._error("internal_error", 500)
        app = web.Application(client_max_size=self.max_media_bytes, middlewares=[safe_errors])
        app.router.add_get("/v1/status", self.status)
        app.router.add_post("/v1/transcriptions", self.submit)
        app.router.add_get("/v1/transcriptions/{request_id}", self.get_result)
        return app

    async def start(self):
        self._runner = web.AppRunner(self.application(), access_log=None, shutdown_timeout=2,
                                    handler_cancellation=False, auto_decompress=False)
        await self._runner.setup()
        try:
            await web.TCPSite(self._runner, self.config.host, self.config.port).start()
        except BaseException:
            await self._runner.cleanup()
            self._runner = None
            raise

    async def stop(self):
        self._accepting = False
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
