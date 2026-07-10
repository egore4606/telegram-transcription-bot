# Repository guidance

This repository contains a Python 3.12 Telegram bot, a read-only Flask admin panel,
SQLite persistence, and Docker deployment files.

## Working rules

- Keep changes focused and preserve backward compatibility for existing SQLite data.
- Never commit Telegram tokens, Gemini API keys, user content, database files, or logs.
- Treat Telegram names, usernames, chat titles, captions, and model output as untrusted input.
- Escape user-controlled text before inserting it into Telegram HTML or admin-panel HTML.
- Keep network calls out of unit tests. Mock Telegram and Gemini clients instead.
- Add or update tests for behavior changes.
- Run `python -m pytest -q` before submitting a pull request.
- Run `ruff check --select E9,F63,F7,F82 .` for critical Python errors.

## Review guidelines

- Flag leaked secrets, authorization bypasses, unsafe HTML, prompt-injection regressions,
  unbounded media processing, and destructive database migrations as P1 issues.
- Verify that admin commands remain restricted to `ADMIN_USER_ID` and group moderation
  commands still require group-admin privileges.
- Check concurrency, cancellation, queue limits, Telegram flood control, and retry paths for
  duplicate replies or jobs that can become permanently stuck.
- Check every SQLite schema change for an ordered migration and upgrade coverage from an
  existing database.
- Ensure CI and GitHub Actions use the least permissions needed and do not expose secrets to
  pull requests from forks.
- For documentation-only pull requests, still flag broken commands, unsafe deployment
  instructions, and claims that do not match the code.
