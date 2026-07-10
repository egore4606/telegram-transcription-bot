<p align="center">
  <img src="../assets/readme/hero.png" alt="Telegram Transcription Bot" width="100%">
</p>

<h1 align="center">Telegram Transcription Bot</h1>

<p align="center">
  Wandelt Telegram-Sprachnachrichten und Videonachrichten mit Google Gemini in lesbare
  Transkripte, Zusammenfassungen oder einen einzeiligen TL;DR um.
</p>

<p align="center">
  <a href="../README.md">English</a> ·
  <a href="README.ru.md">Русский</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.uk.md">Українська</a>
</p>

> [!IMPORTANT]
> Dies ist ein selbst gehosteter Bot. Du benötigst einen eigenen Telegram-Bot-Token und einen
> Gemini-API-Schlüssel. Zugangsdaten dürfen niemals in GitHub eingecheckt werden.

## Funktionen

- Sprachnachrichten und Videonachrichten mit relevantem visuellem Kontext.
- Vier Ausgabemodi: Transkript + Zusammenfassung, nur Transkript, nur Zusammenfassung, TL;DR.
- Eigene Sprache und Einstellungen für private Chats und jede Gruppe.
- Hintergrundwarteschlange mit Limits pro Benutzer und Chat.
- Fortschrittsanzeige, Warteschlangenposition sowie **Stop**- und **Nächstes Modell**-Aktionen.
- Primärer und optionaler zweiter Gemini-Schlüssel mit Modell-Fallbacks.
- Sichere Aufteilung langer Telegram-Antworten.
- SQLite für Einstellungen, Statistiken, Feedback und Verarbeitungshistorie.
- Schreibgeschütztes Admin-Panel über einen SSH-Tunnel.
- Multi-Arch-Container für `amd64` und `arm64` in GitHub Container Registry.
- Kostenlose CI-Prüfungen, CodeQL-Analyse und Dependabot-Updates.

## Schnellstart

```bash
git clone https://github.com/egore4606/telegram-transcription-bot.git
cd telegram-transcription-bot
cp .env.example .env
# Echte Zugangsdaten in .env eintragen
docker compose up -d --build
```

Minimale Konfiguration:

```env
TELEGRAM_TOKEN=dein_telegram_bot_token
GEMINI_API_KEY=dein_gemini_api_schluessel
ADMIN_USER_ID=123456789
```

Vorgefertigtes Image verwenden:

```bash
docker pull ghcr.io/egore4606/telegram-transcription-bot:latest
docker compose -f docker-compose.ghcr.yml up -d
```

Alle Variablen und Standardwerte stehen in der [Konfigurationsreferenz](CONFIGURATION.md).

## Wichtige Befehle

| Befehl | Zweck |
|---|---|
| `/both` | Transkript und Zusammenfassung |
| `/transcription_only` | Nur Transkript |
| `/summary_only` | Nur Zusammenfassung |
| `/tldr` | Ein Satz mit der Kernaussage |
| `/language [Code]` | Ausgabesprache auswählen |
| `/transcription_type [clean\|verbatim]` | Bereinigtes oder wortgetreues Transkript |
| `/stop` | Letzten aktiven oder wartenden Auftrag abbrechen |
| `/next` | Zum nächsten Gemini-Modell wechseln |
| `/feedback [Text]` | Feedback an den Administrator senden |

## Gruppen und Datenschutz

Damit der Bot alle Gruppennachrichten empfangen kann, mache ihn zum Gruppenadministrator oder
deaktiviere den Privacy Mode über [@BotFather](https://t.me/BotFather) und füge ihn erneut hinzu.

Normale Textnachrichten werden nicht archiviert. SQLite enthält Einstellungen und die Historie der
tatsächlich verarbeiteten Medien. Weitere Hinweise stehen im [Betriebshandbuch](OPERATIONS.md).

## Entwicklung

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
ruff check --select E9,F63,F7,F82 .
```

Bitte lies vor einem Pull Request [CONTRIBUTING.md](../CONTRIBUTING.md). Sicherheitslücken werden
privat nach [SECURITY.md](../SECURITY.md) gemeldet.

Lizenz: [MIT](../LICENSE).
