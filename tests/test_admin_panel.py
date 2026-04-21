from admin_panel import create_app
from storage import Storage


def make_storage(tmp_path) -> Storage:
    db_path = tmp_path / "panel.sqlite3"
    storage = Storage(str(db_path))
    storage.init_db()
    return storage


def seed_processing_rows(storage: Storage) -> int:
    storage.upsert_user(1, "Alice Example", "alice")
    storage.upsert_chat(-100, "supergroup", "Test Group", None)
    processing_id = storage.create_message_processing(
        telegram_message_id=321,
        chat_id=-100,
        user_id=1,
        media_type="voice",
        telegram_file_id="voice-321",
        duration_seconds=18,
        file_size_kb=24,
        scope_type="chat",
        scope_id=-100,
        mode="both",
        language="auto",
        status="failed",
    )
    storage.update_message_processing(
        processing_id,
        processing_ms=5300,
        raw_model_response="RAW RESPONSE",
        transcription_text="TRANSCRIPTION",
        summary_text="SUMMARY",
        final_reply_text="FINAL REPLY",
        model_used="gemini-2.5-flash",
        models_tried="gemini-3.1-flash-lite-preview -> gemini-2.5-flash",
        error_code="model_overloaded",
        error_text="503 unavailable",
    )
    storage.add_model_attempt(
        message_processing_id=processing_id,
        attempt_no=1,
        model_name="gemini-3.1-flash-lite-preview",
        api_key_slot="primary",
        status="error",
        started_at="2026-04-21T00:00:00+00:00",
        completed_at="2026-04-21T00:00:03+00:00",
        error_text="503 unavailable",
    )
    return processing_id


def test_dashboard_route_renders_stats(tmp_path) -> None:
    storage = make_storage(tmp_path)
    seed_processing_rows(storage)
    app = create_app(storage.db_path)

    client = app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Telegram Bot Admin Panel" in body
    assert "Total Processing" in body
    assert "Test Group" in body


def test_history_route_filters_by_status(tmp_path) -> None:
    storage = make_storage(tmp_path)
    processing_id = seed_processing_rows(storage)
    success_id = storage.create_message_processing(
        telegram_message_id=322,
        chat_id=-100,
        user_id=1,
        media_type="video",
        telegram_file_id="video-322",
        duration_seconds=21,
        file_size_kb=40,
        scope_type="chat",
        scope_id=-100,
        mode="summary_only",
        language="ru",
        status="success",
    )
    app = create_app(storage.db_path)

    client = app.test_client()
    response = client.get("/history?status=failed&limit=5")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f"/processing/{processing_id}" in body
    assert f"/processing/{success_id}" not in body


def test_errors_route_renders_failed_attempts(tmp_path) -> None:
    storage = make_storage(tmp_path)
    processing_id = seed_processing_rows(storage)
    app = create_app(storage.db_path)

    client = app.test_client()
    response = client.get("/errors?limit=5")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Recent Failed Model Attempts" in body
    assert f"/processing/{processing_id}" in body
    assert "gemini-3.1-flash-lite-preview" in body


def test_processing_detail_route_and_404(tmp_path) -> None:
    storage = make_storage(tmp_path)
    processing_id = seed_processing_rows(storage)
    app = create_app(storage.db_path)

    client = app.test_client()
    response = client.get(f"/processing/{processing_id}")
    missing = client.get("/processing/9999")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Processing #" in body
    assert "RAW RESPONSE" in body
    assert "FINAL REPLY" in body
    assert missing.status_code == 404
