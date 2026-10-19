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

Processing history includes accepted media requests and rows rejected by ignore/block policy or
rate limits. Successful rows retain transcription, summary, raw model output, final replies and
request metadata; failed attempts retain bounded credential-redacted error text. This is persistent
user data, not an anonymized metrics database. Normal text chat is not copied wholesale into the
database, but user/chat metadata, command-rate state and pending-feedback state are retained.
Protect database files and backups accordingly. No retention deletion is introduced by this audit.

`/stats`, `/history` and `/last_errors` require the configured administrator's **private chat**;
they refuse group requests before reading global report rows.

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
- later runs resume at the previous successful cursor;
- the state is stored in `./logs/.save-logs-state`;
- `flock` serializes export, append and cursor replacement across invocations;
- the log directory is owner-only and archive/state/lock files are mode `600`;
- archiving is **at least once**, not exactly once: inclusive second-precision boundaries
  may overlap, and a crash after append but before cursor replacement may replay a window;
- a Docker export failure leaves the existing archive and cursor unchanged.

The script requires Bash, GNU `date`, `flock` (util-linux) and Docker Compose. It does not
delete old archives. Permission hardening covers the directory and the current day's archive;
older archives inside that owner-only directory are not rewritten.

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

Direct `python admin_panel.py` execution defaults to `0.0.0.0` for container compatibility.
Outside Compose, explicitly set `ADMIN_PANEL_HOST=127.0.0.1` before starting it. The panel
does not implement authentication; do not expose its listener publicly.

## Reliability boundaries

Graceful PTB shutdown quiesces the in-memory job manager, cancels/drains owned active jobs,
does not launch queued jobs, and attempts terminal database bookkeeping before closing SDK
clients. Abrupt crashes are different: historical `queued`/`started` rows can remain, and
the queue is intentionally not restored/replayed after restart. Recovery needs an explicit
process-ownership policy; this audit does not rewrite old rows.

Retry callbacks enforce the original chat, owner/admin identity, source/clicker ignore policy,
media rate limit (with the existing admin exemption) and bounded in-memory source claims.
Claims prevent overlapping retries of the same media within one process; they are not a
durable cross-process lock. Queue-position edits can still race active-status edits cosmetically.

Final delivery propagates a failed follow-up chunk and does not record success for an incomplete
reply. Native-draft fallback resumes at the first unconfirmed chunk. A send timeout can mean
Telegram accepted the message but the acknowledgement was lost: exactly-once delivery is not
promised. Feedback pending state clears only after all chunks are confirmed, so retrying a
partially delivered feedback can also duplicate its confirmed prefix.

ffmpeg conversion permits only `file,pipe` protocols, drains bounded reads concurrently, caps
16 kHz mono signed-16 decoded output at one hour plus WAV-header allowance, and limits conversion
to 120 seconds. Over-limit output is rejected, never silently transcribed as truncated audio.
Telegram download remains buffered; if size metadata is absent, the post-download limit cannot
prevent all initial buffering. Temporary upload files are unlinked even when remote cleanup
fails/cancels. Remote deletion is best effort with a five-second timeout; an upload that times
out before returning a handle can leave an unidentifiable remote orphan.

Routine application logs exclude transcripts, feedback text, names, chat titles, language
settings, raw Updates and raw exception tracebacks. Operational identifiers and error classes
remain. Newly stored errors redact configured credential strings and are bounded; this is not
general PII scrubbing of arbitrary SDK exception text, nor a cleanup of existing historical data.
Unicode delivery uses conservative UTF-16 budgets including HTML markup/entities. Free-form
language/style settings remain supported; long existing values are escaped and split, not truncated.

Model order and quota policy are unchanged: quota exhaustion tries configured keys and then
aborts, whereas overload/schema failures can move through the existing model chain. No live
Telegram/Gemini API or historical benchmark is validated by offline tests. See
[`AUDIT_OFFLINE_SAFETY.md`](AUDIT_OFFLINE_SAFETY.md) for scope, evidence and deferrals.

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
