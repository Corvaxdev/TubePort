# Changelog

Notable user-visible changes to TubePort are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Nothing yet.

## [2.1.4] - 2026-08-31

### Added

- Added **Cancel download** with attempt-scoped cancellation that stops the
  active downloader process tree.
- Added **Show downloaded file** after a successful download so File Explorer
  selects the exact result rather than merely opening a directory.

### Changed

- Resolve the default destination through the Windows Downloads Known Folder
  API, with registry and profile-directory fallbacks. Redirected and localized
  Downloads locations are now followed automatically.
- Renamed the destination controls to **Choose folder…** and **Open save folder**
  to make their behavior explicit. The directory picker intentionally displays
  folders only.

### Fixed

- Prevented late progress, completion, and cancellation events from an older
  attempt from changing the state of a newer download.
- Made cancellation effective both before and after the downloader subprocess
  starts, with a clear canceling/canceled state in the interface.

### Verification

- Added deterministic contracts for Windows Known Folder resolution, localized
  paths, destination/result reveal policy, pre-launch cancellation, process-tree
  cancellation, and stale-event isolation.

## [2.1.3] - 2026-08-31

### Changed

- Removed Google Chrome, Microsoft Edge, Brave, Vivaldi, Opera, Chromium, and
  Naver Whale profile choices from the Windows interface. End-to-end checks
  showed that current App-Bound/DPAPI-protected Chromium cookies could not be
  used reliably outside the browser.
- Made a user-selected Netscape `cookies.txt` file the primary authenticated
  path on Windows.
- Show Mozilla Firefox profile authentication only when `firefox.exe` is
  detected.

### Verification

- Added a deterministic Windows GUI contract that fails if a Chromium profile
  label is exposed, if `cookies.txt` is missing, or if Firefox visibility does
  not match installation detection.
- Reconfirmed that Chrome `Default`, Chrome `Profile 2`, and Edge `Default`
  reach yt-dlp but fail to decrypt the current Windows DPAPI-protected cookies;
  closing Chromium does not resolve that failure.

## [2.1.2] - 2026-08-31

### Added

- A direct `Use cookies.txt…` recovery action for authentication failures and
  an in-app link to the upstream cookie-export guide.

### Changed

- Browser process detection is now advisory. TubePort always lets yt-dlp try
  the selected profile and classifies the actual result.
- Cookie database access errors no longer claim that a running browser is the
  definite cause.

### Fixed

- Removed a false preflight failure where an unrelated or background
  `chrome.exe` was treated as proof that the selected cookie database was
  locked.
- Cleared stale in-memory and persisted attempt details before validation so a
  previous error cannot contaminate a new diagnostic report.
- Kept the previous authentication selection intact when the cookies.txt
  recovery file chooser is canceled.

### Verification

- Reproduced the original failure through the structured debug probe.
- Verified that Chrome `Default`, Chrome `Profile 2`, and Edge `Default` now
  reach yt-dlp and correctly report Windows App-Bound/DPAPI protection instead
  of a synthetic browser-lock error.

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

[Unreleased]: ../../compare/v2.1.4...HEAD
[2.1.4]: ../../compare/v2.1.3...v2.1.4
[2.1.3]: ../../compare/v2.1.2...v2.1.3
[2.1.2]: ../../compare/v2.1.1...v2.1.2
[2.1.1]: ../../releases/tag/v2.1.1
