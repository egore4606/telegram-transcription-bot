# Gemini media benchmark — 15–16 октября 2026

**ПРОМЕЖУТОЧНЫЙ ОТЧЁТ — эксперимент продолжается**

Плановое окно UTC: `2026-10-15T15:55:34+00:00` → `2026-10-16T15:55:34+00:00`. 24 часа, каждые 2 часа.
Циклы с записанными строками: **9 / 12**. Строки: **981 / 1308**.
Реальные попытки: **444**; успешные: **244**; пропущенные защитой: **537**.

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
| `gemini-2.5-flash` | json_audio_control | video_note | 6/8 | 6.704 | 9.775 | 9.775 | — |
| `gemini-2.5-flash` | json_original | long_voice | 2/2 | 20.860 | 24.531 | 24.531 | — |
| `gemini-2.5-flash` | json_original | short_voice | 3/4 | 4.652 | 4.753 | 4.753 | — |
| `gemini-2.5-flash` | json_original | video_note | 2/3 | 5.354 | 5.832 | 5.832 | — |
| `gemini-2.5-flash-lite` | json_audio_control | video_note | 6/6 | 1.784 | 2.082 | 2.082 | — |
| `gemini-2.5-flash-lite` | json_original | long_voice | 3/3 | 5.274 | 6.503 | 6.503 | — |
| `gemini-2.5-flash-lite` | json_original | short_voice | 4/4 | 1.685 | 1.958 | 1.958 | — |
| `gemini-2.5-flash-lite` | json_original | video_note | 7/7 | 4.009 | 6.614 | 6.614 | — |
| `gemini-2.5-flash-native-audio-latest` | live_agent_input_stt | long_voice | 4/4 | 182.260 | 183.564 | 183.564 | 4.595 |
| `gemini-2.5-flash-native-audio-latest` | live_agent_input_stt | short_voice | 6/6 | 5.691 | 6.170 | 6.170 | 3.066 |
| `gemini-2.5-flash-native-audio-latest` | live_agent_input_stt | video_note | 6/6 | 31.688 | 33.059 | 33.059 | 2.885 |
| `gemini-2.5-flash-native-audio-preview-09-2025` | live_agent_input_stt | long_voice | 4/4 | 192.896 | 198.674 | 198.674 | 4.482 |
| `gemini-2.5-flash-native-audio-preview-09-2025` | live_agent_input_stt | short_voice | 4/4 | 6.157 | 6.612 | 6.612 | 3.397 |
| `gemini-2.5-flash-native-audio-preview-09-2025` | live_agent_input_stt | video_note | 4/4 | 34.019 | 35.802 | 35.802 | 2.899 |
| `gemini-2.5-flash-native-audio-preview-12-2025` | live_agent_input_stt | long_voice | 3/3 | 179.900 | 181.389 | 181.389 | 4.490 |
| `gemini-2.5-flash-native-audio-preview-12-2025` | live_agent_input_stt | short_voice | 7/7 | 6.697 | 7.862 | 7.862 | 3.097 |
| `gemini-2.5-flash-native-audio-preview-12-2025` | live_agent_input_stt | video_note | 5/5 | 32.515 | 33.488 | 33.488 | 3.019 |
| `gemini-2.5-pro` | json_audio_control | video_note | 0/6 | — | — | — | — |
| `gemini-2.5-pro` | json_original | long_voice | 0/5 | — | — | — | — |
| `gemini-2.5-pro` | json_original | short_voice | 0/4 | — | — | — | — |
| `gemini-2.5-pro` | json_original | video_note | 0/6 | — | — | — | — |
| `gemini-3-flash-preview` | json_audio_control | video_note | 3/5 | 5.459 | 14.166 | 14.166 | — |
| `gemini-3-flash-preview` | json_original | long_voice | 3/4 | 8.056 | 11.163 | 11.163 | — |
| `gemini-3-flash-preview` | json_original | short_voice | 4/5 | 3.414 | 13.761 | 13.761 | — |
| `gemini-3-flash-preview` | json_original | video_note | 5/5 | 6.270 | 19.148 | 19.148 | — |
| `gemini-3.1-flash-lite` | json_audio_control | video_note | 4/7 | 2.224 | 3.578 | 3.578 | — |
| `gemini-3.1-flash-lite` | json_original | long_voice | 5/6 | 5.694 | 13.567 | 13.567 | — |
| `gemini-3.1-flash-lite` | json_original | short_voice | 3/4 | 1.508 | 6.884 | 6.884 | — |
| `gemini-3.1-flash-lite` | json_original | video_note | 4/6 | 4.808 | 11.218 | 11.218 | — |
| `gemini-3.1-flash-lite-preview` | json_audio_control | video_note | 3/5 | 2.043 | 10.914 | 10.914 | — |
| `gemini-3.1-flash-lite-preview` | json_original | long_voice | 3/5 | 5.082 | 5.105 | 5.105 | — |
| `gemini-3.1-flash-lite-preview` | json_original | short_voice | 3/4 | 1.718 | 2.226 | 2.226 | — |
| `gemini-3.1-flash-lite-preview` | json_original | video_note | 4/6 | 1.955 | 2.369 | 2.369 | — |
| `gemini-3.1-flash-live-preview` | live_agent_input_stt | long_voice | 5/5 | 181.105 | 181.828 | 181.828 | 180.282 |
| `gemini-3.1-flash-live-preview` | live_agent_input_stt | short_voice | 5/5 | 3.916 | 4.145 | 4.145 | 3.202 |
| `gemini-3.1-flash-live-preview` | live_agent_input_stt | video_note | 5/5 | 30.869 | 31.348 | 31.348 | 29.967 |
| `gemini-3.1-pro-preview` | json_audio_control | video_note | 0/2 | — | — | — | — |
| `gemini-3.1-pro-preview` | json_original | long_voice | 0/3 | — | — | — | — |
| `gemini-3.1-pro-preview` | json_original | short_voice | 0/1 | — | — | — | — |
| `gemini-3.1-pro-preview` | json_original | video_note | 0/1 | — | — | — | — |
| `gemini-3.1-pro-preview-customtools` | json_audio_control | video_note | 0/3 | — | — | — | — |
| `gemini-3.1-pro-preview-customtools` | json_original | long_voice | 0/1 | — | — | — | — |
| `gemini-3.1-pro-preview-customtools` | json_original | short_voice | 0/2 | — | — | — | — |
| `gemini-3.1-pro-preview-customtools` | json_original | video_note | 0/2 | — | — | — | — |
| `gemini-3.5-flash` | json_audio_control | video_note | 2/2 | 6.872 | 10.131 | 10.131 | — |
| `gemini-3.5-flash` | json_original | long_voice | 1/3 | 10.926 | 10.926 | 10.926 | — |
| `gemini-3.5-flash` | json_original | short_voice | 2/3 | 6.140 | 9.327 | 9.327 | — |
| `gemini-3.5-flash` | json_original | video_note | 3/4 | 5.420 | 5.789 | 5.789 | — |
| `gemini-3.5-flash-lite` | json_audio_control | video_note | 7/7 | 2.161 | 6.804 | 6.804 | — |
| `gemini-3.5-flash-lite` | json_original | long_voice | 4/5 | 4.342 | 7.052 | 7.052 | — |
| `gemini-3.5-flash-lite` | json_original | short_voice | 4/4 | 1.666 | 1.956 | 1.956 | — |
| `gemini-3.5-flash-lite` | json_original | video_note | 5/5 | 2.609 | 6.877 | 6.877 | — |
| `gemini-3.5-transcribe` | file_smart_pipeline | long_voice | 0/3 | — | — | — | — |
| `gemini-3.5-transcribe` | file_smart_pipeline | short_voice | 1/3 | 9.363 | 9.363 | 9.363 | — |
| `gemini-3.5-transcribe` | file_smart_pipeline | video_note | 3/5 | 9.415 | 14.052 | 14.052 | — |
| `gemini-3.5-transcribe` | file_verbatim_stt | long_voice | 3/4 | 8.220 | 9.716 | 9.716 | — |
| `gemini-3.5-transcribe` | file_verbatim_stt | short_voice | 6/6 | 7.040 | 14.869 | 14.869 | — |
| `gemini-3.5-transcribe` | file_verbatim_stt | video_note | 5/6 | 7.380 | 8.002 | 8.002 | — |
| `gemini-3.5-transcribe-live` | live_burst_experimental | long_voice | 0/9 | — | — | — | — |
| `gemini-3.5-transcribe-live` | live_burst_experimental | short_voice | 0/6 | — | — | — | — |
| `gemini-3.5-transcribe-live` | live_burst_experimental | video_note | 5/5 | 1.523 | 1.646 | 1.646 | 1.201 |
| `gemini-3.5-transcribe-live` | live_production_pipeline | long_voice | 1/3 | 186.202 | 186.202 | 186.202 | 3.883 |
| `gemini-3.5-transcribe-live` | live_production_pipeline | short_voice | 0/3 | — | — | — | — |
| `gemini-3.5-transcribe-live` | live_production_pipeline | video_note | 0/5 | — | — | — | — |
| `gemini-3.5-transcribe-live` | live_smart_stt | long_voice | 5/5 | 178.506 | 178.783 | 178.783 | 3.815 |
| `gemini-3.5-transcribe-live` | live_smart_stt | short_voice | 5/5 | 3.198 | 3.278 | 3.278 | 2.340 |
| `gemini-3.5-transcribe-live` | live_smart_stt | video_note | 0/3 | — | — | — | — |
| `gemini-3.6-flash` | json_audio_control | video_note | 2/4 | 4.184 | 4.831 | 4.831 | — |
| `gemini-3.6-flash` | json_original | long_voice | 1/6 | 8.475 | 8.475 | 8.475 | — |
| `gemini-3.6-flash` | json_original | short_voice | 0/2 | — | — | — | — |
| `gemini-3.6-flash` | json_original | video_note | 1/3 | 4.198 | 4.198 | 4.198 | — |
| `gemini-3.7-flash` | json_audio_control | video_note | 0/5 | — | — | — | — |
| `gemini-3.7-flash` | json_original | long_voice | 1/4 | 12.752 | 12.752 | 12.752 | — |
| `gemini-3.7-flash` | json_original | short_voice | 1/4 | 5.913 | 5.913 | 5.913 | — |
| `gemini-3.7-flash` | json_original | video_note | 0/7 | — | — | — | — |
| `gemini-3.8-flash` | json_audio_control | video_note | 1/5 | 5.149 | 5.149 | 5.149 | — |
| `gemini-3.8-flash` | json_original | long_voice | 1/6 | 13.164 | 13.164 | 13.164 | — |
| `gemini-3.8-flash` | json_original | short_voice | 0/5 | — | — | — | — |
| `gemini-3.8-flash` | json_original | video_note | 3/4 | 15.463 | 16.436 | 16.436 | — |
| `gemini-3.8-live` | live_agent_input_stt | long_voice | 4/4 | 180.815 | 181.026 | 181.026 | 180.077 |
| `gemini-3.8-live` | live_agent_input_stt | short_voice | 4/4 | 4.095 | 4.191 | 4.191 | 3.417 |
| `gemini-3.8-live` | live_agent_input_stt | video_note | 5/5 | 30.722 | 31.030 | 31.030 | 30.076 |
| `gemini-3.8-live-extended-thinking` | live_agent_input_stt | long_voice | 0/6 | — | — | — | — |
| `gemini-3.8-live-extended-thinking` | live_agent_input_stt | short_voice | 0/6 | — | — | — | — |
| `gemini-3.8-live-extended-thinking` | live_agent_input_stt | video_note | 0/4 | — | — | — | — |
| `gemini-4-argon` | json_audio_control | video_note | 0/2 | — | — | — | — |
| `gemini-4-argon` | json_original | long_voice | 0/3 | — | — | — | — |
| `gemini-4-argon` | json_original | short_voice | 0/1 | — | — | — | — |
| `gemini-4-argon` | json_original | video_note | 0/1 | — | — | — | — |
| `gemini-flash-latest` | json_audio_control | video_note | 1/2 | 17.315 | 17.315 | 17.315 | — |
| `gemini-flash-latest` | json_original | long_voice | 0/3 | — | — | — | — |
| `gemini-flash-latest` | json_original | short_voice | 0/3 | — | — | — | — |
| `gemini-flash-latest` | json_original | video_note | 2/5 | 5.248 | 5.283 | 5.283 | — |
| `gemini-flash-lite-latest` | json_audio_control | video_note | 5/5 | 1.995 | 5.608 | 5.608 | — |
| `gemini-flash-lite-latest` | json_original | long_voice | 5/5 | 5.677 | 13.136 | 13.136 | — |
| `gemini-flash-lite-latest` | json_original | short_voice | 3/3 | 1.397 | 1.688 | 1.688 | — |
| `gemini-flash-lite-latest` | json_original | video_note | 7/7 | 1.974 | 7.209 | 7.209 | — |
| `gemini-omni-1.1-flash` | json_audio_control | video_note | 0/2 | — | — | — | — |
| `gemini-omni-1.1-flash` | json_original | long_voice | 0/3 | — | — | — | — |
| `gemini-omni-1.1-flash` | json_original | short_voice | 0/3 | — | — | — | — |
| `gemini-omni-flash-preview` | json_audio_control | video_note | 0/1 | — | — | — | — |
| `gemini-omni-flash-preview` | json_original | long_voice | 0/1 | — | — | — | — |
| `gemini-omni-flash-preview` | json_original | short_voice | 0/4 | — | — | — | — |
| `gemini-omni-flash-preview` | json_original | video_note | 0/1 | — | — | — | — |
| `gemini-pro-latest` | json_audio_control | video_note | 0/2 | — | — | — | — |
| `gemini-pro-latest` | json_original | long_voice | 0/2 | — | — | — | — |
| `gemini-pro-latest` | json_original | short_voice | 0/3 | — | — | — | — |
| `gemini-pro-latest` | json_original | video_note | 0/1 | — | — | — | — |

