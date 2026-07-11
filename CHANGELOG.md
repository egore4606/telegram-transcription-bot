# Changelog

All notable changes to this project will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project intends to use semantic version tags for public releases.

## [Unreleased]

### Added

- Repository governance, contribution, support, and security documentation.
- Automated CI, dependency updates, code scanning, labels, and release notes.
- Multilingual README files and a redesigned project overview.

### Changed

- Container publication is gated by the same quality checks used for pull requests.

### Fixed

- Gemini responses now use an enforced JSON schema, and truncated structured responses no longer
  appear as raw JSON inside the transcription block.
