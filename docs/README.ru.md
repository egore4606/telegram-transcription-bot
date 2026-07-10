<p align="center">
  <img src="../assets/readme/hero.png" alt="Telegram Transcription Bot" width="100%">
</p>

<h1 align="center">Telegram Transcription Bot</h1>

<p align="center">
  Превращает голосовые сообщения и видеокружки Telegram в читаемую расшифровку,
  краткое резюме или однострочный TL;DR с помощью Google Gemini.
</p>

<p align="center">
  <a href="../README.md">English</a> ·
  <a href="README.ru.md">Русский</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.uk.md">Українська</a>
</p>

<p align="center">
  <a href="https://github.com/egore4606/telegram-transcription-bot/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/egore4606/telegram-transcription-bot/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/egore4606/telegram-transcription-bot/actions/workflows/codeql.yml"><img alt="CodeQL" src="https://github.com/egore4606/telegram-transcription-bot/actions/workflows/codeql.yml/badge.svg"></a>
  <a href="../LICENSE"><img alt="MIT" src="https://img.shields.io/github/license/egore4606/telegram-transcription-bot"></a>
</p>

> [!IMPORTANT]
> Бот устанавливается на ваш сервер. Для работы нужны собственный токен Telegram и ключ Gemini.
> Никогда не публикуйте их в GitHub.

## Возможности

- Голосовые сообщения и видеокружки с учётом важной визуальной части.
- Четыре режима: расшифровка + резюме, только расшифровка, только резюме и TL;DR.
- Отдельные настройки языка и режима для личных чатов и каждой группы.
- Очередь фоновых задач с лимитами на пользователя и чат.
- Таймер обработки, позиция в очереди, кнопки **Остановить** и **Следующая модель**.
- Основной и резервный ключи Gemini, а также цепочка резервных моделей.
- Безопасное разбиение длинных ответов Telegram.
- SQLite для настроек, статистики, обратной связи и истории обработки.
- Небольшая read-only админ-панель через SSH-туннель.
- Docker-образы для `amd64` и `arm64` в GitHub Container Registry.
- Бесплатные проверки GitHub Actions: тесты, сборка контейнера, CodeQL и Dependabot.

## Быстрый запуск

```bash
git clone https://github.com/egore4606/telegram-transcription-bot.git
cd telegram-transcription-bot
cp .env.example .env
# Впишите реальные токены в .env
docker compose up -d --build
```

Минимальный `.env`:

```env
TELEGRAM_TOKEN=ваш_токен_от_BotFather
GEMINI_API_KEY=ваш_ключ_Gemini
ADMIN_USER_ID=123456789
```

Готовый образ без локальной сборки:

```bash
docker pull ghcr.io/egore4606/telegram-transcription-bot:latest
docker compose -f docker-compose.ghcr.yml up -d
```

Полный список переменных находится в [справочнике конфигурации](CONFIGURATION.md).

## Основные команды

| Команда | Назначение |
|---|---|
| `/both` | Расшифровка и резюме — режим по умолчанию |
| `/transcription_only` | Только расшифровка |
| `/summary_only` | Только резюме |
| `/tldr` | Одна фраза с главной мыслью |
| `/language [код]` | Язык ответа: `auto`, `ru`, `en`, `de` и другие |
| `/transcription_type [clean\|verbatim]` | Читаемый или дословный текст |
| `/stop` | Остановить последнюю активную или ожидающую задачу |
| `/next` | Переключить задачу на следующую модель Gemini |
| `/feedback [текст]` | Отправить сообщение администратору |
| `/myid` | Узнать свой Telegram ID |

Команды администратора: `/stats`, `/history`, `/last_errors`, `/block`, `/unblock` и
`/broadcast_changelog`.

## Группы и приватность

Чтобы бот видел голосовые сообщения группы, назначьте его администратором либо отключите Privacy
Mode через [@BotFather](https://t.me/BotFather) и добавьте бота заново.

Обычный текст чата не архивируется. В SQLite сохраняются настройки и история тех медиафайлов,
которые бот действительно обработал. Подробнее — в [руководстве по эксплуатации](OPERATIONS.md).

## Разработка

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
ruff check --select E9,F63,F7,F82 .
```

Перед Pull Request прочитайте [CONTRIBUTING.md](../CONTRIBUTING.md). Уязвимости нельзя публиковать
в Issues — используйте порядок из [SECURITY.md](../SECURITY.md).

Проект распространяется по лицензии [MIT](../LICENSE).