## День и ночь (Europe/Berlin)

| Период | Попытки | Успехи |
|---|---:|---:|
| day 10:00–20:59 | 182 | 100 |
| night 21:00–09:59 | 262 | 144 |

## Ошибки и покрытие

| Статус | Количество |
|---|---:|
| error | 94 |
| quota_global | 9 |
| quota_model_limit | 11 |
| quota_model_zero | 45 |
| skipped_model_quota | 104 |
| skipped_quota | 433 |
| success | 244 |
| timeout | 20 |
| unavailable | 21 |

## Данные и воспроизводимость

- [raw-measurements.csv](raw-measurements.csv): allowlist числовых измерений и технических статусов; ни свободных текстов ошибок, ни ответов модели.
- [summary.json](summary.json): сгруппированные показатели; [day-night-summary.json](day-night-summary.json): аналогичная разбивка по периодам.
- Стоимость: без подтверждённых тарифов для всех текущих моделей и фактического биллинга долларовая сумма не заявляется. Число вызовов ограничено; сырой usage хранится приватно для проверки.
- Не публикуются аудио, видео, расшифровки, summary пользовательского содержания, file URI, ключи и исходные журналы.
- API-адаптеры проверены изолированными unit tests и отдельными реальными smoke-запросами; smoke не входит в эту статистику.
- Источники протокола: [Live Transcribe](https://ai.google.dev/gemini-api/docs/live-api/live-transcribe), [File Transcribe](https://ai.google.dev/gemini-api/docs/transcribe), [Live API](https://ai.google.dev/gemini-api/docs/live-api/capabilities).

## Решение

Выбор победителя до окончания окна не делается. Этот PR будет обновляться тем же runner-ом. Автоматической смены модели нет.
