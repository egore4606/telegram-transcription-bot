# Gemini media latency benchmark — 2026-08-13/14

## Why this benchmark was run

The bot's primary Gemini model and fallback order should optimize real Telegram media handling, not only nominal model capability. This benchmark measured the same three representative inputs repeatedly across both quiet and busy hours, using the bot's production prompt shape and structured JSON response schema.

This document contains aggregate timing and availability data only. It intentionally excludes API keys, raw media, transcripts, Telegram metadata, and other user data.

## Method

- Window: 2026-08-13 14:00 through 2026-08-14 20:00 Europe/Berlin.
- Cadence: one cycle every two hours.
- Completed cycles: 16.
- Measurements: 765.
- Inputs per model and cycle:
  - short OGG voice message: 2.52 seconds;
  - long OGG voice message: 175.30 seconds;
  - MP4 Telegram video note: 29.06 seconds.
- Request timeout: 40 seconds, matching the bot default.
- Prompt: the current `build_prompt()` output in `both`, `auto`, and `clean` mode.
- Output contract: the current `transcription` + `summary` JSON schema.
- Discovery: every general-purpose Gemini model advertised for `generateContent` was rediscovered at the start of each cycle. Purpose-specific image, TTS, embedding, robotics, computer-use, and bidirectional Live models were excluded because they are not comparable drop-in transcription endpoints.
- Ordering: model/input jobs were shuffled per cycle and executed serially to avoid creating artificial concurrent load.
- Success: a request completed within 40 seconds and returned valid structured JSON. Transcription accuracy was not scored, so latency is not a substitute for a future quality benchmark.

## Overall results

The ranking below prioritizes successful-request rate, then median latency among successful requests.

| Model | Success | Median | Short voice | Long voice | Video note |
|---|---:|---:|---:|---:|---:|
| `gemini-3.1-flash-lite-preview` | 47/48 | 4.361 s | 2.730 s | 5.749 s | 3.761 s |
| `gemini-3.5-flash-lite` | 47/48 | 4.893 s | 4.878 s | 15.519 s | 1.542 s |
| `gemini-3.1-flash-lite` | 47/48 | 5.315 s | 3.515 s | 7.259 s | 5.178 s |
| `gemini-flash-lite-latest` | 45/48 | 4.564 s | 4.383 s | 15.635 s | 1.501 s |
| `gemini-3-flash-preview` | 36/48 | 5.934 s | 3.173 s | 7.871 s | 6.095 s |
| `gemini-2.5-flash-lite` | 34/48 | 4.265 s | 1.564 s | 6.028 s | 4.286 s |
| `gemini-2.5-flash` | 31/48 | 7.565 s | 3.538 s | 18.049 s | 7.565 s |
| `gemini-3.6-flash` | 31/48 | 9.036 s | 6.966 s | 22.040 s | 3.993 s |
| `gemini-3.5-flash` | 23/48 | 5.128 s | 2.362 s | 20.899 s | 5.128 s |
| `gemini-flash-latest` | 23/48 | 6.818 s | 4.886 s | 17.254 s | 5.028 s |
| `gemini-3.7-flash` | 15/39 | 4.809 s | 3.698 s | 18.692 s | 3.955 s |

The following advertised endpoints produced no successful comparable response in this run: `gemini-3.1-pro-preview-customtools`, `gemini-3.1-pro-preview`, `gemini-pro-latest`, `gemini-2.5-pro`, and `gemini-omni-flash-preview`. Failures were quota, availability, or endpoint-lifecycle errors; their short error latency must not be interpreted as model speed.

`gemini-3.7-flash-video-understanding-eap` appeared late in model discovery and produced only 1/6 successes, which is insufficient for a recommendation.

## Busy-hours comparison

Busy hours are defined as 10:00–20:59 Europe/Berlin. Quiet hours are 21:00–09:59.

| Model | Busy success | Busy median | Quiet success | Quiet median |
|---|---:|---:|---:|---:|
| `gemini-3.1-flash-lite-preview` | 29/30 | 4.430 s | 18/18 | 4.240 s |
| `gemini-3.5-flash-lite` | 29/30 | 4.864 s | 18/18 | 5.030 s |
| `gemini-3.1-flash-lite` | 29/30 | 5.040 s | 18/18 | 6.258 s |
| `gemini-2.5-flash-lite` | 27/30 | 4.360 s | 7/18 | 3.622 s |
| `gemini-flash-lite-latest` | 27/30 | 4.732 s | 18/18 | 4.383 s |
| `gemini-3.6-flash` | 25/30 | 7.861 s | 6/18 | 17.790 s |
| `gemini-2.5-flash` | 24/30 | 8.905 s | 7/18 | 6.317 s |
| `gemini-3-flash-preview` | 23/30 | 7.473 s | 13/18 | 4.747 s |
| `gemini-3.5-flash` | 16/30 | 5.737 s | 7/18 | 4.198 s |
| `gemini-flash-latest` | 13/30 | 7.187 s | 10/18 | 4.761 s |
| `gemini-3.7-flash` | 6/21 | 10.665 s | 9/18 | 4.532 s |

The extra daytime cycles changed the recommendation materially: larger Flash models degraded in success rate and/or latency under load, while the Flash-Lite family remained reliable.

## Recommended default chain

Proposed order:

1. `gemini-3.1-flash-lite` — stable (non-Preview), 29/30 busy-hour success, and substantially faster than 3.5 Flash-Lite on long voice messages.
2. `gemini-3.5-flash-lite` — equally strong busy-hour success and the fastest reliable video-note path, but slower on long audio.
3. `gemini-3.1-flash-lite-preview` — best measured latency/reliability combination, retained as a fallback because Preview endpoints can change or disappear without stable-version guarantees.
4. `gemini-2.5-flash-lite` — lower busy-hour reliability but fast and stable-version fallback on another generation.
5. `gemini-3-flash-preview` — final broader Flash fallback; less reliable under busy-hour load than the Flash-Lite candidates.

The code change affects defaults only. Existing deployments that explicitly set `GEMINI_MODEL` keep their configured primary model. This pull request does not edit a real `.env`, restart a container, merge itself, or deploy anything.

## Follow-up

- Add a human-reviewed reference transcript and word/error scoring before treating latency as a complete quality ranking.
- Re-run the benchmark after Google changes Preview availability or introduces a stable successor.
- Monitor production model-attempt history after deployment and roll back the configured `GEMINI_MODEL` if error rates regress.
