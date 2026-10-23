# Full-result speed order and independent Live preview

## Selection policy

The default main chain is ranked by **complete successful `json_original`
latency**, not first-text latency, STT-only time, `json_audio_control`, or Live
pipeline time. Source: [15–16 October 2026 benchmark](benchmarks/2026-10-15/README.md),
[raw measurements](benchmarks/2026-10-15/raw-measurements.csv), and
[grouped summary](benchmarks/2026-10-15/summary.json).

Eligibility deliberately retains the existing five general-purpose main-chain
models (the previous primary plus its four fallbacks). Every selected model has
at least one successful `json_original` result **for each of the three sample
types**. Models with zero successful results for a type cannot be ranked for
that type. This does not expand the production universe merely because a new
alias/model returned valid JSON on one unlabelled sample; other successful JSON
models are outside this conservative allowlist, not claimed slower or unsafe.
Dedicated file STT and all Live tracks are not comparable full JSON calls and
are excluded from automatic main ranking.

Within this eligibility universe, speed alone determines order. There is no
hidden reliability weighting. Errors and quota-skipped rows are not latency
samples, but their impact must not be mistaken for measured reliability. The
benchmark has only three fixed recordings and no human-verified gold transcript;
technical success is not evidence of transcription correctness. In particular,
the fastest video model below succeeded only 4/8 actual attempts.

## Measured medians

Seconds below retain the raw CSV's millisecond precision (a midpoint median can
therefore have four decimal places). Counts are successful/actual attempts;
`skipped_*` rows do not count as attempted calls. Values were calculated with
Python `statistics.median`, not copied from the rounded README table.

| Main model | Short voice ≤30s median (success/attempt) | Long voice >30s median (success/attempt) | Video median (success/attempt) |
|---|---:|---:|---:|
| `gemini-2.5-flash-lite` | 1.624 (5/5) | 5.3345 (4/6) | 3.897 (10/10) |
| `gemini-3.1-flash-lite-preview` | 1.718 (3/7) | 4.9295 (4/8) | 1.9545 (4/8) |
| `gemini-3.5-flash-lite` | 1.881 (6/6) | 5.881 (6/8) | 4.8555 (8/8) |
| `gemini-3-flash-preview` | 3.453 (6/7) | 7.6475 (4/5) | 6.270 (7/7) |
| `gemini-3.1-flash-lite` | 4.196 (4/7) | 5.694 (5/9) | 3.969 (5/9) |

Resulting full-result chains:

- **Short voice, ≤30 seconds:** `gemini-2.5-flash-lite` →
  `gemini-3.1-flash-lite-preview` → `gemini-3.5-flash-lite` →
  `gemini-3-flash-preview` → `gemini-3.1-flash-lite`.
- **Long voice, >30 seconds:** `gemini-3.1-flash-lite-preview` →
  `gemini-2.5-flash-lite` → `gemini-3.1-flash-lite` →
  `gemini-3.5-flash-lite` → `gemini-3-flash-preview`.
- **Video:** `gemini-3.1-flash-lite-preview` → `gemini-2.5-flash-lite` →
  `gemini-3.1-flash-lite` → `gemini-3.5-flash-lite` →
  `gemini-3-flash-preview`.

The 30-second dispatch boundary is an operational policy; the benchmark has one
short and one long recording, not evidence of a latency crossover at exactly 30s.
Unknown duration defaults to the short-voice order. Video always uses video order.

Reproduce the medians from the repository root (offline):

```python
import csv
from collections import defaultdict
from statistics import median

models = {
    "gemini-2.5-flash-lite", "gemini-3.1-flash-lite-preview",
    "gemini-3.5-flash-lite", "gemini-3-flash-preview", "gemini-3.1-flash-lite",
}
groups = defaultdict(list)
with open("docs/benchmarks/2026-10-15/raw-measurements.csv") as source:
    for row in csv.DictReader(source):
        if (row["track"] == "json_original" and row["status"] == "success"
                and row["model"] in models):
            groups[row["input"], row["model"]].append(float(row["latency_seconds"]))
for sample in ("short_voice", "long_voice", "video_note"):
    for model in sorted(models, key=lambda m: median(groups[sample, m])):
        print(sample, model, len(groups[sample, model]), median(groups[sample, model]))
```

`tests/test_parallel_live.py` independently recomputes medians/order from the CSV
and checks the checked-in constants and the short/long boundary.

## Configuration and failure handling

- Default `MODEL_ORDER=benchmark` applies these orders even if an old deployment
  still exports `GEMINI_MODEL`. The only opt-out is explicit `MODEL_ORDER=manual`:
  then `GEMINI_MODEL` heads the existing deduplicated fallback list.
- A manual `gemini-3.5-transcribe-live` primary maps to file
  `gemini-3.5-transcribe` for **both voice and video**, so the main chain never
  duplicates the independent Live preview. File STT postprocessing remains intact.
- Overload/capacity, timeout, invalid structured output, and model unavailability
  automatically advance the main chain (respecting configured attempt limits).
- True quota errors first try the existing backup-key path, then abort instead
  of walking models and amplifying exhausted quota. Quota takes precedence over
  generic “try again later” wording. Explicit model-overload 429s without quota
  wording are capacity failures, not account-quota fallback.
- Other errors, such as malformed media or authorization failures, are not
  blanket-retried. Provider errors are not inferred from preview failure.

## Independent preview lifecycle

For an observed Telegram `MediaJob` with downloaded bytes and duration ≤600s,
one independent `gemini-3.5-transcribe-live` preview starts alongside the main
request. It uses the existing paced PCM Live protocol and primary key. It never
runs for `IntegrationJob`/`SilentProgress`, and never contributes main attempt
counts, final output, or model selection. `/next` and main fallback do not
restart/cancel the preview; `/stop` still applies to both.

The Live progress proxy forwards only live transcript/mode updates and discards
Live's main-status text. Main first/fallback model status updates remain owned
by the main worker. Final main success, error, stop, or parent cancellation
closes the preview write gate, disables native draft keepalives synchronously,
and cancels/drains the preview before returning. No final main result waits for
the remaining audio duration. Websocket close has a one-second close timeout;
preview draining has a two-second cancellation deadline. Cleanup itself is
shielded from repeated parent cancellation so sender/receiver/conversion tasks
are not abandoned. A preview failure/completion never substitutes its text for
the main result and does not retry with another key or open another preview.

No dependencies or production configuration were changed. All lifecycle tests
mock provider/network operations; real Gemini availability and word accuracy
are not verified by this change.
