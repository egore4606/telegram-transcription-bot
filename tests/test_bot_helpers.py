import bot


def test_parse_response_sections_standard_response() -> None:
    raw = "ТРАНСКРИПЦИЯ:\nПривет, мир\n\nКРАТКОЕ СОДЕРЖАНИЕ:\nКороткое summary"

    transcription, summary = bot.parse_response_sections(raw, "both")

    assert transcription == "Привет, мир"
    assert summary == "Короткое summary"


def test_parse_response_sections_tldr_response() -> None:
    raw = "КРАТКОЕ СОДЕРЖАНИЕ:\nОдно главное предложение."

    transcription, summary = bot.parse_response_sections(raw, "tldr")

    assert transcription == ""
    assert summary == "Одно главное предложение."


def test_parse_response_sections_handles_partial_response() -> None:
    raw = "КРАТКОЕ СОДЕРЖАНИЕ:\nЕсть только summary без транскрипции."

    transcription, summary = bot.parse_response_sections(raw, "both")

    assert transcription == ""
    assert summary == "Есть только summary без транскрипции."


def test_parse_response_sections_handles_nonstandard_response() -> None:
    raw = "Просто свободный текст без ожидаемых секций."

    transcription, summary = bot.parse_response_sections(raw, "both")

    assert transcription == raw
    assert summary == ""


def test_format_response_escapes_html_for_both_mode() -> None:
    raw = "ТРАНСКРИПЦИЯ:\n<hello> & bye\n\nКРАТКОЕ СОДЕРЖАНИЕ:\nUse <b>tags</b>"

    formatted = bot.format_response(raw, "both")

    assert "📝 <b>Транскрипция:</b>" in formatted
    assert "📌 <b>Краткое содержание:</b>" in formatted
    assert "&lt;hello&gt; &amp; bye" in formatted
    assert "Use &lt;b&gt;tags&lt;/b&gt;" in formatted


def test_format_response_transcription_only_mode() -> None:
    raw = "ТРАНСКРИПЦИЯ:\nТолько текст\n\nКРАТКОЕ СОДЕРЖАНИЕ:\nНе должно попасть в ответ"

    formatted = bot.format_response(raw, "transcription_only")

    assert "Только текст" in formatted
    assert "Краткое содержание" not in formatted


def test_format_response_summary_only_mode() -> None:
    raw = "ТРАНСКРИПЦИЯ:\nНе нужен\n\nКРАТКОЕ СОДЕРЖАНИЕ:\nНужен только summary"

    formatted = bot.format_response(raw, "summary_only")

    assert "Нужен только summary" in formatted
    assert "Транскрипция" not in formatted


def test_format_response_tldr_mode() -> None:
    raw = "КРАТКОЕ СОДЕРЖАНИЕ:\nСамая важная мысль."

    formatted = bot.format_response(raw, "tldr")

    assert formatted == "💡 Самая важная мысль."


def test_build_prompt_differs_for_voice_and_video() -> None:
    voice_prompt = bot.build_prompt("voice", "auto", "both")
    video_prompt = bot.build_prompt("video", "auto", "both")

    assert "голосовое сообщение" in voice_prompt
    assert "видео-кружочек" in video_prompt
    assert "что происходит на видео" in video_prompt


def test_build_prompt_differs_for_auto_and_fixed_language() -> None:
    auto_prompt = bot.build_prompt("voice", "auto", "both")
    fixed_prompt = bot.build_prompt("voice", "de", "both")

    assert "Сохраняй язык оригинала." in auto_prompt
    assert "Переведи ответ на язык: de." in fixed_prompt


def test_build_prompt_differs_for_tldr_and_regular_modes() -> None:
    tldr_prompt = bot.build_prompt("voice", "auto", "tldr")
    regular_prompt = bot.build_prompt("voice", "auto", "both")

    assert "ОДНО короткое предложение" in tldr_prompt
    assert "Выполни две задачи" not in tldr_prompt
    assert "Выполни две задачи" in regular_prompt
