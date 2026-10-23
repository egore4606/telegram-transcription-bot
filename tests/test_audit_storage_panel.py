import asyncio
from pathlib import Path
import sqlite3
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

import bot
from admin_panel import create_app
from storage import LATEST_SCHEMA_VERSION, Storage
from test_admin_panel import seed_processing_rows
from test_audit_core import job_fixture


def test_frozen_v1_upgrade_preserves_settings_history_and_is_idempotent(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.executescript((Path(__file__).parent / "fixtures/schema-v1.sql").read_text())
        for table in ("settings", "message_processing"):
            assert "transcription_type" not in [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
    finally:
        connection.close()
    store = Storage(str(path))
    for _ in range(2):
        store.init_db()
        assert store.get_schema_version() == LATEST_SCHEMA_VERSION
        assert store.get_settings("user", 42) == ("summary_only", "de & fixture", "clean")
        detail = store.get_processing_detail(1)
        assert detail["transcription_text"] == "legacy fixture transcript"
        assert detail["summary_text"] == "legacy fixture summary"
        assert detail["full_name"] == "Legacy fixture"
        assert detail["transcription_type"] == "clean"
        assert len(store.get_processing_attempts(1)) == 1


def test_panel_escapes_stored_markup_and_rejects_post(tmp_path):
    store = Storage(str(tmp_path / "panel.sqlite3"))
    store.init_db()
    processing_id = seed_processing_rows(store)
    payload = '<script>alert("fixture")</script> & text'
    store.upsert_user(1, payload, payload)
    store.upsert_chat(-100, "supergroup", payload, None)
    store.update_message_processing(processing_id, transcription_text=payload, raw_model_response=payload, error_text=payload)
    client = create_app(store.db_path).test_client()
    for route in ("/", "/history", "/errors", f"/processing/{processing_id}"):
        response = client.get(route)
        assert response.status_code == 200
        text = response.get_data(as_text=True)
        assert '<script>alert("fixture")</script>' not in text
        assert "&lt;script&gt;" in text
        assert client.post(route, data={"transcription_text": "overwrite"}).status_code == 405
    assert store.get_processing_detail(processing_id)["transcription_text"] == payload


@pytest.mark.parametrize("mode,language", [("both", "auto"), ("both", "de"), ("summary_only", "auto"), ("tldr", "auto"), ("transcription_only", "de")])
def test_dedicated_postprocess_requires_selected_fields(monkeypatch, mode, language):
    monkeypatch.setattr(bot, "GEMINI_MODEL_CHAIN", ["gemini-3.5-transcribe"])
    monkeypatch.setattr(bot, "call_gemini_transcribe", AsyncMock(return_value=("fixture transcript", "gemini-3.5-transcribe")))
    raw = '{"transcription":"text","summary":""}' if mode != "transcription_only" else '{"transcription":"","summary":"summary"}'
    client = NS(models=NS(generate_content=AsyncMock(return_value=NS(text=raw))))
    monkeypatch.setattr(bot, "gemini_async_clients", [client])
    monkeypatch.setattr(bot, "STORAGE", Mock())
    job = job_fixture(mode=mode, language=language)
    with pytest.raises(bot.InvalidStructuredResponse):
        asyncio.run(bot.call_gemini_with_retries([], NS(set_status_text=AsyncMock()), 1,
                                                {"attempt_no": 1, "models_tried": []}, job,
                                                media_data=b"synthetic", mime_type="audio/ogg"))
