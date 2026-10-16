# Gemini media benchmark — 15–16 октября 2026

**ПРОМЕЖУТОЧНЫЙ ОТЧЁТ — эксперимент продолжается**

Плановое окно UTC: `2026-10-15T15:55:34+00:00` → `2026-10-16T15:55:34+00:00`. 24 часа, каждые 2 часа.
Циклы с записанными строками: **7 / 12**. Строки: **763 / 1308**.
Реальные попытки: **378**; успешные: **205**; пропущенные защитой: **385**.

## Что измеряется

- Три прежних образца: короткое голосовое, длинное голосовое, видеокружок. Файлы и тексты не публикуются.
- JSON Original: текущий промпт бота, исходное медиа, transcription + summary, generateContent, не streaming.
- JSON Audio Control: только аудиодорожка того же кружка, voice prompt; это контроль без визуального контекста.
- File Smart Pipeline: Interactions STT smart + summary через текущую summary-модель. Для кружка исходное видео передаётся на этапе summary.
- Live Production Pipeline: realtime PCM, verbatim по умолчанию + cleanup/summary. Для кружка это экспериментальный маршрут: production бот сейчас направляет кружки в файловый STT.
- Live Smart STT: realtime PCM, SMART без дополнительной summary. Live Burst: отдельный эксперимент без realtime pacing.
- Live Agent Input STT: input transcription голосового агента; manual activityStart/activityEnd, response modality AUDIO, ответ агента не сохраняется и не воспроизводится. Это не готовая замена полного pipeline бота.
- Основной Live передаёт аудио в реальном времени, как нынешний бот. Поэтому полное время длинной записи включает её длительность; не путать с задержкой первого текста.
- First text включает первый interim или final фрагмент и preprocessing. JSON API не streaming: first text для него неизвестно, а не ноль.
- STT и postprocess отмечены отдельно; общая latency включает конвертацию, соединение, upload/cleanup где применимо, inference и постобработку.
- Успех Live требует непустого final input transcript и серверного generationComplete/turnComplete ПОСЛЕ отправки всего аудио. Ранний конец фразы не завершает длинную запись.
- Unary timeout 40 секунд; Live realtime — длительность PCM + 40 секунд; дополнительный postprocess до 40 секунд. max_output_tokens=8192 для общего JSON API.
- Запросы последовательные, между ними 2 секунды; порядок рандомизирован с сохранённым seed. Новые модели в течение опыта не добавляются в фиксированную матрицу.
- При явно модельном 429 оставшиеся запросы к этой модели в цикле пропускаются; при общей/неизвестной квоте прекращается весь цикл. Нулевая квота модели не означает исчерпание квот других моделей. Runner не повторяет неудачные запросы. Лимит 1600 логических inference-вызовов за эксперимент; это не денежный лимит.
- Присутствие в каталоге не означает доступную квоту. Ошибки, timeout, недоступность и пропуски показаны отдельно, исключать их из надёжности нельзя.
- Постобработка: `gemini-3.5-flash`. Боевые файлы, настройки и контейнер не изменяются.

## Ограничение качества / human gold

**Проверенного человеком эталона нет. WER/CER и точность распознавания не измерены.** Валидный JSON, непустой final transcript и отсутствие ошибки — техническая успешность, не доказательство правильности слов или полноты. Не выбирать модель только по этим метрикам.
Три фиксированных примера и 12 повторов не представляют все языки, шум, длины и варианты речи. p90 — nearest-rank по успешным попыткам, при малом n нестабилен.
Результаты августа — историческая база, а не контролируемое A/B: промпт, модели, backend и сеть могли измениться. Latest aliases могут указывать на одинаковые backend версии.

## Задержки по каждому образцу и треку

