# Offline reliability and safety audit

## Scope and evidence boundaries

Baseline: `b32e35974fd9e1b5be575e1d2ebd9126df356513`. This audit preserves the current
SQLite schema (version 5), model ordering and dependency constraints. It is a source/test
change, not a deployment or a live-service certification. No Telegram/Gemini service calls,
production data, recordings, credentials or runtime logs were used for regression tests.
GitHub CI builds the image without publishing; a local image build was deliberately skipped
to avoid resource contention. No release, merge or deployment is part of the audit.

The initial review phase recorded static inspection of all 53 baseline text files and visual
inspection of the sole decorative image. The continuation rechecked the full implementation
diff, surrounding lifecycle/auth/delivery/storage paths, the offline regressions, and relevant
operations/CI configuration. The per-file checklist below separates inherited static coverage
from executable evidence; it is not a claim that every possible behavior is covered.

## Fixed defects and regression mapping

Numbers refer to the original mandatory findings, letters to the additional audit findings.
Test names below omit parameter suffixes for readability.

| Finding / root cause | Focused change | Regression evidence |
| --- | --- | --- |
| 1. Progress Telegram failures escaped into model work | Catch only Telegram errors; retain unrendered state, flood backoff, and programming-error propagation | `test_progress_telegram_errors_are_retryable_best_effort`, `test_progress_programming_errors_propagate`, `test_fallback_survives_failed_progress_edit` |
| 2. Parent cancellation left a model request running | Always cancel/drain request and control watchers | `test_request_and_watchers_are_drained` (outer/stop/next/timeout/success/error, Events and task ownership assertions) |
| 3. SQLite connection context did not close | Transactional context manager with unconditional close, including setup failure | `test_storage_closes_success_and_rollback`, `test_storage_setup_error_closes_connection`, `test_storage_readonly_rejects_writes` |
| 4. RetryAfter truncated fractions and mishandled timedelta | `total_seconds` support, ceiling, minimum one second, fractional text fallback | `test_retry_after_rounds_up` with PTB opt-in, `test_retry_after_string_fraction` |
| 5. Retry bypassed policy/chat/quota and admitted duplicates | Original chat, failed source/media validation, owner/admin, source and clicker policy, rate limits, bounded per-media claims retained until terminal work | `test_retry_rejects_invalid_policy_before_enqueue`, `test_retry_owner_admin_and_concurrent_click_claim`, rejection/error recovery and terminal release tests |
| 6. Follow-up delivery failure was swallowed | Propagate missing-chunk failures before success/statistics bookkeeping | `test_followup_delivery_failure_propagates`, `test_job_lifecycle_always_releases_and_drains[delivery]` with actual fake-message APIs and recorded storage calls |
| 7. Native-draft fallback repeated confirmed chunks and used a missing original target | Fall back from the first failed chunk only; use processing message when original is absent; cleanup best effort | Native prefix, retry target, flood retry and fallback-failure tests in `test_audit_core.py` |
| 8. Stored language was inserted as HTML | Escape and safely split both read and confirmation, preserving free-form/legacy values | `test_language_set_and_legacy_read_are_escaped_bounded` |
| 9. Global admin reports could disclose cross-chat metadata in a group | Identity plus private-chat gate before global report reads; help/docs updated | `test_global_reports_are_private_and_admin_only` |
| 10. Initial DB errors and secondary cleanup errors bypassed capacity release | Protect full lifecycle; drain progress and always finish; best-effort terminal bookkeeping; preserve outer cancellation | `test_job_lifecycle_always_releases_and_drains`, `test_initial_db_failure_promotes_next_queued_job`, `test_background_task_errors_are_consumed` |
| 11. Live TaskGroup hid service/control exception identity | Explicitly owned sender/receiver tasks, cancel/drain sibling, preserve controls/503 classification, redact configured keys | `test_live_errors_preserve_identity_and_drain_siblings` for both sender and receiver |
| A. Stale numeric callback ID could operate a new job | Bind control to exact accessible processing message and original chat, including admin actions | `test_job_controls_bind_exact_processing_message` |
| B. ffmpeg could expand/output/run without local bounds | Concurrent bounded stdout/stderr reads, decoded cap, wall timeout, kill/reap, unconditional temp cleanup; network protocols disabled | `test_conversion_is_bounded_and_always_cleans`, protocol whitelist test, synthetic local OGG/MP4 smoke tests |
| C. Remote cleanup cancellation skipped local unlink | Nested unconditional local cleanup and bounded best-effort remote deletion | `test_file_upload_local_cleanup_survives_remote_cleanup` |
| D. Routine logging exposed content and errors could contain credentials | Remove raw Updates/content/names/language/tracebacks from routine logs; type/code logging and bounded configured-credential redaction before error persistence | `test_success_feedback_and_unhandled_logs_exclude_content`, feedback logging and SDK redaction tests |
| E. Python character length underestimated emoji/HTML payloads | Conservative UTF-16 budgets including markup, whole-codepoint splitting before escaping, feedback/language splitting, bounded Live drafts/previews | Unicode/chunk/whitespace tests, long-feedback/metadata and language tests; balanced-HTML/content reconstruction tests |
| F. Schema accepted nonstrings and missing required mode output | Reject bool/list/dict/number/null fields; explicit required mode at normal and dedicated postprocess request boundaries | Nonstring/mode tests in `test_audit_core.py`, `test_dedicated_postprocess_requires_selected_fields`; existing compatibility tests retained |
| G. Shutdown did not own background jobs | Quiesce admission, cancel/drain owned active jobs, stop queued promotion, terminal bookkeeping before SDK close via PTB lifecycle | `test_manager_shutdown_owns_active_queued_jobs_and_stops_before_clients`, `test_shutdown_drains_even_with_failed_bookkeeping_and_finish` |
| H. Log exporter races and misleading exactly-once claim | Whole-operation `flock`, owner-only directory/files, document inclusive cursor overlap and crash replay | Copied script with fake Docker/date: failure unchanged, serialization/boundary reuse, permission tests |
| I. Absent/anonymous senders caused command exceptions/policy misuse | Guard human command/feedback dispatch and group-admin checks; reject channel/anonymous ignore targets | Missing-message/user, bot and anonymous cases, guard dispatch and ignore-target tests |

