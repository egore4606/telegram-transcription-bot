# Operations and releases

## Data stored by the bot

The SQLite database contains:

- private-chat and per-group settings;
- transcript-style and language settings;
- ignore and block state;
- rate-limit windows and statistics;
- processed voice/video request history;
- Gemini model attempts and errors;
- pending feedback state;
- changelog delivery records.

Only media that the bot processes is archived in processing history. Normal text chat is not
copied into the database, apart from operational state required for features such as feedback.

## Database migrations

`storage.py` applies ordered migrations during startup. `schema_version` records the latest applied
version. When adding a schema change:

1. Add an idempotent migration block or migration function.
2. Append it to the ordered migration map with the next integer version.
3. Increment `LATEST_SCHEMA_VERSION`.
4. Add tests that upgrade an older database and tests for a new empty database.

Back up the Docker volume before deploying a schema change:

```bash
docker compose stop bot admin_panel
docker run --rm -v telegram-transcription-bot_bot_data:/data -v "$PWD:/backup" alpine \
  tar czf /backup/bot-data-backup.tgz -C /data .
docker compose start bot admin_panel
```

Adjust the volume name if your Compose project uses a different prefix.

## Logs

Follow current logs:

```bash
docker compose logs -f bot
```

`save-logs.sh` exports incremental Docker logs to `./logs/`:

- the first run exports the last 24 hours;
- later runs export only lines after the previous successful run;
- the state is stored in `./logs/.save-logs-state`;
- repeated runs on the same day do not duplicate older lines.

```bash
./save-logs.sh
```

Log files can contain usernames, chat titles, identifiers, and error context. Do not attach raw
production logs to public GitHub issues.

## Admin panel

The panel opens SQLite in read-only mode and has no write actions. The provided Compose file binds
it to localhost only.

```bash
ssh -L 8081:127.0.0.1:8081 user@your-server
```

Open `http://127.0.0.1:8081` after the tunnel is established. Do not change the host port binding to
`0.0.0.0` unless a separate authenticated reverse proxy protects it.

## Updating a GHCR deployment

```bash
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
docker compose -f docker-compose.ghcr.yml logs --tail=100 bot
```

For a reproducible deployment, replace `latest` in `docker-compose.ghcr.yml` with a release version
or immutable `sha-<commit>` tag.

## Public changelog broadcast

The Telegram broadcast is manual by design:

1. Update `PUBLIC_CHANGELOG_TEXT` in `bot.py`.
2. Increment `PUBLIC_CHANGELOG_VERSION`.
3. Deploy and verify the bot.
4. Run `/broadcast_changelog` from the administrator account.

The database prevents the same changelog version from being sent twice to the same private-chat
user.

## Creating a GitHub release

1. Merge a reviewed pull request into `main`.
2. Confirm that CI, CodeQL, dependency review, and the container build are green.
3. Update `CHANGELOG.md` when the release deserves a curated summary.
4. Create and push a semantic version tag:

```bash
git checkout main
git pull --ff-only
git tag -a v1.0.0 -m "v1.0.0"
git push origin v1.0.0
```

The `Release` workflow generates GitHub release notes. The container workflow publishes `1.0.0`,
`1.0`, the original tag, and an immutable SHA tag to GHCR.

## Deployment environments

Publishing an image records a GitHub deployment to the `container-registry` environment. A real
`production` environment should be added only after the server deployment is automated and the
required SSH or platform secrets are stored in GitHub environment secrets.
