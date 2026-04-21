import sqlite3

from storage import LATEST_SCHEMA_VERSION, MIGRATION_1_SQL, Storage


def make_storage(tmp_path) -> Storage:
    db_path = tmp_path / "bot.sqlite3"
    storage = Storage(str(db_path))
    storage.init_db()
    return storage


def test_init_db_sets_latest_schema_version_on_empty_database(tmp_path) -> None:
    storage = make_storage(tmp_path)

    assert storage.get_schema_version() == LATEST_SCHEMA_VERSION

    with sqlite3.connect(storage.db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "pending_feedback" in tables
    assert "changelog_broadcasts" in tables


def test_init_db_migrates_existing_version_one_database(tmp_path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        conn.executescript(MIGRATION_1_SQL)

    storage = Storage(str(db_path))
    storage.init_db()

    assert storage.get_schema_version() == LATEST_SCHEMA_VERSION

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "pending_feedback" in tables
    assert "changelog_broadcasts" in tables


def test_feedback_pending_state_roundtrip(tmp_path) -> None:
    storage = make_storage(tmp_path)

    storage.set_pending_feedback(chat_id=10, user_id=20)

    assert storage.has_pending_feedback(chat_id=10, user_id=20) is True

    storage.clear_pending_feedback(chat_id=10, user_id=20)

    assert storage.has_pending_feedback(chat_id=10, user_id=20) is False


def test_settings_are_saved_per_scope(tmp_path) -> None:
    storage = make_storage(tmp_path)

    storage.set_mode("user", 1, "summary_only")
    storage.set_language("user", 1, "en")
    storage.set_mode("chat", -100, "tldr")
    storage.set_language("chat", -100, "ru")

    assert storage.get_settings("user", 1) == ("summary_only", "en")
    assert storage.get_settings("chat", -100) == ("tldr", "ru")


def test_get_stats_snapshot_returns_joined_users_and_stable_order(tmp_path) -> None:
    storage = make_storage(tmp_path)

    storage.upsert_user(2, "Alice Example", "alice")
    storage.upsert_user(1, "Bob Example", None)
    storage.upsert_user(3, "Carol Example", "carol")

    storage.increment_stats(2, "voice")
    storage.increment_stats(2, "video")
    storage.increment_stats(1, "voice")
    storage.increment_stats(1, "voice")
    storage.increment_stats(3, "video")

    snapshot = storage.get_stats_snapshot()

    assert snapshot["today"] == 5
    assert snapshot["voice_total"] == 3
    assert snapshot["video_total"] == 2
    assert snapshot["top_users"] == [
        {
            "user_id": 1,
            "full_name": "Bob Example",
            "username": None,
            "total_requests": 2,
        },
        {
            "user_id": 2,
            "full_name": "Alice Example",
            "username": "alice",
            "total_requests": 2,
        },
        {
            "user_id": 3,
            "full_name": "Carol Example",
            "username": "carol",
            "total_requests": 1,
        },
    ]


def test_rate_limit_allows_until_limit_then_blocks_and_expires_old_window(tmp_path) -> None:
    storage = make_storage(tmp_path)

    assert storage.check_and_record_rate_limit(user_id=10, rate_limit=2, now_ts=100.0) is True
    assert storage.check_and_record_rate_limit(user_id=10, rate_limit=2, now_ts=120.0) is True
    assert storage.check_and_record_rate_limit(user_id=10, rate_limit=2, now_ts=130.0) is False
    assert storage.check_and_record_rate_limit(user_id=10, rate_limit=2, now_ts=161.0) is True


def test_prune_rate_limits_removes_old_rows_for_user(tmp_path) -> None:
    storage = make_storage(tmp_path)

    storage.check_and_record_rate_limit(user_id=10, rate_limit=5, now_ts=100.0)
    storage.check_and_record_rate_limit(user_id=10, rate_limit=5, now_ts=120.0)
    storage.prune_rate_limits(user_id=10, now_ts=181.0)

    with sqlite3.connect(storage.db_path) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM rate_limits WHERE user_id = 10"
        ).fetchone()[0]

    assert remaining == 0


def test_model_attempts_persist_in_attempt_order(tmp_path) -> None:
    storage = make_storage(tmp_path)

    storage.upsert_user(77, "Tester", "tester")
    storage.upsert_chat(77, "private", None, "tester")
    message_processing_id = storage.create_message_processing(
        telegram_message_id=1,
        chat_id=77,
        user_id=77,
        media_type="voice",
        telegram_file_id="file-1",
        duration_seconds=12,
        file_size_kb=10,
        scope_type="user",
        scope_id=77,
        mode="both",
        language="auto",
        status="started",
    )

    storage.add_model_attempt(
        message_processing_id=message_processing_id,
        attempt_no=1,
        model_name="gemini-3.1-flash-lite-preview",
        api_key_slot="primary",
        status="error",
        started_at="2026-04-21T00:00:00+00:00",
        completed_at="2026-04-21T00:00:05+00:00",
        error_text="503 unavailable",
    )
    storage.add_model_attempt(
        message_processing_id=message_processing_id,
        attempt_no=2,
        model_name="gemini-2.5-flash",
        api_key_slot="backup",
        status="success",
        started_at="2026-04-21T00:00:06+00:00",
        completed_at="2026-04-21T00:00:07+00:00",
    )

    assert storage.list_model_attempts(message_processing_id) == [
        {
            "attempt_no": 1,
            "model_name": "gemini-3.1-flash-lite-preview",
            "api_key_slot": "primary",
            "status": "error",
            "error_text": "503 unavailable",
        },
        {
            "attempt_no": 2,
            "model_name": "gemini-2.5-flash",
            "api_key_slot": "backup",
            "status": "success",
            "error_text": None,
        },
    ]


def test_changelog_broadcast_deduplicates_per_version_and_private_users(tmp_path) -> None:
    storage = make_storage(tmp_path)

    storage.upsert_user(1, "Private User", "private_user")
    storage.upsert_chat(1, "private", None, "private_user")
    storage.upsert_user(2, "Group User", "group_user")
    storage.upsert_chat(-100, "group", "Test Group", None)

    assert storage.list_private_chat_users() == [
        {
            "user_id": 1,
            "full_name": "Private User",
            "username": "private_user",
        }
    ]
    assert storage.has_changelog_been_sent("v1", 1) is False
    assert storage.mark_changelog_sent("v1", 1) is True
    assert storage.has_changelog_been_sent("v1", 1) is True
    assert storage.mark_changelog_sent("v1", 1) is False
    assert storage.has_changelog_been_sent("v2", 1) is False


def test_recent_processing_and_detail_queries(tmp_path) -> None:
    storage = make_storage(tmp_path)

    storage.upsert_user(1, "Alice Example", "alice")
    storage.upsert_chat(-100, "supergroup", "Test Group", None)
    first_id = storage.create_message_processing(
        telegram_message_id=10,
        chat_id=-100,
        user_id=1,
        media_type="voice",
        telegram_file_id="voice-1",
        duration_seconds=20,
        file_size_kb=100,
        scope_type="chat",
        scope_id=-100,
        mode="both",
        language="auto",
        status="failed",
    )
    storage.update_message_processing(
        first_id,
        processing_ms=4200,
        model_used="gemini-2.5-flash",
        models_tried="gemini-3.1-flash-lite-preview -> gemini-2.5-flash",
        error_code="model_overloaded",
        error_text="503 unavailable",
        final_reply_text="temporary failure",
    )
    second_id = storage.create_message_processing(
        telegram_message_id=11,
        chat_id=-100,
        user_id=1,
        media_type="video",
        telegram_file_id="video-1",
        duration_seconds=35,
        file_size_kb=220,
        scope_type="chat",
        scope_id=-100,
        mode="summary_only",
        language="ru",
        status="success",
    )
    storage.update_message_processing(
        second_id,
        processing_ms=8100,
        model_used="gemini-3.1-flash-lite-preview",
        raw_model_response="full response",
        transcription_text="transcription",
        summary_text="summary",
        final_reply_text="reply",
    )

    recent = storage.get_recent_processing(limit=10)
    success_only = storage.get_recent_processing(limit=10, status="success")
    detail = storage.get_processing_detail(second_id)

    assert [row["id"] for row in recent] == [second_id, first_id]
    assert [row["id"] for row in success_only] == [second_id]
    assert detail is not None
    assert detail["username"] == "alice"
    assert detail["title"] == "Test Group"
    assert detail["summary_text"] == "summary"


def test_recent_failed_attempts_and_processing_attempts_queries(tmp_path) -> None:
    storage = make_storage(tmp_path)

    storage.upsert_user(7, "Tester", "tester")
    storage.upsert_chat(7, "private", None, "tester")
    processing_id = storage.create_message_processing(
        telegram_message_id=99,
        chat_id=7,
        user_id=7,
        media_type="voice",
        telegram_file_id="voice-99",
        duration_seconds=12,
        file_size_kb=10,
        scope_type="user",
        scope_id=7,
        mode="both",
        language="auto",
        status="failed",
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
    storage.add_model_attempt(
        message_processing_id=processing_id,
        attempt_no=2,
        model_name="gemini-2.5-flash",
        api_key_slot="backup",
        status="success",
        started_at="2026-04-21T00:00:04+00:00",
        completed_at="2026-04-21T00:00:05+00:00",
    )

    errors = storage.get_recent_failed_attempts(limit=5)
    attempts = storage.get_processing_attempts(processing_id)

    assert len(errors) == 1
    assert errors[0]["processing_id"] == processing_id
    assert errors[0]["username"] == "tester"
    assert attempts == [
        {
            "attempt_id": attempts[0]["attempt_id"],
            "message_processing_id": processing_id,
            "attempt_no": 1,
            "model_name": "gemini-3.1-flash-lite-preview",
            "api_key_slot": "primary",
            "attempt_status": "error",
            "attempt_error_text": "503 unavailable",
            "attempt_started_at": "2026-04-21T00:00:00+00:00",
            "attempt_completed_at": "2026-04-21T00:00:03+00:00",
        },
        {
            "attempt_id": attempts[1]["attempt_id"],
            "message_processing_id": processing_id,
            "attempt_no": 2,
            "model_name": "gemini-2.5-flash",
            "api_key_slot": "backup",
            "attempt_status": "success",
            "attempt_error_text": None,
            "attempt_started_at": "2026-04-21T00:00:04+00:00",
            "attempt_completed_at": "2026-04-21T00:00:05+00:00",
        },
    ]


def test_dashboard_snapshot_includes_processing_counters(tmp_path) -> None:
    storage = make_storage(tmp_path)

    storage.upsert_user(1, "Alice", "alice")
    storage.upsert_chat(1, "private", None, "alice")
    for status in ("success", "failed", "ignored", "rate_limited"):
        processing_id = storage.create_message_processing(
            telegram_message_id=1,
            chat_id=1,
            user_id=1,
            media_type="voice",
            telegram_file_id=f"file-{status}",
            duration_seconds=5,
            file_size_kb=5,
            scope_type="user",
            scope_id=1,
            mode="both",
            language="auto",
            status=status,
        )
        storage.update_message_processing(processing_id, processing_ms=1000)
    storage.add_model_attempt(
        message_processing_id=processing_id,
        attempt_no=1,
        model_name="gemini-3.1-flash-lite-preview",
        api_key_slot="primary",
        status="error",
        started_at="2026-04-21T00:00:00+00:00",
        completed_at="2026-04-21T00:00:05+00:00",
        error_text="503 unavailable",
    )

    snapshot = storage.get_dashboard_snapshot()

    assert snapshot["total_processing"] == 4
    assert snapshot["success_processing"] == 1
    assert snapshot["failed_processing"] == 1
    assert snapshot["ignored_processing"] == 1
    assert snapshot["rate_limited_processing"] == 1
    assert snapshot["failed_attempts"] == 1
    assert snapshot["last_processed_at"] is not None