Additional continuation checks cover cancellation before/after retry admission and ownership of
its claim, shutdown bookkeeping/finish failure, balanced HTML and reconstruction of complete
section text. Self-review added a regression for a secondary Live-cleanup `CancelledError`
masking an originating service failure: both sender/receiver cases failed before the focused
fix and passed afterward. Actual parent-task cancellation is still propagated.

## Reproducible offline checks

Use an isolated Python 3.12 development environment with the repository requirements installed.
`tests/conftest.py` replaces inherited service values before bot imports, uses temporary SQLite,
and forbids socket connections during tests. All Telegram/SDK/websocket clients are mocked.
Optional ffmpeg tests generate a short sine wave locally, never use an existing recording.
Shell tests copy the script into a temporary fixture directory and intercept Docker/date.
Do not execute the real exporter against a production Compose project as a test.

Commands run successfully at the Sol pre-review checkpoint:

```bash
python -m pytest -q
ruff check --select E9,F63,F7,F82 .
python -m compileall -q bot.py storage.py admin_panel.py tests
bash -n save-logs.sh
git diff --check
```

Pre-review result: **256 passed**, 12 PTB deprecation warnings (numeric RetryAfter compatibility),
no skips on the local validation environment. Interpreter Python 3.12.13; installed packages:
python-telegram-bot 22.8, google-genai 2.31.0, websockets 16.1.1, Flask 3.1.3, waitress 3.0.2,
pytest 9.1.1 and ruff 0.17.1. These record one tested environment, not new dependency pins.
The original 67-test baseline also had a saved passing run.

RED evidence was rerun using a separate `git archive` of the exact baseline SHA, copying only
the current hardened test harness and six regression files/legacy fixture into that isolated
source tree. Running the five `test_audit_{core,media,lifecycle,privacy,storage_panel}.py` files
and `test_save_logs.py` there produced **137 failed, 44 passed, 0 collection/setup errors**
(181 tests). Failures include each numbered/lettered behavioral fix above; existing safe behavior
such as read-only panel escaping and the frozen legacy upgrade also passes on the baseline.
This distinguishes weak previous migration coverage from an invented migration defect.