| Модель | Трек | Образец | Успех/попытки | median, s | p90, s | max, s | first text median, s |
|---|---|---|---:|---:|---:|---:|---:|
| `gemini-2.5-flash` | json_audio_control | video_note | 5/7 | 6.411 | 8.019 | 8.019 | — |
| `gemini-2.5-flash` | json_original | long_voice | 2/2 | 20.860 | 24.531 | 24.531 | — |
| `gemini-2.5-flash` | json_original | short_voice | 3/4 | 4.652 | 4.753 | 4.753 | — |
| `gemini-2.5-flash` | json_original | video_note | 2/3 | 5.354 | 5.832 | 5.832 | — |
| `gemini-2.5-flash-lite` | json_audio_control | video_note | 5/5 | 1.767 | 2.082 | 2.082 | — |
| `gemini-2.5-flash-lite` | json_original | long_voice | 2/2 | 5.746 | 6.503 | 6.503 | — |
| `gemini-2.5-flash-lite` | json_original | short_voice | 3/3 | 1.624 | 1.958 | 1.958 | — |
| `gemini-2.5-flash-lite` | json_original | video_note | 6/6 | 3.844 | 6.614 | 6.614 | — |
| `gemini-2.5-flash-native-audio-latest` | live_agent_input_stt | long_voice | 3/3 | 180.963 | 183.564 | 183.564 | 4.528 |
| `gemini-2.5-flash-native-audio-latest` | live_agent_input_stt | short_voice | 5/5 | 5.844 | 6.170 | 6.170 | 3.075 |
| `gemini-2.5-flash-native-audio-latest` | live_agent_input_stt | video_note | 5/5 | 31.807 | 33.059 | 33.059 | 2.907 |
| `gemini-2.5-flash-native-audio-preview-09-2025` | live_agent_input_stt | long_voice | 3/3 | 190.913 | 198.674 | 198.674 | 4.516 |
| `gemini-2.5-flash-native-audio-preview-09-2025` | live_agent_input_stt | short_voice | 4/4 | 6.157 | 6.612 | 6.612 | 3.397 |
| `gemini-2.5-flash-native-audio-preview-09-2025` | live_agent_input_stt | video_note | 3/3 | 32.381 | 35.802 | 35.802 | 2.911 |
| `gemini-2.5-flash-native-audio-preview-12-2025` | live_agent_input_stt | long_voice | 2/2 | 180.545 | 181.389 | 181.389 | 4.462 |
| `gemini-2.5-flash-native-audio-preview-12-2025` | live_agent_input_stt | short_voice | 6/6 | 6.425 | 7.862 | 7.862 | 3.079 |
| `gemini-2.5-flash-native-audio-preview-12-2025` | live_agent_input_stt | video_note | 4/4 | 32.541 | 33.488 | 33.488 | 3.006 |
| `gemini-2.5-pro` | json_audio_control | video_note | 0/5 | — | — | — | — |
| `gemini-2.5-pro` | json_original | long_voice | 0/4 | — | — | — | — |
| `gemini-2.5-pro` | json_original | short_voice | 0/3 | — | — | — | — |
| `gemini-2.5-pro` | json_original | video_note | 0/6 | — | — | — | — |
| `gemini-3-flash-preview` | json_audio_control | video_note | 2/4 | 8.825 | 14.166 | 14.166 | — |
| `gemini-3-flash-preview` | json_original | long_voice | 2/3 | 7.647 | 8.056 | 8.056 | — |
| `gemini-3-flash-preview` | json_original | short_voice | 3/4 | 3.493 | 13.761 | 13.761 | — |
| `gemini-3-flash-preview` | json_original | video_note | 4/4 | 9.402 | 19.148 | 19.148 | — |
| `gemini-3.1-flash-lite` | json_audio_control | video_note | 4/6 | 2.224 | 3.578 | 3.578 | — |
| `gemini-3.1-flash-lite` | json_original | long_voice | 4/5 | 5.376 | 13.567 | 13.567 | — |
| `gemini-3.1-flash-lite` | json_original | short_voice | 3/4 | 1.508 | 6.884 | 6.884 | — |
| `gemini-3.1-flash-lite` | json_original | video_note | 4/6 | 4.808 | 11.218 | 11.218 | — |
| `gemini-3.1-flash-lite-preview` | json_audio_control | video_note | 3/4 | 2.043 | 10.914 | 10.914 | — |
| `gemini-3.1-flash-lite-preview` | json_original | long_voice | 2/4 | 4.941 | 5.105 | 5.105 | — |
| `gemini-3.1-flash-lite-preview` | json_original | short_voice | 3/4 | 1.718 | 2.226 | 2.226 | — |
| `gemini-3.1-flash-lite-preview` | json_original | video_note | 4/5 | 1.955 | 2.369 | 2.369 | — |
| `gemini-3.1-flash-live-preview` | live_agent_input_stt | long_voice | 4/4 | 181.075 | 181.118 | 181.118 | 180.252 |
| `gemini-3.1-flash-live-preview` | live_agent_input_stt | short_voice | 5/5 | 3.916 | 4.145 | 4.145 | 3.202 |
| `gemini-3.1-flash-live-preview` | live_agent_input_stt | video_note | 5/5 | 30.869 | 31.348 | 31.348 | 29.967 |
| `gemini-3.1-pro-preview` | json_audio_control | video_note | 0/2 | — | — | — | — |
| `gemini-3.1-pro-preview` | json_original | long_voice | 0/3 | — | — | — | — |
| `gemini-3.1-pro-preview` | json_original | video_note | 0/1 | — | — | — | — |
| `gemini-3.1-pro-preview-customtools` | json_audio_control | video_note | 0/3 | — | — | — | — |
| `gemini-3.1-pro-preview-customtools` | json_original | long_voice | 0/1 | — | — | — | — |
| `gemini-3.1-pro-preview-customtools` | json_original | short_voice | 0/1 | — | — | — | — |
| `gemini-3.1-pro-preview-customtools` | json_original | video_note | 0/2 | — | — | — | — |
| `gemini-3.5-flash` | json_audio_control | video_note | 1/1 | 10.131 | 10.131 | 10.131 | — |
| `gemini-3.5-flash` | json_original | long_voice | 0/2 | — | — | — | — |
| `gemini-3.5-flash` | json_original | short_voice | 1/2 | 9.327 | 9.327 | 9.327 | — |
| `gemini-3.5-flash` | json_original | video_note | 2/3 | 5.153 | 5.789 | 5.789 | — |
| `gemini-3.5-flash-lite` | json_audio_control | video_note | 6/6 | 2.110 | 6.804 | 6.804 | — |
| `gemini-3.5-flash-lite` | json_original | long_voice | 4/4 | 4.342 | 7.052 | 7.052 | — |
| `gemini-3.5-flash-lite` | json_original | short_voice | 3/3 | 1.526 | 1.806 | 1.806 | — |
| `gemini-3.5-flash-lite` | json_original | video_note | 5/5 | 2.609 | 6.877 | 6.877 | — |
| `gemini-3.5-transcribe` | file_smart_pipeline | long_voice | 0/3 | — | — | — | — |
| `gemini-3.5-transcribe` | file_smart_pipeline | short_voice | 0/2 | — | — | — | — |
| `gemini-3.5-transcribe` | file_smart_pipeline | video_note | 2/4 | 11.352 | 14.052 | 14.052 | — |
| `gemini-3.5-transcribe` | file_verbatim_stt | long_voice | 2/3 | 8.710 | 9.716 | 9.716 | — |
| `gemini-3.5-transcribe` | file_verbatim_stt | short_voice | 5/5 | 6.342 | 14.869 | 14.869 | — |
| `gemini-3.5-transcribe` | file_verbatim_stt | video_note | 4/5 | 7.527 | 8.002 | 8.002 | — |
| `gemini-3.5-transcribe-live` | live_burst_experimental | long_voice | 0/7 | — | — | — | — |
| `gemini-3.5-transcribe-live` | live_burst_experimental | short_voice | 0/5 | — | — | — | — |
| `gemini-3.5-transcribe-live` | live_burst_experimental | video_note | 4/4 | 1.507 | 1.646 | 1.646 | 1.180 |
| `gemini-3.5-transcribe-live` | live_production_pipeline | long_voice | 1/2 | 186.202 | 186.202 | 186.202 | 3.883 |
| `gemini-3.5-transcribe-live` | live_production_pipeline | short_voice | 0/3 | — | — | — | — |
| `gemini-3.5-transcribe-live` | live_production_pipeline | video_note | 0/4 | — | — | — | — |
| `gemini-3.5-transcribe-live` | live_smart_stt | long_voice | 5/5 | 178.506 | 178.783 | 178.783 | 3.815 |
| `gemini-3.5-transcribe-live` | live_smart_stt | short_voice | 5/5 | 3.198 | 3.278 | 3.278 | 2.340 |
| `gemini-3.5-transcribe-live` | live_smart_stt | video_note | 0/3 | — | — | — | — |
| `gemini-3.6-flash` | json_audio_control | video_note | 2/4 | 4.184 | 4.831 | 4.831 | — |
| `gemini-3.6-flash` | json_original | long_voice | 1/5 | 8.475 | 8.475 | 8.475 | — |
| `gemini-3.6-flash` | json_original | short_voice | 0/2 | — | — | — | — |
| `gemini-3.6-flash` | json_original | video_note | 0/2 | — | — | — | — |
| `gemini-3.7-flash` | json_audio_control | video_note | 0/5 | — | — | — | — |
| `gemini-3.7-flash` | json_original | long_voice | 1/4 | 12.752 | 12.752 | 12.752 | — |
| `gemini-3.7-flash` | json_original | short_voice | 0/3 | — | — | — | — |
| `gemini-3.7-flash` | json_original | video_note | 0/6 | — | — | — | — |
| `gemini-3.8-flash` | json_audio_control | video_note | 1/4 | 5.149 | 5.149 | 5.149 | — |
| `gemini-3.8-flash` | json_original | long_voice | 0/5 | — | — | — | — |
| `gemini-3.8-flash` | json_original | short_voice | 0/4 | — | — | — | — |
| `gemini-3.8-flash` | json_original | video_note | 3/3 | 15.463 | 16.436 | 16.436 | — |
| `gemini-3.8-live` | live_agent_input_stt | long_voice | 3/3 | 180.731 | 181.026 | 181.026 | 180.015 |
| `gemini-3.8-live` | live_agent_input_stt | short_voice | 4/4 | 4.095 | 4.191 | 4.191 | 3.417 |
| `gemini-3.8-live` | live_agent_input_stt | video_note | 4/4 | 30.649 | 31.030 | 31.030 | 30.106 |
| `gemini-3.8-live-extended-thinking` | live_agent_input_stt | long_voice | 0/5 | — | — | — | — |
| `gemini-3.8-live-extended-thinking` | live_agent_input_stt | short_voice | 0/5 | — | — | — | — |
| `gemini-3.8-live-extended-thinking` | live_agent_input_stt | video_note | 0/3 | — | — | — | — |
| `gemini-4-argon` | json_audio_control | video_note | 0/2 | — | — | — | — |
| `gemini-4-argon` | json_original | long_voice | 0/2 | — | — | — | — |
| `gemini-4-argon` | json_original | short_voice | 0/1 | — | — | — | — |
| `gemini-4-argon` | json_original | video_note | 0/1 | — | — | — | — |
| `gemini-flash-latest` | json_audio_control | video_note | 1/2 | 17.315 | 17.315 | 17.315 | — |
| `gemini-flash-latest` | json_original | long_voice | 0/3 | — | — | — | — |
| `gemini-flash-latest` | json_original | short_voice | 0/3 | — | — | — | — |
| `gemini-flash-latest` | json_original | video_note | 2/4 | 5.248 | 5.283 | 5.283 | — |
| `gemini-flash-lite-latest` | json_audio_control | video_note | 5/5 | 1.995 | 5.608 | 5.608 | — |
| `gemini-flash-lite-latest` | json_original | long_voice | 4/4 | 4.785 | 13.136 | 13.136 | — |
| `gemini-flash-lite-latest` | json_original | short_voice | 3/3 | 1.397 | 1.688 | 1.688 | — |
| `gemini-flash-lite-latest` | json_original | video_note | 6/6 | 1.866 | 7.209 | 7.209 | — |
| `gemini-omni-1.1-flash` | json_audio_control | video_note | 0/1 | — | — | — | — |
| `gemini-omni-1.1-flash` | json_original | long_voice | 0/3 | — | — | — | — |
| `gemini-omni-1.1-flash` | json_original | short_voice | 0/3 | — | — | — | — |
| `gemini-omni-flash-preview` | json_audio_control | video_note | 0/1 | — | — | — | — |
| `gemini-omni-flash-preview` | json_original | long_voice | 0/1 | — | — | — | — |
| `gemini-omni-flash-preview` | json_original | short_voice | 0/4 | — | — | — | — |
| `gemini-pro-latest` | json_audio_control | video_note | 0/1 | — | — | — | — |
| `gemini-pro-latest` | json_original | long_voice | 0/2 | — | — | — | — |
| `gemini-pro-latest` | json_original | short_voice | 0/3 | — | — | — | — |
| `gemini-pro-latest` | json_original | video_note | 0/1 | — | — | — | — |

