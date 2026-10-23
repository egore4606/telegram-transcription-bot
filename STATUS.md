# Bot feature release — 2026-10-23

Baseline: `3b634e7` in production; development branch `feat/fast-live-onboarding-context`.

## Authorized scope
- Rank complete-result models by measured benchmark speed; independent Live preview with cancellation.
- Plain default / opt-in technical UI; guided `/start` and editable settings.
- Opt-in in-memory conversation context: 300-second retention, <=120-second media linkage, per chat/topic, no forwarded-message linkage, conservative prompt relevance.
- Publish to GitHub and deploy after verification. Write changelog; **do not broadcast it**.

## State
- Baseline runtime confirmed running, no restarts; production untouched during development.
- Implementation integrated in the isolated feature worktree. Full offline suite: **442 passed**, 12 existing PTB deprecation warnings; critical Ruff and diff whitespace checks passed. Credential-pattern scan found no matches.
- Setup is owner/message/topic bound; schema 6 preserves existing settings. Context is rechecked before each model/key request, including postprocessing, with off/clear/expiry regression tests.
- Context default OFF; group changes require a group administrator. Existing settings/data must remain intact.

## Remaining verification
- Independent security/correctness review, container execution of the suite, and GitHub CI.
- PR/merge, backup, Docker rollout, runtime revision and Telegram connection checks.

No live transcription acceptance or new deployment has yet occurred for this feature release.
