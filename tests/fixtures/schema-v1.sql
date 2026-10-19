-- Frozen pre-transcription_type schema. Do not generate from current migrations.
CREATE TABLE schema_version (version INTEGER NOT NULL);
INSERT INTO schema_version VALUES (1);
CREATE TABLE settings_scopes (
    scope_type TEXT NOT NULL, scope_id INTEGER NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (scope_type, scope_id)
);
CREATE TABLE settings (
    scope_type TEXT NOT NULL, scope_id INTEGER NOT NULL,
    mode TEXT NOT NULL, language TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (scope_type, scope_id),
    FOREIGN KEY (scope_type, scope_id) REFERENCES settings_scopes(scope_type, scope_id) ON DELETE CASCADE
);
CREATE TABLE users (
    user_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, username TEXT,
    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
);
CREATE TABLE chats (
    chat_id INTEGER PRIMARY KEY, chat_type TEXT NOT NULL, title TEXT, username TEXT,
    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
);
CREATE TABLE ignored_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, source TEXT NOT NULL,
    set_by_user_id INTEGER, chat_id INTEGER, created_at TEXT NOT NULL
);
CREATE TABLE rate_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, request_ts REAL NOT NULL
);
CREATE TABLE daily_stats (
    stat_date TEXT PRIMARY KEY, voice_count INTEGER NOT NULL DEFAULT 0,
    video_count INTEGER NOT NULL DEFAULT 0, total_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE user_stats (
    user_id INTEGER PRIMARY KEY, total_requests INTEGER NOT NULL DEFAULT 0,
    voice_count INTEGER NOT NULL DEFAULT 0, video_count INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT NOT NULL
);
CREATE TABLE message_processing (
    id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_message_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, media_type TEXT NOT NULL,
    telegram_file_id TEXT NOT NULL, duration_seconds INTEGER NOT NULL, file_size_kb INTEGER,
    scope_type TEXT NOT NULL, scope_id INTEGER NOT NULL, mode TEXT NOT NULL, language TEXT NOT NULL,
    status TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT,
    processing_ms INTEGER, raw_model_response TEXT, transcription_text TEXT, summary_text TEXT,
    final_reply_text TEXT, model_used TEXT, models_tried TEXT, fallback_key_used INTEGER NOT NULL DEFAULT 0,
    error_code TEXT, error_text TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id), FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
);
CREATE TABLE model_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, message_processing_id INTEGER NOT NULL,
    attempt_no INTEGER NOT NULL, model_name TEXT NOT NULL, api_key_slot TEXT NOT NULL,
    status TEXT NOT NULL, error_text TEXT, started_at TEXT NOT NULL, completed_at TEXT NOT NULL,
    FOREIGN KEY (message_processing_id) REFERENCES message_processing(id) ON DELETE CASCADE
);
CREATE INDEX idx_ignored_users_lookup ON ignored_users(user_id, source, chat_id);
CREATE INDEX idx_rate_limits_user_ts ON rate_limits(user_id, request_ts);
CREATE INDEX idx_message_processing_chat ON message_processing(chat_id, created_at);
CREATE INDEX idx_message_processing_user ON message_processing(user_id, created_at);
CREATE INDEX idx_model_attempts_processing ON model_attempts(message_processing_id, attempt_no);
INSERT INTO users VALUES (42, 'Legacy fixture', NULL, '2020-01-01', '2020-01-01');
INSERT INTO chats VALUES (42, 'private', NULL, NULL, '2020-01-01', '2020-01-01');
INSERT INTO settings_scopes VALUES ('user', 42, '2020-01-01', '2020-01-01');
INSERT INTO settings VALUES ('user', 42, 'summary_only', 'de & fixture', '2020-01-01', '2020-01-01');
INSERT INTO message_processing (
    id, telegram_message_id, chat_id, user_id, media_type, telegram_file_id, duration_seconds,
    scope_type, scope_id, mode, language, status, created_at, transcription_text, summary_text
) VALUES (1, 1, 42, 42, 'voice', 'fake-legacy-file', 5, 'user', 42, 'both', 'auto',
          'success', '2020-01-01', 'legacy fixture transcript', 'legacy fixture summary');
INSERT INTO model_attempts (
    message_processing_id, attempt_no, model_name, api_key_slot, status, started_at, completed_at
) VALUES (1, 1, 'fixture-model', 'primary', 'success', '2020-01-01', '2020-01-01');
