import os
import socket
import tempfile

import pytest


# Never let inherited service configuration reach imports (including backup keys).
for name in tuple(os.environ):
    if name.startswith(("GOOGLE_", "GCLOUD_", "GEMINI_")):
        os.environ.pop(name)
for name in (
    "GEMINI_API_KEY_2", "GEMINI_SUMMARY_MODEL", "RATE_LIMIT", "MODEL_REQUEST_TIMEOUT",
    "PRIMARY_MODEL_ATTEMPTS", "FALLBACK_MODEL_ATTEMPTS", "PENDING_FEEDBACK_TTL_SECONDS",
    "COMMAND_RATE_LIMIT", "COMMAND_RATE_LIMIT_WINDOW_SECONDS", "MAX_ACTIVE_JOBS_PER_USER",
    "MAX_ACTIVE_JOBS_PER_CHAT", "MAX_ACTIVE_JOBS_GLOBAL", "MAX_QUEUED_JOBS",
    "MAX_QUEUED_JOBS_PER_USER", "MAX_MEDIA_BYTES", "PROGRESS_PRIVATE_REFRESH_INTERVAL",
    "PROGRESS_GROUP_REFRESH_INTERVAL", "ADMIN_PANEL_HOST", "ADMIN_PANEL_PORT",
):
    os.environ.pop(name, None)
_test_directory = tempfile.TemporaryDirectory(prefix="telegrambot-offline-")
os.environ.update(
    TELEGRAM_TOKEN="test-telegram-token",
    GEMINI_API_KEY="test-gemini-key",
    GEMINI_MODEL="gemini-3.1-flash-lite",
    DATABASE_PATH=os.path.join(_test_directory.name, "test.sqlite3"),
    ADMIN_USER_ID="123456789",
    PTB_TIMEDELTA="0",
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network access is forbidden in offline tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
