# Changelog

Notable user-visible changes to TubePort are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Nothing yet.

## [2.1.1] - 2026-08-31

### Added

- English desktop interface and release documentation.
- Instagram Reel URL recognition alongside supported YouTube video links.
- Authentication selection through existing Chrome, Edge, Brave, Vivaldi,
  Opera, Chromium, Firefox, and Naver Whale profiles.
- User-selected Netscape `cookies.txt` authentication with format validation.
- External-browser sign-in launch; TubePort does not accept account passwords.
- Structured diagnostics for browser locks, missing profiles, invalid cookie
  files, sign-in requirements, and Chromium App-Bound/DPAPI cookie failures.
- Verified bootstrap setup, pinned component inventory, and SHA-256 integrity
  checks. Public archives obtain external media tools directly from upstream.

### Changed

- Improved the compact desktop layout and download-status reporting.
- Made the default one-item option explicit when a YouTube link also contains a
  playlist.
- Improved privacy redaction in persistent and copied diagnostic reports.

### Fixed

- Restored Ctrl+V in the URL field under English and non-English Windows
  keyboard layouts.
- Added Shift+Insert and context-menu paste behavior.
- Clarified the difference between a locked Chromium cookie database and a v20
  App-Bound/DPAPI decryption failure.

### Verification

- Verified the public YouTube test download and inspected the resulting media
  with ffprobe.
- Verified that an Instagram Reel requiring sign-in is classified as an
  authentication requirement rather than a generic download failure.
- Verified the Windows x64 application package and the pinned tool-setup
  inventory.

Earlier builds were internal proof-of-concept iterations and are not documented
as public releases here.

[Unreleased]: ../../compare/v2.1.1...HEAD
[2.1.1]: ../../releases/tag/v2.1.1