Private raw evidence is intentionally not committed: it can contain machine metadata and
verbose fixture payloads. The public evidence here is test names, exact source SHA, commands
and aggregate outcomes. The finalization-only ownership/HTML tests strengthen GREEN coverage;
they are not counted as independent RED proof against the old API. CI and independent review
must be checked on the PR's actual head; this document does not pre-claim those outcomes.

## Compatibility, classifications and explicit deferrals

- No schema bump/destructive migration. A frozen v1 SQL fixture lacks `transcription_type` and
  preserves real fixture settings/history/attempts through v1→v5 and repeated initialization.
  SQL values remain parameterized and dynamic column/table names originate from fixed internal
  callers; no SQL-injection finding is asserted here.
- Schema compatibility remains: single-object array, case-insensitive Transcript aliases,
  fences/trailing-brace repair, and empty unused output. Required fields depend explicitly on
  the selected mode; invalid output takes the existing schema-fallback path.
- Private-only global reports are an intentional restriction. Group moderation still requires
  a usable human group administrator; admin identity and rate-limit exemption are preserved.
- Retry claims are bounded and in-memory, not durable/cross-process. They release on rejection,
  pre-admission exception/cancellation, queued cancellation and terminal completion; admitted
  work retains ownership even if the callback itself is cancelled afterward.
- Queue-position refresh still uses a snapshot and may overwrite an active-status edit while
  a network edit is in flight. This cosmetic stale-position race is explicitly deferred, not
  presented as fixed by a pre-await state check.
- Abrupt-crash `queued`/`started` historical rows are not replayed or bulk-rewritten. Graceful
  shutdown is covered; crash recovery needs a separate persisted ownership policy.
- Delivery resumes after a confirmed prefix, but timeout ambiguity precludes exactly-once sends.
  Partially delivered feedback stays pending; a whole-feedback retry can repeat its prefix.
- Decoded ffmpeg output is limited to one hour of 16 kHz mono signed-16 plus header allowance,
  conversion wall time is 120 seconds and diagnostic memory is bounded. This is not constant
  memory streaming of the entire pipeline; downloads/output are still buffered. Missing
  Telegram size metadata cannot prevent all initial download buffering.
- Remote deletion is bounded/best effort. Upload timeout before a returned remote handle can
  leave an orphan that cannot be identified safely. Local temporary cleanup is guaranteed on
  the exercised normal failure/cancellation paths, not in a hard process crash.
- Logs are not a full anonymization system: operational IDs and error classifications remain;
  configured-credential redaction is not general PII detection in arbitrary exceptions. SQLite
  intentionally retains transcripts/raw output/replies and ignored/rate-limited metadata.
  Existing historical rows/logs are not scrubbed or deleted.
- Jinja autoescape remains enabled, with no stored-content `safe` override; panel XSS/read-only
  regressions pass. The panel intentionally has no authentication. Compose binds the host port
  to localhost; direct Python execution must use `ADMIN_PANEL_HOST=127.0.0.1` outside containers.
- Quota exhaustion tries configured keys, then aborts; overload/schema fallback follows the
  existing model chain. No model-order changes or dependency-PR changes are included.
- Mutable action/dependency ranges are maintenance risk, not a reason for a sweeping upgrade.
  Privileged label/size workflows do not check out untrusted PR code; permissions are unchanged.
- Export is at least once: lock prevents concurrent cursor races, but inclusive second boundaries
  and append-before-state crashes can duplicate data. No retention deletion was added.
- Repository benchmark claims remain historical assertions, not remeasured by this audit.
  Mock tests cannot establish live Telegram draft support or Gemini model availability.

## Baseline per-file coverage checklist

Legend: P = complete static review recorded by the initial review phase (image: visual);
S = continuation inspected changed code or relevant surrounding/config paths;
T = exercised by offline tests; C = validated by syntax/compile or CI configuration inspection.
P-only files were not re-audited line-by-line in the continuation. No live-service evidence is
inferred from any marker. New audit/test files are listed separately after the baseline table.