## День и ночь (Europe/Berlin)

| Период | Попытки | Успехи |
|---|---:|---:|
| day 10:00–20:59 | 127 | 68 |
| night 21:00–09:59 | 251 | 137 |

## Ошибки и покрытие

| Статус | Количество |
|---|---:|
| error | 80 |
| quota_global | 7 |
| quota_model_limit | 11 |
| quota_model_zero | 39 |
| skipped_model_quota | 93 |
| skipped_quota | 292 |
| success | 205 |
| timeout | 18 |
| unavailable | 18 |

## Данные и воспроизводимость

- [raw-measurements.csv](raw-measurements.csv): allowlist числовых измерений и технических статусов; ни свободных текстов ошибок, ни ответов модели.
- [summary.json](summary.json): сгруппированные показатели; [day-night-summary.json](day-night-summary.json): аналогичная разбивка по периодам.
- Стоимость: без подтверждённых тарифов для всех текущих моделей и фактического биллинга долларовая сумма не заявляется. Число вызовов ограничено; сырой usage хранится приватно для проверки.
- Не публикуются аудио, видео, расшифровки, summary пользовательского содержания, file URI, ключи и исходные журналы.
- API-адаптеры проверены изолированными unit tests и отдельными реальными smoke-запросами; smoke не входит в эту статистику.
- Источники протокола: [Live Transcribe](https://ai.google.dev/gemini-api/docs/live-api/live-transcribe), [File Transcribe](https://ai.google.dev/gemini-api/docs/transcribe), [Live API](https://ai.google.dev/gemini-api/docs/live-api/capabilities).

## Решение

Выбор победителя до окончания окна не делается. Этот PR будет обновляться тем же runner-ом. Автоматической смены модели нет.
