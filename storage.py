import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


DEFAULT_MODE = "both"
DEFAULT_LANGUAGE = "auto"
LATEST_SCHEMA_VERSION = 3

MIGRATION_1_SQL = """
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
"""

MIGRATION_2_SQL = """
CREATE TABLE IF NOT EXISTS pending_feedback (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (chat_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_pending_feedback_created
    ON pending_feedback(created_at);
"""

MIGRATION_3_SQL = """
CREATE TABLE IF NOT EXISTS changelog_broadcasts (
    changelog_version TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (changelog_version, user_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_changelog_broadcasts_user
    ON changelog_broadcasts(user_id, sent_at);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, db_path: str, *, read_only: bool = False) -> None:
        self.db_path = db_path
        self.read_only = read_only
        if not read_only:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        else:
            conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema_version_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            )
            """
        )
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version (version) VALUES (0)")

    def _get_schema_version(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            return 0
        return int(row["version"])

    def _set_schema_version(self, conn: sqlite3.Connection, version: int) -> None:
        updated = conn.execute("UPDATE schema_version SET version = ?", (version,))
        if updated.rowcount == 0:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))

    def _migration_1_initial_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(MIGRATION_1_SQL)

    def _migration_2_pending_feedback(self, conn: sqlite3.Connection) -> None:
        conn.executescript(MIGRATION_2_SQL)

    def _migration_3_changelog_broadcasts(self, conn: sqlite3.Connection) -> None:
        conn.executescript(MIGRATION_3_SQL)

    def init_db(self) -> None:
        migrations: dict[int, Callable[[sqlite3.Connection], None]] = {
            1: self._migration_1_initial_schema,
            2: self._migration_2_pending_feedback,
            3: self._migration_3_changelog_broadcasts,
        }

        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            self._ensure_schema_version_table(conn)
            current_version = self._get_schema_version(conn)

            if current_version > LATEST_SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {current_version} is newer than supported "
                    f"version {LATEST_SCHEMA_VERSION}."
                )

            for version in range(current_version + 1, LATEST_SCHEMA_VERSION + 1):
                migration = migrations[version]
                with conn:
                    migration(conn)
                    self._set_schema_version(conn, version)

    def get_schema_version(self) -> int:
        with self._connect() as conn:
            self._ensure_schema_version_table(conn)
            return self._get_schema_version(conn)

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
                "DELETE FROM rate_limits WHERE user_id = ? AND request_ts < ?",
                (user_id, threshold),
            )

    def check_and_record_rate_limit(
        self,
        user_id: int,
        rate_limit: int,
        now_ts: float,
        window_seconds: int = 60,
    ) -> bool:
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
                SELECT
                    s.user_id,
                    s.total_requests,
                    u.full_name,
                    u.username
                FROM user_stats s
                LEFT JOIN users u ON u.user_id = s.user_id
                ORDER BY s.total_requests DESC, s.user_id ASC
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
            "top_users": [
                {
                    "user_id": row["user_id"],
                    "full_name": row["full_name"],
                    "username": row["username"],
                    "total_requests": row["total_requests"],
                }
                for row in top_rows
            ],
            "blocked_users": [row["user_id"] for row in blocked_rows],
        }

    def get_dashboard_snapshot(self) -> dict[str, Any]:
        with self._connect() as conn:
            processing_totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_processing,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_processing,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_processing,
                    SUM(CASE WHEN status = 'ignored' THEN 1 ELSE 0 END) AS ignored_processing,
                    SUM(CASE WHEN status = 'rate_limited' THEN 1 ELSE 0 END) AS rate_limited_processing,
                    MAX(created_at) AS last_processed_at
                FROM message_processing
                """
            ).fetchone()
            failed_attempts = conn.execute(
                """
                SELECT COUNT(*) AS failed_attempts
                FROM model_attempts
                WHERE status != 'success'
                """
            ).fetchone()

        stats_snapshot = self.get_stats_snapshot()
        return {
            "total_processing": processing_totals["total_processing"] or 0,
            "success_processing": processing_totals["success_processing"] or 0,
            "failed_processing": processing_totals["failed_processing"] or 0,
            "ignored_processing": processing_totals["ignored_processing"] or 0,
            "rate_limited_processing": processing_totals["rate_limited_processing"] or 0,
            "failed_attempts": failed_attempts["failed_attempts"] or 0,
            "last_processed_at": processing_totals["last_processed_at"],
            "today": stats_snapshot["today"],
            "voice_total": stats_snapshot["voice_total"],
            "video_total": stats_snapshot["video_total"],
            "top_users": stats_snapshot["top_users"],
        }

    def get_recent_processing(self, limit: int, status: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT
                mp.id,
                mp.telegram_message_id,
                mp.chat_id,
                mp.user_id,
                mp.media_type,
                mp.duration_seconds,
                mp.file_size_kb,
                mp.scope_type,
                mp.scope_id,
                mp.mode,
                mp.language,
                mp.status,
                mp.created_at,
                mp.started_at,
                mp.completed_at,
                mp.processing_ms,
                mp.raw_model_response,
                mp.transcription_text,
                mp.summary_text,
                mp.final_reply_text,
                mp.model_used,
                mp.models_tried,
                mp.fallback_key_used,
                mp.error_code,
                mp.error_text,
                u.full_name,
                u.username,
                c.chat_type,
                c.title,
                c.username AS chat_username
            FROM message_processing mp
            LEFT JOIN users u ON u.user_id = mp.user_id
            LEFT JOIN chats c ON c.chat_id = mp.chat_id
        """
        params: list[Any] = []
        if status is not None:
            query += " WHERE mp.status = ?"
            params.append(status)
        query += " ORDER BY mp.id DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_recent_failed_attempts(self, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    ma.id AS attempt_id,
                    ma.message_processing_id,
                    ma.attempt_no,
                    ma.model_name,
                    ma.api_key_slot,
                    ma.status AS attempt_status,
                    ma.error_text AS attempt_error_text,
                    ma.started_at AS attempt_started_at,
                    ma.completed_at AS attempt_completed_at,
                    mp.id AS processing_id,
                    mp.telegram_message_id,
                    mp.chat_id,
                    mp.user_id,
                    mp.media_type,
                    mp.status AS processing_status,
                    mp.created_at AS processing_created_at,
                    mp.processing_ms,
                    mp.model_used,
                    mp.error_code,
                    u.full_name,
                    u.username,
                    c.chat_type,
                    c.title,
                    c.username AS chat_username
                FROM model_attempts ma
                INNER JOIN message_processing mp ON mp.id = ma.message_processing_id
                LEFT JOIN users u ON u.user_id = mp.user_id
                LEFT JOIN chats c ON c.chat_id = mp.chat_id
                WHERE ma.status != 'success'
                ORDER BY ma.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_processing_detail(self, processing_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    mp.*,
                    u.full_name,
                    u.username,
                    c.chat_type,
                    c.title,
                    c.username AS chat_username
                FROM message_processing mp
                LEFT JOIN users u ON u.user_id = mp.user_id
                LEFT JOIN chats c ON c.chat_id = mp.chat_id
                WHERE mp.id = ?
                LIMIT 1
                """,
                (processing_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_processing_attempts(self, processing_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id AS attempt_id,
                    message_processing_id,
                    attempt_no,
                    model_name,
                    api_key_slot,
                    status AS attempt_status,
                    error_text AS attempt_error_text,
                    started_at AS attempt_started_at,
                    completed_at AS attempt_completed_at
                FROM model_attempts
                WHERE message_processing_id = ?
                ORDER BY attempt_no ASC, id ASC
                """,
                (processing_id,),
            ).fetchall()
        return [dict(row) for row in rows]

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

    def list_model_attempts(self, message_processing_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    attempt_no,
                    model_name,
                    api_key_slot,
                    status,
                    error_text
                FROM model_attempts
                WHERE message_processing_id = ?
                ORDER BY attempt_no ASC, id ASC
                """,
                (message_processing_id,),
            ).fetchall()
        return [dict(row) for row in rows]

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

    def list_private_chat_users(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    u.user_id,
                    u.full_name,
                    u.username
                FROM users u
                INNER JOIN chats c
                    ON c.chat_id = u.user_id
                WHERE c.chat_type = 'private'
                ORDER BY u.user_id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def has_changelog_been_sent(self, changelog_version: str, user_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM changelog_broadcasts
                WHERE changelog_version = ? AND user_id = ?
                LIMIT 1
                """,
                (changelog_version, user_id),
            ).fetchone()
        return row is not None

    def mark_changelog_sent(self, changelog_version: str, user_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO changelog_broadcasts (changelog_version, user_id, sent_at)
                VALUES (?, ?, ?)
                """,
                (changelog_version, user_id, utc_now()),
            )
            return cur.rowcount > 0
