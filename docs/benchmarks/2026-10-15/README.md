# Gemini media benchmark — 15–16 октября 2026

**ПРОМЕЖУТОЧНЫЙ ОТЧЁТ — эксперимент продолжается**

Плановое окно UTC: `2026-10-15T15:55:34+00:00` → `2026-10-16T15:55:34+00:00`. 24 часа, каждые 2 часа.
Циклы с записанными строками: **12 / 12**. Строки: **1308 / 1308**.
Реальные попытки: **660**; успешные: **357**; пропущенные защитой: **648**.

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
| `gemini-2.5-flash` | json_audio_control | video_note | 7/10 | 6.411 | 9.775 | 9.775 | — |
| `gemini-2.5-flash` | json_original | long_voice | 4/4 | 25.540 | 28.223 | 28.223 | — |
| `gemini-2.5-flash` | json_original | short_voice | 5/6 | 3.679 | 4.753 | 4.753 | — |
| `gemini-2.5-flash` | json_original | video_note | 5/6 | 5.834 | 6.850 | 6.850 | — |
| `gemini-2.5-flash-lite` | json_audio_control | video_note | 9/9 | 1.860 | 2.263 | 2.263 | — |
| `gemini-2.5-flash-lite` | json_original | long_voice | 4/6 | 5.335 | 6.503 | 6.503 | — |
| `gemini-2.5-flash-lite` | json_original | short_voice | 5/5 | 1.624 | 1.958 | 1.958 | — |
| `gemini-2.5-flash-lite` | json_original | video_note | 10/10 | 3.897 | 5.193 | 6.614 | — |
| `gemini-2.5-flash-native-audio-latest` | live_agent_input_stt | long_voice | 6/6 | 183.561 | 184.613 | 184.613 | 4.621 |
| `gemini-2.5-flash-native-audio-latest` | live_agent_input_stt | short_voice | 9/9 | 5.844 | 7.484 | 7.484 | 3.131 |
| `gemini-2.5-flash-native-audio-latest` | live_agent_input_stt | video_note | 9/9 | 31.807 | 34.217 | 34.217 | 2.977 |
| `gemini-2.5-flash-native-audio-preview-09-2025` | live_agent_input_stt | long_voice | 7/7 | 190.913 | 198.674 | 198.674 | 4.526 |
| `gemini-2.5-flash-native-audio-preview-09-2025` | live_agent_input_stt | short_voice | 6/6 | 5.963 | 6.612 | 6.612 | 3.390 |
| `gemini-2.5-flash-native-audio-preview-09-2025` | live_agent_input_stt | video_note | 7/7 | 32.381 | 35.802 | 35.802 | 2.911 |
| `gemini-2.5-flash-native-audio-preview-12-2025` | live_agent_input_stt | long_voice | 6/6 | 181.294 | 192.846 | 192.846 | 4.622 |
| `gemini-2.5-flash-native-audio-preview-12-2025` | live_agent_input_stt | short_voice | 10/10 | 6.425 | 7.862 | 9.441 | 3.106 |
| `gemini-2.5-flash-native-audio-preview-12-2025` | live_agent_input_stt | video_note | 7/7 | 32.515 | 34.226 | 34.226 | 3.033 |
| `gemini-2.5-pro` | json_audio_control | video_note | 0/8 | — | — | — | — |
| `gemini-2.5-pro` | json_original | long_voice | 0/7 | — | — | — | — |
| `gemini-2.5-pro` | json_original | short_voice | 0/5 | — | — | — | — |
| `gemini-2.5-pro` | json_original | video_note | 0/9 | — | — | — | — |
| `gemini-3-flash-preview` | json_audio_control | video_note | 6/8 | 5.529 | 14.166 | 14.166 | — |
| `gemini-3-flash-preview` | json_original | long_voice | 4/5 | 7.647 | 11.163 | 11.163 | — |
| `gemini-3-flash-preview` | json_original | short_voice | 6/7 | 3.453 | 13.761 | 13.761 | — |
| `gemini-3-flash-preview` | json_original | video_note | 7/7 | 6.270 | 19.148 | 19.148 | — |
| `gemini-3.1-flash-lite` | json_audio_control | video_note | 5/10 | 2.469 | 17.418 | 17.418 | — |
| `gemini-3.1-flash-lite` | json_original | long_voice | 5/9 | 5.694 | 13.567 | 13.567 | — |
| `gemini-3.1-flash-lite` | json_original | short_voice | 4/7 | 4.196 | 17.339 | 17.339 | — |
| `gemini-3.1-flash-lite` | json_original | video_note | 5/9 | 3.969 | 11.218 | 11.218 | — |
| `gemini-3.1-flash-lite-preview` | json_audio_control | video_note | 4/8 | 6.479 | 17.076 | 17.076 | — |
| `gemini-3.1-flash-lite-preview` | json_original | long_voice | 4/8 | 4.929 | 5.105 | 5.105 | — |
| `gemini-3.1-flash-lite-preview` | json_original | short_voice | 3/7 | 1.718 | 2.226 | 2.226 | — |
| `gemini-3.1-flash-lite-preview` | json_original | video_note | 4/8 | 1.955 | 2.369 | 2.369 | — |
| `gemini-3.1-flash-live-preview` | live_agent_input_stt | long_voice | 8/8 | 181.111 | 181.828 | 181.828 | 180.326 |
| `gemini-3.1-flash-live-preview` | live_agent_input_stt | short_voice | 7/7 | 3.939 | 4.738 | 4.738 | 3.175 |
| `gemini-3.1-flash-live-preview` | live_agent_input_stt | video_note | 8/8 | 30.888 | 31.348 | 31.348 | 29.953 |
| `gemini-3.1-pro-preview` | json_audio_control | video_note | 0/2 | — | — | — | — |
| `gemini-3.1-pro-preview` | json_original | long_voice | 0/3 | — | — | — | — |
| `gemini-3.1-pro-preview` | json_original | short_voice | 0/2 | — | — | — | — |
| `gemini-3.1-pro-preview` | json_original | video_note | 0/3 | — | — | — | — |
| `gemini-3.1-pro-preview-customtools` | json_audio_control | video_note | 0/4 | — | — | — | — |
| `gemini-3.1-pro-preview-customtools` | json_original | long_voice | 0/2 | — | — | — | — |
| `gemini-3.1-pro-preview-customtools` | json_original | short_voice | 0/2 | — | — | — | — |
| `gemini-3.1-pro-preview-customtools` | json_original | video_note | 0/3 | — | — | — | — |
| `gemini-3.5-flash` | json_audio_control | video_note | 3/3 | 4.349 | 10.131 | 10.131 | — |
| `gemini-3.5-flash` | json_original | long_voice | 1/5 | 10.926 | 10.926 | 10.926 | — |
| `gemini-3.5-flash` | json_original | short_voice | 3/4 | 2.953 | 9.327 | 9.327 | — |
| `gemini-3.5-flash` | json_original | video_note | 3/5 | 5.420 | 5.789 | 5.789 | — |
| `gemini-3.5-flash-lite` | json_audio_control | video_note | 9/10 | 3.606 | 6.804 | 6.804 | — |
| `gemini-3.5-flash-lite` | json_original | long_voice | 6/8 | 5.881 | 13.678 | 13.678 | — |
| `gemini-3.5-flash-lite` | json_original | short_voice | 6/6 | 1.881 | 7.734 | 7.734 | — |
| `gemini-3.5-flash-lite` | json_original | video_note | 8/8 | 4.856 | 9.853 | 9.853 | — |
| `gemini-3.5-transcribe` | file_smart_pipeline | long_voice | 1/4 | 15.592 | 15.592 | 15.592 | — |
| `gemini-3.5-transcribe` | file_smart_pipeline | short_voice | 1/5 | 9.363 | 9.363 | 9.363 | — |
| `gemini-3.5-transcribe` | file_smart_pipeline | video_note | 5/7 | 11.195 | 18.727 | 18.727 | — |
| `gemini-3.5-transcribe` | file_verbatim_stt | long_voice | 5/6 | 9.716 | 12.434 | 12.434 | — |
| `gemini-3.5-transcribe` | file_verbatim_stt | short_voice | 8/8 | 6.464 | 14.869 | 14.869 | — |
| `gemini-3.5-transcribe` | file_verbatim_stt | video_note | 8/9 | 7.039 | 8.002 | 8.002 | — |
| `gemini-3.5-transcribe-live` | live_burst_experimental | long_voice | 0/12 | — | — | — | — |
| `gemini-3.5-transcribe-live` | live_burst_experimental | short_voice | 0/9 | — | — | — | — |
| `gemini-3.5-transcribe-live` | live_burst_experimental | video_note | 8/8 | 1.563 | 1.950 | 1.950 | 1.236 |
| `gemini-3.5-transcribe-live` | live_production_pipeline | long_voice | 1/3 | 186.202 | 186.202 | 186.202 | 3.883 |
| `gemini-3.5-transcribe-live` | live_production_pipeline | short_voice | 0/5 | — | — | — | — |
| `gemini-3.5-transcribe-live` | live_production_pipeline | video_note | 0/5 | — | — | — | — |
| `gemini-3.5-transcribe-live` | live_smart_stt | long_voice | 6/6 | 178.459 | 178.783 | 178.783 | 3.784 |
| `gemini-3.5-transcribe-live` | live_smart_stt | short_voice | 8/8 | 3.216 | 3.278 | 3.278 | 2.330 |
| `gemini-3.5-transcribe-live` | live_smart_stt | video_note | 0/6 | — | — | — | — |
| `gemini-3.6-flash` | json_audio_control | video_note | 3/7 | 3.628 | 4.831 | 4.831 | — |
| `gemini-3.6-flash` | json_original | long_voice | 1/7 | 8.475 | 8.475 | 8.475 | — |
| `gemini-3.6-flash` | json_original | short_voice | 2/4 | 11.867 | 21.162 | 21.162 | — |
| `gemini-3.6-flash` | json_original | video_note | 2/4 | 3.845 | 4.198 | 4.198 | — |
| `gemini-3.7-flash` | json_audio_control | video_note | 2/8 | 8.406 | 11.097 | 11.097 | — |
| `gemini-3.7-flash` | json_original | long_voice | 1/5 | 12.752 | 12.752 | 12.752 | — |
| `gemini-3.7-flash` | json_original | short_voice | 1/6 | 5.913 | 5.913 | 5.913 | — |
| `gemini-3.7-flash` | json_original | video_note | 0/9 | — | — | — | — |
| `gemini-3.8-flash` | json_audio_control | video_note | 1/8 | 5.149 | 5.149 | 5.149 | — |
| `gemini-3.8-flash` | json_original | long_voice | 1/8 | 13.164 | 13.164 | 13.164 | — |
| `gemini-3.8-flash` | json_original | short_voice | 1/8 | 4.228 | 4.228 | 4.228 | — |
| `gemini-3.8-flash` | json_original | video_note | 4/6 | 10.977 | 16.436 | 16.436 | — |
| `gemini-3.8-live` | live_agent_input_stt | long_voice | 6/6 | 180.851 | 181.026 | 181.026 | 180.180 |
| `gemini-3.8-live` | live_agent_input_stt | short_voice | 7/7 | 3.954 | 4.191 | 4.191 | 3.311 |
| `gemini-3.8-live` | live_agent_input_stt | video_note | 8/8 | 30.819 | 31.030 | 31.030 | 30.184 |
| `gemini-3.8-live-extended-thinking` | live_agent_input_stt | long_voice | 0/9 | — | — | — | — |
| `gemini-3.8-live-extended-thinking` | live_agent_input_stt | short_voice | 0/8 | — | — | — | — |
| `gemini-3.8-live-extended-thinking` | live_agent_input_stt | video_note | 0/7 | — | — | — | — |
| `gemini-4-argon` | json_audio_control | video_note | 0/3 | — | — | — | — |
| `gemini-4-argon` | json_original | long_voice | 0/4 | — | — | — | — |
| `gemini-4-argon` | json_original | short_voice | 0/1 | — | — | — | — |
| `gemini-4-argon` | json_original | video_note | 0/2 | — | — | — | — |
| `gemini-flash-latest` | json_audio_control | video_note | 2/4 | 13.207 | 17.315 | 17.315 | — |
| `gemini-flash-latest` | json_original | long_voice | 1/5 | 13.114 | 13.114 | 13.114 | — |
| `gemini-flash-latest` | json_original | short_voice | 0/6 | — | — | — | — |
| `gemini-flash-latest` | json_original | video_note | 2/7 | 5.248 | 5.283 | 5.283 | — |
| `gemini-flash-lite-latest` | json_audio_control | video_note | 5/8 | 1.995 | 5.608 | 5.608 | — |
| `gemini-flash-lite-latest` | json_original | long_voice | 7/8 | 6.859 | 13.136 | 13.136 | — |
| `gemini-flash-lite-latest` | json_original | short_voice | 6/6 | 2.909 | 9.131 | 9.131 | — |
| `gemini-flash-lite-latest` | json_original | video_note | 8/10 | 3.169 | 9.920 | 9.920 | — |
| `gemini-omni-1.1-flash` | json_audio_control | video_note | 0/2 | — | — | — | — |
| `gemini-omni-1.1-flash` | json_original | long_voice | 0/3 | — | — | — | — |
| `gemini-omni-1.1-flash` | json_original | short_voice | 0/4 | — | — | — | — |
| `gemini-omni-1.1-flash` | json_original | video_note | 0/2 | — | — | — | — |
| `gemini-omni-flash-preview` | json_audio_control | video_note | 0/3 | — | — | — | — |
| `gemini-omni-flash-preview` | json_original | long_voice | 0/2 | — | — | — | — |
| `gemini-omni-flash-preview` | json_original | short_voice | 0/4 | — | — | — | — |
| `gemini-omni-flash-preview` | json_original | video_note | 0/1 | — | — | — | — |
| `gemini-pro-latest` | json_audio_control | video_note | 0/2 | — | — | — | — |
| `gemini-pro-latest` | json_original | long_voice | 0/2 | — | — | — | — |
| `gemini-pro-latest` | json_original | short_voice | 0/3 | — | — | — | — |
| `gemini-pro-latest` | json_original | video_note | 0/4 | — | — | — | — |

