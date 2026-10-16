# Gemini media benchmark — 15–16 октября 2026

**ПРОМЕЖУТОЧНЫЙ ОТЧЁТ — эксперимент продолжается**

Плановое окно UTC: `2026-10-15T15:55:34+00:00` → `2026-10-16T15:55:34+00:00`. 24 часа, каждые 2 часа.
Циклы с записанными строками: **11 / 12**. Строки: **1199 / 1308**.
Реальные попытки: **591**; успешные: **323**; пропущенные защитой: **608**.

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
| `gemini-2.5-flash` | json_original | short_voice | 4/5 | 4.100 | 4.753 | 4.753 | — |
| `gemini-2.5-flash` | json_original | video_note | 4/5 | 6.274 | 6.850 | 6.850 | — |
| `gemini-2.5-flash-lite` | json_audio_control | video_note | 8/8 | 1.837 | 2.263 | 2.263 | — |
| `gemini-2.5-flash-lite` | json_original | long_voice | 3/5 | 5.274 | 6.503 | 6.503 | — |
| `gemini-2.5-flash-lite` | json_original | short_voice | 4/4 | 1.685 | 1.958 | 1.958 | — |
| `gemini-2.5-flash-lite` | json_original | video_note | 9/9 | 4.009 | 6.614 | 6.614 | — |
| `gemini-2.5-flash-native-audio-latest` | live_agent_input_stt | long_voice | 5/5 | 183.558 | 184.325 | 184.325 | 4.581 |
| `gemini-2.5-flash-native-audio-latest` | live_agent_input_stt | short_voice | 8/8 | 5.812 | 6.898 | 6.898 | 3.103 |
| `gemini-2.5-flash-native-audio-latest` | live_agent_input_stt | video_note | 8/8 | 31.688 | 33.059 | 33.059 | 2.942 |
| `gemini-2.5-flash-native-audio-preview-09-2025` | live_agent_input_stt | long_voice | 6/6 | 190.117 | 198.674 | 198.674 | 4.521 |
| `gemini-2.5-flash-native-audio-preview-09-2025` | live_agent_input_stt | short_voice | 5/5 | 5.935 | 6.612 | 6.612 | 3.368 |
| `gemini-2.5-flash-native-audio-preview-09-2025` | live_agent_input_stt | video_note | 6/6 | 32.695 | 35.802 | 35.802 | 2.960 |
| `gemini-2.5-flash-native-audio-preview-12-2025` | live_agent_input_stt | long_voice | 5/5 | 181.199 | 192.846 | 192.846 | 4.590 |
| `gemini-2.5-flash-native-audio-preview-12-2025` | live_agent_input_stt | short_voice | 9/9 | 6.154 | 7.862 | 7.862 | 3.097 |
| `gemini-2.5-flash-native-audio-preview-12-2025` | live_agent_input_stt | video_note | 6/6 | 32.335 | 33.488 | 33.488 | 3.026 |
| `gemini-2.5-pro` | json_audio_control | video_note | 0/7 | — | — | — | — |
| `gemini-2.5-pro` | json_original | long_voice | 0/6 | — | — | — | — |
| `gemini-2.5-pro` | json_original | short_voice | 0/5 | — | — | — | — |
| `gemini-2.5-pro` | json_original | video_note | 0/8 | — | — | — | — |
| `gemini-3-flash-preview` | json_audio_control | video_note | 5/7 | 5.459 | 14.166 | 14.166 | — |
| `gemini-3-flash-preview` | json_original | long_voice | 4/5 | 7.647 | 11.163 | 11.163 | — |
| `gemini-3-flash-preview` | json_original | short_voice | 5/6 | 3.413 | 13.761 | 13.761 | — |
| `gemini-3-flash-preview` | json_original | video_note | 7/7 | 6.270 | 19.148 | 19.148 | — |
| `gemini-3.1-flash-lite` | json_audio_control | video_note | 5/9 | 2.469 | 17.418 | 17.418 | — |
| `gemini-3.1-flash-lite` | json_original | long_voice | 5/8 | 5.694 | 13.567 | 13.567 | — |
| `gemini-3.1-flash-lite` | json_original | short_voice | 4/6 | 4.196 | 17.339 | 17.339 | — |
| `gemini-3.1-flash-lite` | json_original | video_note | 5/8 | 3.969 | 11.218 | 11.218 | — |
| `gemini-3.1-flash-lite-preview` | json_audio_control | video_note | 4/7 | 6.479 | 17.076 | 17.076 | — |
| `gemini-3.1-flash-lite-preview` | json_original | long_voice | 4/7 | 4.929 | 5.105 | 5.105 | — |
| `gemini-3.1-flash-lite-preview` | json_original | short_voice | 3/6 | 1.718 | 2.226 | 2.226 | — |
| `gemini-3.1-flash-lite-preview` | json_original | video_note | 4/7 | 1.955 | 2.369 | 2.369 | — |
| `gemini-3.1-flash-live-preview` | live_agent_input_stt | long_voice | 7/7 | 181.118 | 181.828 | 181.828 | 180.326 |
| `gemini-3.1-flash-live-preview` | live_agent_input_stt | short_voice | 6/6 | 3.928 | 4.738 | 4.738 | 3.157 |
| `gemini-3.1-flash-live-preview` | live_agent_input_stt | video_note | 7/7 | 30.869 | 31.348 | 31.348 | 29.940 |
| `gemini-3.1-pro-preview` | json_audio_control | video_note | 0/2 | — | — | — | — |
| `gemini-3.1-pro-preview` | json_original | long_voice | 0/3 | — | — | — | — |
| `gemini-3.1-pro-preview` | json_original | short_voice | 0/2 | — | — | — | — |
| `gemini-3.1-pro-preview` | json_original | video_note | 0/2 | — | — | — | — |
| `gemini-3.1-pro-preview-customtools` | json_audio_control | video_note | 0/3 | — | — | — | — |
| `gemini-3.1-pro-preview-customtools` | json_original | long_voice | 0/2 | — | — | — | — |
| `gemini-3.1-pro-preview-customtools` | json_original | short_voice | 0/2 | — | — | — | — |
| `gemini-3.1-pro-preview-customtools` | json_original | video_note | 0/3 | — | — | — | — |
| `gemini-3.5-flash` | json_audio_control | video_note | 3/3 | 4.349 | 10.131 | 10.131 | — |
| `gemini-3.5-flash` | json_original | long_voice | 1/4 | 10.926 | 10.926 | 10.926 | — |
| `gemini-3.5-flash` | json_original | short_voice | 3/4 | 2.953 | 9.327 | 9.327 | — |
| `gemini-3.5-flash` | json_original | video_note | 3/5 | 5.420 | 5.789 | 5.789 | — |
| `gemini-3.5-flash-lite` | json_audio_control | video_note | 9/9 | 3.606 | 6.804 | 6.804 | — |
| `gemini-3.5-flash-lite` | json_original | long_voice | 6/7 | 5.881 | 13.678 | 13.678 | — |
| `gemini-3.5-flash-lite` | json_original | short_voice | 5/5 | 1.806 | 5.236 | 5.236 | — |
| `gemini-3.5-flash-lite` | json_original | video_note | 7/7 | 2.834 | 9.853 | 9.853 | — |
| `gemini-3.5-transcribe` | file_smart_pipeline | long_voice | 1/4 | 15.592 | 15.592 | 15.592 | — |
| `gemini-3.5-transcribe` | file_smart_pipeline | short_voice | 1/5 | 9.363 | 9.363 | 9.363 | — |
| `gemini-3.5-transcribe` | file_smart_pipeline | video_note | 5/7 | 11.195 | 18.727 | 18.727 | — |
| `gemini-3.5-transcribe` | file_verbatim_stt | long_voice | 4/5 | 8.968 | 11.450 | 11.450 | — |
| `gemini-3.5-transcribe` | file_verbatim_stt | short_voice | 8/8 | 6.464 | 14.869 | 14.869 | — |
| `gemini-3.5-transcribe` | file_verbatim_stt | video_note | 7/8 | 6.698 | 8.002 | 8.002 | — |
| `gemini-3.5-transcribe-live` | live_burst_experimental | long_voice | 0/11 | — | — | — | — |
| `gemini-3.5-transcribe-live` | live_burst_experimental | short_voice | 0/8 | — | — | — | — |
| `gemini-3.5-transcribe-live` | live_burst_experimental | video_note | 7/7 | 1.541 | 1.950 | 1.950 | 1.225 |
| `gemini-3.5-transcribe-live` | live_production_pipeline | long_voice | 1/3 | 186.202 | 186.202 | 186.202 | 3.883 |
| `gemini-3.5-transcribe-live` | live_production_pipeline | short_voice | 0/4 | — | — | — | — |
| `gemini-3.5-transcribe-live` | live_production_pipeline | video_note | 0/5 | — | — | — | — |
| `gemini-3.5-transcribe-live` | live_smart_stt | long_voice | 5/5 | 178.506 | 178.783 | 178.783 | 3.815 |
| `gemini-3.5-transcribe-live` | live_smart_stt | short_voice | 7/7 | 3.198 | 3.278 | 3.278 | 2.340 |
| `gemini-3.5-transcribe-live` | live_smart_stt | video_note | 0/5 | — | — | — | — |
| `gemini-3.6-flash` | json_audio_control | video_note | 3/6 | 3.628 | 4.831 | 4.831 | — |
| `gemini-3.6-flash` | json_original | long_voice | 1/7 | 8.475 | 8.475 | 8.475 | — |
| `gemini-3.6-flash` | json_original | short_voice | 1/3 | 2.573 | 2.573 | 2.573 | — |
| `gemini-3.6-flash` | json_original | video_note | 2/4 | 3.845 | 4.198 | 4.198 | — |
| `gemini-3.7-flash` | json_audio_control | video_note | 2/7 | 8.406 | 11.097 | 11.097 | — |
| `gemini-3.7-flash` | json_original | long_voice | 1/5 | 12.752 | 12.752 | 12.752 | — |
| `gemini-3.7-flash` | json_original | short_voice | 1/5 | 5.913 | 5.913 | 5.913 | — |
| `gemini-3.7-flash` | json_original | video_note | 0/8 | — | — | — | — |
| `gemini-3.8-flash` | json_audio_control | video_note | 1/7 | 5.149 | 5.149 | 5.149 | — |
| `gemini-3.8-flash` | json_original | long_voice | 1/8 | 13.164 | 13.164 | 13.164 | — |
| `gemini-3.8-flash` | json_original | short_voice | 1/7 | 4.228 | 4.228 | 4.228 | — |
| `gemini-3.8-flash` | json_original | video_note | 4/6 | 10.977 | 16.436 | 16.436 | — |
| `gemini-3.8-live` | live_agent_input_stt | long_voice | 5/5 | 180.900 | 181.026 | 181.026 | 180.140 |
| `gemini-3.8-live` | live_agent_input_stt | short_voice | 6/6 | 3.979 | 4.191 | 4.191 | 3.337 |
| `gemini-3.8-live` | live_agent_input_stt | video_note | 7/7 | 30.727 | 31.030 | 31.030 | 30.136 |
| `gemini-3.8-live-extended-thinking` | live_agent_input_stt | long_voice | 0/8 | — | — | — | — |
| `gemini-3.8-live-extended-thinking` | live_agent_input_stt | short_voice | 0/7 | — | — | — | — |
| `gemini-3.8-live-extended-thinking` | live_agent_input_stt | video_note | 0/6 | — | — | — | — |
| `gemini-4-argon` | json_audio_control | video_note | 0/3 | — | — | — | — |
| `gemini-4-argon` | json_original | long_voice | 0/3 | — | — | — | — |
| `gemini-4-argon` | json_original | short_voice | 0/1 | — | — | — | — |
| `gemini-4-argon` | json_original | video_note | 0/2 | — | — | — | — |
| `gemini-flash-latest` | json_audio_control | video_note | 2/4 | 13.207 | 17.315 | 17.315 | — |
| `gemini-flash-latest` | json_original | long_voice | 1/5 | 13.114 | 13.114 | 13.114 | — |
| `gemini-flash-latest` | json_original | short_voice | 0/5 | — | — | — | — |
| `gemini-flash-latest` | json_original | video_note | 2/7 | 5.248 | 5.283 | 5.283 | — |
| `gemini-flash-lite-latest` | json_audio_control | video_note | 5/7 | 1.995 | 5.608 | 5.608 | — |
| `gemini-flash-lite-latest` | json_original | long_voice | 6/7 | 6.268 | 13.136 | 13.136 | — |
| `gemini-flash-lite-latest` | json_original | short_voice | 5/5 | 1.688 | 9.131 | 9.131 | — |
| `gemini-flash-lite-latest` | json_original | video_note | 7/9 | 1.974 | 7.209 | 7.209 | — |
| `gemini-omni-1.1-flash` | json_audio_control | video_note | 0/2 | — | — | — | — |
| `gemini-omni-1.1-flash` | json_original | long_voice | 0/3 | — | — | — | — |
| `gemini-omni-1.1-flash` | json_original | short_voice | 0/4 | — | — | — | — |
| `gemini-omni-1.1-flash` | json_original | video_note | 0/1 | — | — | — | — |
| `gemini-omni-flash-preview` | json_audio_control | video_note | 0/2 | — | — | — | — |
| `gemini-omni-flash-preview` | json_original | long_voice | 0/2 | — | — | — | — |
| `gemini-omni-flash-preview` | json_original | short_voice | 0/4 | — | — | — | — |
| `gemini-omni-flash-preview` | json_original | video_note | 0/1 | — | — | — | — |
| `gemini-pro-latest` | json_audio_control | video_note | 0/2 | — | — | — | — |
| `gemini-pro-latest` | json_original | long_voice | 0/2 | — | — | — | — |
| `gemini-pro-latest` | json_original | short_voice | 0/3 | — | — | — | — |
| `gemini-pro-latest` | json_original | video_note | 0/3 | — | — | — | — |

