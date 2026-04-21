import os


os.environ.setdefault("TELEGRAM_TOKEN", "test-telegram-token")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
os.environ.setdefault("DATABASE_PATH", "/tmp/telegrambot-test.sqlite3")
os.environ.setdefault("ADMIN_USER_ID", "123456789")
