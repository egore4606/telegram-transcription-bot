import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MODE = "both"
DEFAULT_LANGUAGE = "auto"
SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER NOT NULL
                )
                """
            )
            row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings_scopes (
                    scope_type TEXT NOT NULL,
                    scope_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope_type, scope_id)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    scope_type TEXT NOT NULL,
                    scope_id INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    language TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope_type, scope_id),
                    FOREIGN KEY (scope_type, scope_id)
                        REFERENCES settings_scopes(scope_type, scope_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    username TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chats (
                    chat_id INTEGER PRIMARY KEY,
                    chat_type TEXT NOT NULL,
                    title TEXT,
                    username TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ignored_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    set_by_user_id INTEGER,
                    chat_id INTEGER,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rate_limits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    request_ts REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS daily_stats (
                    stat_date TEXT PRIMARY KEY,
                    voice_count INTEGER NOT NULL DEFAULT 0,
                    video_count INTEGER NOT NULL DEFAULT 0,
                    total_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS user_stats (
                    user_id INTEGER PRIMARY KEY,
                    total_requests INTEGER NOT NULL DEFAULT 0,
                    voice_count INTEGER NOT NULL DEFAULT 0,
                    video_count INTEGER NOT NULL DEFAULT 0,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS message_processing (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_message_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    media_type TEXT NOT NULL,
                    telegram_file_id TEXT NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    file_size_kb INTEGER,
                    scope_type TEXT NOT NULL,
                    scope_id INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    language TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    processing_ms INTEGER,
                    raw_model_response TEXT,
                    transcription_text TEXT,
                    summary_text TEXT,
                    final_reply_text TEXT,
                    model_used TEXT,
                    models_tried TEXT,
                    fallback_key_used INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_text TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
                );

                CREATE TABLE IF NOT EXISTS model_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_processing_id INTEGER NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    model_name TEXT NOT NULL,
                    api_key_slot TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_text TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    FOREIGN KEY (message_processing_id)
                        REFERENCES message_processing(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS pending_feedback (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_ignored_users_lookup
                    ON ignored_users(user_id, source, chat_id);
                CREATE INDEX IF NOT EXISTS idx_rate_limits_user_ts
                    ON rate_limits(user_id, request_ts);
                CREATE INDEX IF NOT EXISTS idx_message_processing_chat
                    ON message_processing(chat_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_message_processing_user
                    ON message_processing(user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_model_attempts_processing
                    ON model_attempts(message_processing_id, attempt_no);
                CREATE INDEX IF NOT EXISTS idx_pending_feedback_created
                    ON pending_feedback(created_at);
                """
            )

    def upsert_user(self, user_id: int, full_name: str, username: str | None) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, full_name, username, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    full_name = excluded.full_name,
                    username = excluded.username,
                    last_seen_at = excluded.last_seen_at
                """,
                (user_id, full_name, username, now, now),
            )

    def upsert_chat(self, chat_id: int, chat_type: str, title: str | None, username: str | None) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chats (chat_id, chat_type, title, username, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    chat_type = excluded.chat_type,
                    title = excluded.title,
                    username = excluded.username,
                    last_seen_at = excluded.last_seen_at
                """,
                (chat_id, chat_type, title, username, now, now),
            )

    def ensure_scope(self, scope_type: str, scope_id: int) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings_scopes (scope_type, scope_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scope_type, scope_id) DO UPDATE SET
                    updated_at = excluded.updated_at
                """,
                (scope_type, scope_id, now, now),
            )

    def get_settings(self, scope_type: str, scope_id: int) -> tuple[str, str]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT mode, language
                FROM settings
                WHERE scope_type = ? AND scope_id = ?
                """,
                (scope_type, scope_id),
            ).fetchone()
        if row is None:
            return DEFAULT_MODE, DEFAULT_LANGUAGE
        return row["mode"], row["language"]

    def save_settings(self, scope_type: str, scope_id: int, mode: str, language: str) -> None:
        now = utc_now()
        self.ensure_scope(scope_type, scope_id)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (scope_type, scope_id, mode, language, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope_type, scope_id) DO UPDATE SET
                    mode = excluded.mode,
                    language = excluded.language,
                    updated_at = excluded.updated_at
                """,
                (scope_type, scope_id, mode, language, now, now),
            )

    def set_mode(self, scope_type: str, scope_id: int, mode: str) -> None:
        _, language = self.get_settings(scope_type, scope_id)
        self.save_settings(scope_type, scope_id, mode, language)

    def set_language(self, scope_type: str, scope_id: int, language: str) -> None:
        mode, _ = self.get_settings(scope_type, scope_id)
        self.save_settings(scope_type, scope_id, mode, language)

    def add_admin_block(self, target_user_id: int, admin_user_id: int) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM ignored_users WHERE user_id = ? AND source = 'admin_block'",
                (target_user_id,),
            )
            conn.execute(
                """
                INSERT INTO ignored_users (user_id, source, set_by_user_id, chat_id, created_at)
                VALUES (?, 'admin_block', ?, NULL, ?)
                """,
                (target_user_id, admin_user_id, now),
            )

    def remove_admin_block(self, target_user_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM ignored_users WHERE user_id = ? AND source = 'admin_block'",
                (target_user_id,),
            )
            return cur.rowcount > 0

    def toggle_group_ignore(self, chat_id: int, target_user_id: int, actor_user_id: int) -> bool:
        now = utc_now()
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT id
                FROM ignored_users
                WHERE user_id = ? AND source = 'group_ignore' AND chat_id = ?
                """,
                (target_user_id, chat_id),
            ).fetchone()
            if existing:
                conn.execute("DELETE FROM ignored_users WHERE id = ?", (existing["id"],))
                return False

            conn.execute(
                """
                INSERT INTO ignored_users (user_id, source, set_by_user_id, chat_id, created_at)
                VALUES (?, 'group_ignore', ?, ?, ?)
                """,
                (target_user_id, actor_user_id, chat_id, now),
            )
            return True

    def is_user_ignored(self, user_id: int, chat_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM ignored_users
                WHERE user_id = ?
                  AND (source = 'admin_block' OR (source = 'group_ignore' AND chat_id = ?))
                LIMIT 1
                """,
                (user_id, chat_id),
            ).fetchone()
        return row is not None

    def list_blocked_user_ids(self) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT user_id FROM ignored_users ORDER BY user_id"
            ).fetchall()
        return [row["user_id"] for row in rows]

    def prune_rate_limits(self, user_id: int, now_ts: float, window_seconds: int = 60) -> None:
        threshold = now_ts - window_seconds
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM rate_limits WHERE request_ts < ? OR user_id = ? AND request_ts < ?",
                (threshold, user_id, threshold),
            )

    def check_and_record_rate_limit(self, user_id: int, rate_limit: int, now_ts: float, window_seconds: int = 60) -> bool:
        threshold = now_ts - window_seconds
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM rate_limits WHERE request_ts < ?",
                (threshold,),
            )
            current = conn.execute(
                "SELECT COUNT(*) AS count FROM rate_limits WHERE user_id = ? AND request_ts >= ?",
                (user_id, threshold),
            ).fetchone()
            if current["count"] >= rate_limit:
                return False
            conn.execute(
                "INSERT INTO rate_limits (user_id, request_ts) VALUES (?, ?)",
                (user_id, now_ts),
            )
            return True

    def increment_stats(self, user_id: int, media_type: str) -> None:
        now = utc_now()
        today = datetime.now(timezone.utc).date().isoformat()
        voice_inc = 1 if media_type == "voice" else 0
        video_inc = 1 if media_type == "video" else 0
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_stats (stat_date, voice_count, video_count, total_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(stat_date) DO UPDATE SET
                    voice_count = voice_count + excluded.voice_count,
                    video_count = video_count + excluded.video_count,
                    total_count = total_count + 1
                """,
                (today, voice_inc, video_inc),
            )
            conn.execute(
                """
                INSERT INTO user_stats (user_id, total_requests, voice_count, video_count, last_seen_at)
                VALUES (?, 1, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    total_requests = total_requests + 1,
                    voice_count = voice_count + excluded.voice_count,
                    video_count = video_count + excluded.video_count,
                    last_seen_at = excluded.last_seen_at
                """,
                (user_id, voice_inc, video_inc, now),
            )

    def get_stats_snapshot(self) -> dict[str, Any]:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._connect() as conn:
            today_row = conn.execute(
                """
                SELECT voice_count, video_count, total_count
                FROM daily_stats
                WHERE stat_date = ?
                """,
                (today,),
            ).fetchone()
            totals = conn.execute(
                """
                SELECT
                    COALESCE(SUM(voice_count), 0) AS voice_total,
                    COALESCE(SUM(video_count), 0) AS video_total
                FROM daily_stats
                """
            ).fetchone()
            top_rows = conn.execute(
                """
                SELECT user_id, total_requests
                FROM user_stats
                ORDER BY total_requests DESC, user_id ASC
                LIMIT 5
                """
            ).fetchall()
            blocked_rows = conn.execute(
                "SELECT DISTINCT user_id FROM ignored_users ORDER BY user_id"
            ).fetchall()

        return {
            "today": today_row["total_count"] if today_row else 0,
            "voice_total": totals["voice_total"],
            "video_total": totals["video_total"],
            "top_users": [(str(row["user_id"]), row["total_requests"]) for row in top_rows],
            "blocked_users": [row["user_id"] for row in blocked_rows],
        }

    def create_message_processing(
        self,
        *,
        telegram_message_id: int,
        chat_id: int,
        user_id: int,
        media_type: str,
        telegram_file_id: str,
        duration_seconds: int,
        file_size_kb: int | None,
        scope_type: str,
        scope_id: int,
        mode: str,
        language: str,
        status: str,
        started_at: str | None = None,
        completed_at: str | None = None,
        processing_ms: int | None = None,
        final_reply_text: str | None = None,
        error_code: str | None = None,
        error_text: str | None = None,
    ) -> int:
        created_at = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO message_processing (
                    telegram_message_id,
                    chat_id,
                    user_id,
                    media_type,
                    telegram_file_id,
                    duration_seconds,
                    file_size_kb,
                    scope_type,
                    scope_id,
                    mode,
                    language,
                    status,
                    created_at,
                    started_at,
                    completed_at,
                    processing_ms,
                    final_reply_text,
                    error_code,
                    error_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    telegram_message_id,
                    chat_id,
                    user_id,
                    media_type,
                    telegram_file_id,
                    duration_seconds,
                    file_size_kb,
                    scope_type,
                    scope_id,
                    mode,
                    language,
                    status,
                    created_at,
                    started_at,
                    completed_at,
                    processing_ms,
                    final_reply_text,
                    error_code,
                    error_text,
                ),
            )
            return int(cur.lastrowid)

    def update_message_processing(self, message_processing_id: int, **fields: Any) -> None:
        if not fields:
            return

        assignments = ", ".join(f"{field} = ?" for field in fields)
        values = list(fields.values())
        values.append(message_processing_id)

        with self._connect() as conn:
            conn.execute(
                f"UPDATE message_processing SET {assignments} WHERE id = ?",
                values,
            )

    def add_model_attempt(
        self,
        *,
        message_processing_id: int,
        attempt_no: int,
        model_name: str,
        api_key_slot: str,
        status: str,
        started_at: str,
        completed_at: str,
        error_text: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_attempts (
                    message_processing_id,
                    attempt_no,
                    model_name,
                    api_key_slot,
                    status,
                    error_text,
                    started_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_processing_id,
                    attempt_no,
                    model_name,
                    api_key_slot,
                    status,
                    error_text,
                    started_at,
                    completed_at,
                ),
            )

    def set_pending_feedback(self, chat_id: int, user_id: int) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_feedback (chat_id, user_id, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET
                    created_at = excluded.created_at
                """,
                (chat_id, user_id, now),
            )

    def has_pending_feedback(self, chat_id: int, user_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM pending_feedback
                WHERE chat_id = ? AND user_id = ?
                LIMIT 1
                """,
                (chat_id, user_id),
            ).fetchone()
        return row is not None

    def clear_pending_feedback(self, chat_id: int, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM pending_feedback WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
