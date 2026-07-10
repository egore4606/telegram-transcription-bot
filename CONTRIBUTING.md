# Contributing

Thanks for helping improve Telegram Transcription Bot. Small, focused pull requests are the
easiest to review and merge.

## Before you start

1. Search existing issues and pull requests.
2. For a larger feature, open a feature request before investing significant work.
3. Never include real Telegram tokens, Gemini keys, logs, voice messages, or production
   databases in an issue or pull request.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

Tests do not require live Telegram or Gemini credentials:

```bash
python -m pytest -q
ruff check --select E9,F63,F7,F82 .
```

You can also validate the production image locally:

```bash
docker build -t telegram-transcription-bot:dev .
```

## Pull requests

- Create a branch from `main`.
- Explain what changed and why.
- Add tests for new behavior or bug fixes.
- Update documentation when configuration or commands change.
- Keep unrelated formatting or refactoring out of the same pull request.
- Confirm that no sensitive data is present in the diff.

By contributing, you agree that your contribution is licensed under the repository's MIT
license.