| Baseline file | Coverage / disposition |
| --- | --- |
| `.dockerignore` | P,S — excludes credentials/data/logs/tests from build context |
| `.env.example` | P — placeholder documentation only, unchanged |
| `.gitattributes` | P — text normalization, unchanged |
| `.github/CODEOWNERS` | P — ownership, unchanged |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | P — issue intake, unchanged |
| `.github/ISSUE_TEMPLATE/config.yml` | P — issue config, unchanged |
| `.github/ISSUE_TEMPLATE/feature_request.yml` | P — feature intake, unchanged |
| `.github/dependabot.yml` | P — dependency policy, unchanged |
| `.github/labeler.yml` | P — labeling paths, unchanged |
| `.github/labels.json` | P — label definitions, unchanged |
| `.github/pull_request_template.md` | P — contributor guidance, unchanged |
| `.github/release.yml` | P — release notes, unchanged |
| `.github/workflows/ci.yml` | P,S,C — Python offline gates and nonpublishing container build |
| `.github/workflows/codeql.yml` | P — static analysis, unchanged |
| `.github/workflows/dependency-review.yml` | P — dependency gate, unchanged |
| `.github/workflows/labeler.yml` | P — no untrusted PR checkout, unchanged |
| `.github/workflows/pr-size.yml` | P — metadata-only, unchanged |
| `.github/workflows/publish-container.yml` | P,S — main/tag publish after quality gate, not invoked by this branch |
| `.github/workflows/release.yml` | P — release permissions, unchanged |
| `.github/workflows/sync-labels.yml` | P — label administration, unchanged |
| `.gitignore` | P — generated/private files exclusion, unchanged |
| `AGENTS.md` | P,S — audit/testing/privacy rules followed |
| `CHANGELOG.md` | P — historical statements unchanged |
| `CODE_OF_CONDUCT.md` | P — governance, unchanged |
| `CONTRIBUTING.md` | P — contribution instructions, unchanged |
| `Dockerfile` | P — existing image, local build skipped; PR CI build required |
| `LICENSE` | P — license, unchanged |
| `README.md` | P — public usage/benchmark claims not independently rerun |
| `SECURITY.md` | P — reporting policy, unchanged |
| `SUPPORT.md` | P — support guidance, unchanged |
| `admin_panel.py` | P,S,T,C — read-only routes and escaped templates, no server started |
| `assets/readme/hero.png` | P — decorative image, no executable behavior |
| `bot.py` | P,S,T,C — lifecycle, auth, fallback, media, formatting, privacy fixes |
| `docker-compose.ghcr.yml` | P — deployment descriptor unchanged, not executed |
| `docker-compose.yml` | P,S — localhost host-port binding, not executed |
| `docs/CONFIGURATION.md` | P — config contract unchanged |
| `docs/GEMINI_LOAD_BENCHMARK_2026-08-14.md` | P — historical benchmark, not rerun |
| `docs/OPERATIONS.md` | P,S — privacy, private reports, log/archive and reliability limits corrected |
| `docs/README.de.md` | P — translated usage, unchanged |
| `docs/README.ru.md` | P — translated usage, unchanged |
| `docs/README.uk.md` | P — translated usage, unchanged |
| `requirements-dev.txt` | P,S — test tooling, no range changes |
| `requirements.txt` | P,S — dependencies, no upgrades |
| `save-logs.sh` | P,S,T,C — lock/permissions; copied fake-Docker tests only |
| `storage.py` | P,S,T,C — all connection usages use context manager; schema unchanged |
| `templates/base.html` | P,T — Flask test-client routes/autoescape |
| `templates/dashboard.html` | P,T — XSS/read-only route checks |
| `templates/errors.html` | P,T — XSS/read-only route checks |
| `templates/history.html` | P,T — XSS/read-only route checks |
| `templates/processing_detail.html` | P,T — XSS/read-only route checks |
| `tests/conftest.py` | P,S,T,C — fake environment, temporary DB and socket guard |
| `tests/test_admin_panel.py` | P,T,C — existing panel compatibility suite |
| `tests/test_bot_helpers.py` | P,S,T,C — existing compatibility tests; fake sender-chat field explicit |
| `tests/test_storage.py` | P,T,C — existing storage compatibility suite |

New files reviewed/exercised in this continuation: `tests/test_audit_core.py`,
`tests/test_audit_lifecycle.py`, `tests/test_audit_media.py`, `tests/test_audit_privacy.py`,
`tests/test_audit_storage_panel.py`, `tests/test_audit_finalization.py`, `tests/test_save_logs.py`,
`tests/fixtures/schema-v1.sql`, and this audit document. Raw private reports, launcher prompts,
venvs, databases, logs and test XML are deliberately outside the public changeset.