## День и ночь (Europe/Berlin)

| Период | Попытки | Успехи |
|---|---:|---:|
| day 10:00–20:59 | 398 | 213 |
| night 21:00–09:59 | 262 | 144 |

## Ошибки и покрытие

| Статус | Количество |
|---|---:|
| error | 155 |
| invalid_json | 1 |
| quota_global | 12 |
| quota_model_limit | 17 |
| quota_model_zero | 63 |
| skipped_model_quota | 162 |
| skipped_quota | 486 |
| success | 357 |
| timeout | 26 |
| unavailable | 29 |

## Данные и воспроизводимость

- [raw-measurements.csv](raw-measurements.csv): allowlist числовых измерений и технических статусов; ни свободных текстов ошибок, ни ответов модели.
- [summary.json](summary.json): сгруппированные показатели; [day-night-summary.json](day-night-summary.json): аналогичная разбивка по периодам.
- Стоимость: без подтверждённых тарифов для всех текущих моделей и фактического биллинга долларовая сумма не заявляется. Число вызовов ограничено; сырой usage хранится приватно для проверки.
- Не публикуются аудио, видео, расшифровки, summary пользовательского содержания, file URI, ключи и исходные журналы.
- API-адаптеры проверены изолированными unit tests и отдельными реальными smoke-запросами; smoke не входит в эту статистику.
- Источники протокола: [Live Transcribe](https://ai.google.dev/gemini-api/docs/live-api/live-transcribe), [File Transcribe](https://ai.google.dev/gemini-api/docs/transcribe), [Live API](https://ai.google.dev/gemini-api/docs/live-api/capabilities).

## Решение

Выбор победителя до окончания окна не делается. Этот PR будет обновляться тем же runner-ом. Автоматической смены модели нет.
