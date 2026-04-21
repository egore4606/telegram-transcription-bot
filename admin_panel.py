import html
import os
from datetime import datetime, timezone

from flask import Flask, abort, render_template, request
from waitress import serve

from storage import Storage


DATABASE_PATH = os.environ.get("DATABASE_PATH", "/data/bot.sqlite3")
ADMIN_PANEL_HOST = os.environ.get("ADMIN_PANEL_HOST", "0.0.0.0")
ADMIN_PANEL_PORT = int(os.environ.get("ADMIN_PANEL_PORT", "8081"))
PANEL_DEFAULT_LIMIT = 50
PANEL_MAX_LIMIT = 200
KNOWN_PROCESSING_STATUSES = ("started", "success", "failed", "ignored", "rate_limited")


def clamp_limit(raw_value: str | None, default: int = PANEL_DEFAULT_LIMIT) -> int:
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    if value < 1:
        return default
    return min(value, PANEL_MAX_LIMIT)


def format_timestamp(value: str | None) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def format_processing_ms(value: int | None) -> str:
    if value is None:
        return "-"
    seconds = value / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remaining_seconds = int(seconds % 60)
    return f"{minutes}m {remaining_seconds:02d}s"


def format_user_label(user_id: int | None, full_name: str | None, username: str | None) -> str:
    if user_id is None:
        return "без пользователя"
    if username:
        label = f"@{username}"
    elif full_name:
        label = full_name
    else:
        label = "без имени"
    return f"{label} ({user_id})"


def format_chat_label(chat_id: int | None, chat_type: str | None, title: str | None, chat_username: str | None) -> str:
    if chat_id is None:
        return "без чата"
    if chat_type == "private":
        return f"личка ({chat_id})"
    if chat_username:
        label = f"@{chat_username}"
    elif title:
        label = title
    elif chat_type:
        label = chat_type
    else:
        label = "неизвестный чат"
    return f"{label} ({chat_id})"


def format_status_label(status: str | None) -> str:
    labels = {
        "success": "success",
        "failed": "failed",
        "ignored": "ignored",
        "rate_limited": "rate_limited",
        "started": "started",
    }
    if status is None:
        return "-"
    return labels.get(status, status)


def status_badge_class(status: str | None) -> str:
    classes = {
        "success": "success",
        "failed": "failed",
        "ignored": "ignored",
        "rate_limited": "warning",
        "started": "info",
    }
    return classes.get(status, "info")


def short_error(value: str | None, limit: int = 220) -> str:
    if not value:
        return "-"
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__)
    storage = Storage(db_path or DATABASE_PATH, read_only=True)

    app.jinja_env.filters["format_timestamp"] = format_timestamp
    app.jinja_env.filters["format_processing_ms"] = format_processing_ms
    app.jinja_env.filters["short_error"] = short_error
    app.jinja_env.globals["format_user_label"] = format_user_label
    app.jinja_env.globals["format_chat_label"] = format_chat_label
    app.jinja_env.globals["format_status_label"] = format_status_label
    app.jinja_env.globals["status_badge_class"] = status_badge_class
    app.jinja_env.globals["html_escape"] = html.escape

    @app.route("/")
    def dashboard():
        return render_template(
            "dashboard.html",
            dashboard=storage.get_dashboard_snapshot(),
            recent_processing=storage.get_recent_processing(limit=10),
            recent_errors=storage.get_recent_failed_attempts(limit=10),
        )

    @app.route("/history")
    def history():
        limit = clamp_limit(request.args.get("limit"))
        status = request.args.get("status") or None
        if status not in KNOWN_PROCESSING_STATUSES:
            status = None
        rows = storage.get_recent_processing(limit=limit, status=status)
        return render_template(
            "history.html",
            rows=rows,
            limit=limit,
            status=status,
            statuses=KNOWN_PROCESSING_STATUSES,
        )

    @app.route("/errors")
    def errors():
        limit = clamp_limit(request.args.get("limit"))
        rows = storage.get_recent_failed_attempts(limit=limit)
        return render_template(
            "errors.html",
            rows=rows,
            limit=limit,
        )

    @app.route("/processing/<int:processing_id>")
    def processing_detail(processing_id: int):
        detail = storage.get_processing_detail(processing_id)
        if detail is None:
            abort(404)
        attempts = storage.get_processing_attempts(processing_id)
        return render_template(
            "processing_detail.html",
            detail=detail,
            attempts=attempts,
        )

    return app


app = create_app()


if __name__ == "__main__":
    serve(app, host=ADMIN_PANEL_HOST, port=ADMIN_PANEL_PORT)
