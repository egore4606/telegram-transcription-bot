<p align="center">
  <img src="../assets/readme/hero.png" alt="Telegram Transcription Bot" width="100%">
</p>

<h1 align="center">Telegram Transcription Bot</h1>

<p align="center">
  Перетворює голосові повідомлення та відеокружечки Telegram на читабельні розшифровки,
  стислі підсумки або однорядковий TL;DR за допомогою Google Gemini.
</p>

<p align="center">
  <a href="../README.md">English</a> ·
  <a href="README.ru.md">Русский</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.uk.md">Українська</a>
</p>

> [!IMPORTANT]
> Це self-hosted бот. Для роботи потрібні власний токен Telegram і ключ Gemini. Ніколи не
> публікуйте облікові дані в GitHub.

## Можливості

- Голосові повідомлення та відеокружечки з урахуванням важливого візуального контексту.
- Чотири режими: розшифровка + підсумок, лише розшифровка, лише підсумок і TL;DR.
- Окремі налаштування мови та режиму для приватних чатів і кожної групи.
- Фонова черга з обмеженнями на користувача та чат.
- Таймер, позиція в черзі, кнопки **Зупинити** та **Наступна модель**.
- Основний і резервний ключі Gemini та ланцюжок резервних моделей.
- Безпечне розбиття довгих відповідей Telegram.
- SQLite для налаштувань, статистики, відгуків та історії обробки.
- Невелика read-only адмін-панель через SSH-тунель.
- Контейнери `amd64` і `arm64` у GitHub Container Registry.
- Безкоштовні CI-перевірки, CodeQL і Dependabot.

## Швидкий запуск

```bash
git clone https://github.com/egore4606/telegram-transcription-bot.git
cd telegram-transcription-bot
cp .env.example .env
# Додайте справжні облікові дані до .env
docker compose up -d --build
```

Мінімальний `.env`:

```env
TELEGRAM_TOKEN=ваш_токен_telegram
GEMINI_API_KEY=ваш_ключ_gemini
ADMIN_USER_ID=123456789
```

Запуск готового образу:

```bash
docker pull ghcr.io/egore4606/telegram-transcription-bot:latest
docker compose -f docker-compose.ghcr.yml up -d
```

Усі змінні описані в [довіднику конфігурації](CONFIGURATION.md).

## Основні команди

| Команда | Призначення |
|---|---|
| `/both` | Розшифровка та підсумок |
| `/transcription_only` | Лише розшифровка |
| `/summary_only` | Лише підсумок |
| `/tldr` | Одне речення з головною думкою |
| `/language [код]` | Вибір мови відповіді |
| `/transcription_type [clean\|verbatim]` | Очищений або дослівний текст |
| `/stop` | Скасувати останнє активне або заплановане завдання |
| `/next` | Перейти до наступної моделі Gemini |
| `/feedback [текст]` | Надіслати відгук адміністратору |

## Групи та приватність

Щоб бот отримував усі повідомлення групи, зробіть його адміністратором або вимкніть Privacy Mode
через [@BotFather](https://t.me/BotFather) і додайте бота повторно.

Звичайні текстові повідомлення не архівуються. SQLite містить налаштування й історію тих медіа,
які бот фактично обробив. Докладніше — у [посібнику з експлуатації](OPERATIONS.md).

## Розробка

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
ruff check --select E9,F63,F7,F82 .
```

Перед Pull Request прочитайте [CONTRIBUTING.md](../CONTRIBUTING.md). Вразливості слід повідомляти
приватно відповідно до [SECURITY.md](../SECURITY.md).

Ліцензія: [MIT](../LICENSE).