## День и ночь (Europe/Berlin)

| Период | Попытки | Успехи |
|---|---:|---:|
| day 10:00–20:59 | 329 | 179 |
| night 21:00–09:59 | 262 | 144 |

## Ошибки и покрытие

| Статус | Количество |
|---|---:|
| error | 136 |
| invalid_json | 1 |
| quota_global | 11 |
| quota_model_limit | 13 |
| quota_model_zero | 57 |
| skipped_model_quota | 139 |
| skipped_quota | 469 |
| success | 323 |
| timeout | 24 |
| unavailable | 26 |

## Данные и воспроизводимость

- [raw-measurements.csv](raw-measurements.csv): allowlist числовых измерений и технических статусов; ни свободных текстов ошибок, ни ответов модели.
- [summary.json](summary.json): сгруппированные показатели; [day-night-summary.json](day-night-summary.json): аналогичная разбивка по периодам.
- Стоимость: без подтверждённых тарифов для всех текущих моделей и фактического биллинга долларовая сумма не заявляется. Число вызовов ограничено; сырой usage хранится приватно для проверки.
- Не публикуются аудио, видео, расшифровки, summary пользовательского содержания, file URI, ключи и исходные журналы.
- API-адаптеры проверены изолированными unit tests и отдельными реальными smoke-запросами; smoke не входит в эту статистику.
- Источники протокола: [Live Transcribe](https://ai.google.dev/gemini-api/docs/live-api/live-transcribe), [File Transcribe](https://ai.google.dev/gemini-api/docs/transcribe), [Live API](https://ai.google.dev/gemini-api/docs/live-api/capabilities).

## Решение

Выбор победителя до окончания окна не делается. Этот PR будет обновляться тем же runner-ом. Автоматической смены модели нет.
