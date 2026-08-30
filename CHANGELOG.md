# Changelog

All notable changes to this project will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project intends to use semantic version tags for public releases.

## [Unreleased]

### Added

- Native Telegram `sendMessageDraft` streaming for Gemini Live transcripts in private chats.
- Dedicated Gemini 3.5 Transcribe file and Live API modes, including incremental transcript updates.
- FFmpeg-based audio extraction and conversion for video notes and live transcription.
- Repository governance, contribution, support, and security documentation.
- Automated CI, dependency updates, code scanning, labels, and release notes.
- Multilingual README files and a redesigned project overview.

### Changed

- Final private-chat results are sent as persistent messages after the ephemeral Live draft.
- Live processing now shows a persistent hint and uses a shorter `Другая модель` button label.
- The default Gemini fallback order now follows the August 2026 load benchmark.
- The Google Gen AI SDK has been upgraded to the supported 2.x release line.
- Container publication is gated by the same quality checks used for pull requests.

### Fixed

- Video notes now use the file transcription model instead of Gemini Live, and FFmpeg reads MP4
  input from a seekable temporary file to support Telegram video containers reliably.
- Live transcription now finishes when Gemini emits `generationComplete` without a trailing
  `turnComplete` event.
- Gemini responses now use an enforced JSON schema, and truncated structured responses no longer
  appear as raw JSON inside the transcription block.
