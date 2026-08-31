<p align="center">
  <img src="assets/tubeport.png" width="104" alt="TubePort icon">
</p>

# TubePort

[![CI](https://github.com/nanomicron/TubePort/actions/workflows/ci.yml/badge.svg)](https://github.com/nanomicron/TubePort/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-2ea44f.svg)](LICENSE)
[![Windows 10/11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078d4.svg)](#download-and-run)

TubePort is a portable Windows desktop application for downloading video or
audio from supported YouTube video URLs and Instagram Reel URLs. It provides a
small graphical interface over locally installed command-line media tools and includes
local diagnostics for common authentication and packaging failures.

Current version: **2.1.4**
Supported release platform: **Windows 10/11 x64**

> [!IMPORTANT]
> Download only material that you own or have permission to use. You are
> responsible for complying with applicable law, copyright, the source site's
> terms, and any access restrictions. TubePort is not affiliated with YouTube,
> Google, Instagram, or Meta.

## Features

- YouTube watch, Shorts, live, embed, and `youtu.be` video links
- Instagram Reel links
- Video with audio: MP4, MKV, or WebM
- Audio only: MP3, M4A, or Opus
- Maximum-quality selection from 360p through 2160p, or best available
- A one-item mode that prevents an attached YouTube playlist from being
  downloaded unintentionally
- Optional authenticated access through a user-selected Netscape `cookies.txt`
  file, or through a detected Mozilla Firefox installation
- Honest Windows authentication choices: Chromium profiles are not offered
  because current App-Bound/DPAPI cookie protection makes direct access
  unreliable outside the browser
- Native paste behavior, including Ctrl+V under non-English Windows keyboard
  layouts, Shift+Insert, and the context menu
- Portable save-location discovery through the Windows Downloads Known Folder,
  including redirected and localized user folders
- Unambiguous folder controls that open the selected destination and, after a
  successful download, select the exact result in File Explorer
- Attempt-scoped cancellation that stops the active downloader process tree
  without allowing stale events to affect a later download
- Local diagnostics that distinguish browser database locks, Chromium
  App-Bound/DPAPI decryption failures, missing profiles, invalid cookie files,
  and sign-in requirements
- A verified bootstrap release: no Python installation is required, and a
  one-click setup downloads pinned media tools from their upstream releases

Support means that TubePort recognizes the URL and delegates retrieval to its
locally installed media tools. Availability is not guaranteed: source sites change, a
video may be private or removed, and Instagram in particular may require an
authenticated session even for links that appear public in a signed-in browser.

## Download and run

1. Download the Windows bootstrap ZIP from the repository's **Releases** page.
2. Verify the archive against the published SHA-256 checksum.
3. Extract the entire archive to a normal folder.
4. Run `Setup-Tools.cmd` once while connected to the internet. It verifies every
   downloaded tool against `TOOLS.lock.json`.
5. Run `TubePort.exe`.
6. Paste a supported link, choose the media type, quality, format, and output
   folder, then select **Download**. Use **Cancel download** if you need to stop
   the active attempt before it finishes.

Do not run the executable directly inside the ZIP. Keep `TubePort.exe`, the
`_internal` directory, and—after setup—the `tools` directory together. Once
setup is complete, that folder can be copied to another Windows x64 machine.

## Save location and download controls

TubePort selects the current Windows Downloads Known Folder by default through
the Windows Known Folder API. This follows a Downloads location redirected by
Windows or the user; registry and profile-directory fallbacks are available if
the API cannot resolve it. File Explorer may display a localized name such as
**Загрузки** while the physical directory is named `Downloads`. Those labels do
not by themselves indicate two separate folders.

**Choose folder…** opens a directory picker. It intentionally shows folders and
hides files because its only purpose is to choose a destination. **Open save
folder** opens the destination currently used by the attempt. After a successful
download, that button becomes **Show downloaded file** and selects the exact
result in File Explorer.

While a download is active, **Cancel download** moves the attempt immediately to
the canceling state and stops its downloader process tree. Completion and cancel
events belong to a single attempt, so a late event from an earlier attempt cannot
change the state of a later one. TubePort does not remove unrelated or
pre-existing files when canceling; a partial file created by the downloader may
remain.

## Authentication

TubePort does not provide an embedded login form and never asks for a username,
password, or two-factor authentication code. Sign in only on the official site
in your regular external browser.

Under **Advanced options**, choose one of these modes:

| Mode | When to use it | Important notes |
| --- | --- | --- |
| Do not use | Public media that the source site serves anonymously | The site may still require sign-in. |
| `cookies.txt` file | Recommended Windows mode when sign-in is required | Use a fresh Netscape-format export from your own signed-in session. Treat the file like an active session credential. |
| Mozilla Firefox profile | Firefox is installed and the required session is active in it | This choice appears only when TubePort detects `firefox.exe`. Select the correct Firefox profile. |

When cookies are required, TubePort offers **Use cookies.txt…** directly on the
error result. In file mode, **Export help** opens yt-dlp's upstream guidance in
your default browser.

### Why Chromium profiles are not shown on Windows

TubePort deliberately does not offer direct Google Chrome, Microsoft Edge,
Brave, Vivaldi, Opera, Chromium, or Naver Whale profile access in its Windows
interface. Current Chromium browsers can protect `v20` cookies with Windows
App-Bound/DPAPI encryption, which makes direct reading by yt-dlp unreliable.
Closing the browser does not fix this encryption failure. Use a fresh Netscape
`cookies.txt` export instead, or an installed Firefox profile when it is
offered.

Do not run TubePort as administrator, weaken browser security, or copy raw
browser databases. Never share or commit a `cookies.txt` file. Delete exported
cookies when they are no longer needed and revoke the associated session if the
file may have been exposed.

## Diagnostics

Open **Diagnostics and log** in the application for a structured status report
and recent output. Persistent logs are stored under:

```text
%LOCALAPPDATA%\TubePort\logs
```

The portable bundle can also check its embedded components and manifest:

```powershell
.\TubePort.exe --bundle-self-test --report-file .\bundle-report.json
```

Diagnostic reports defensively redact cookie-like values and media URLs, but
they can still contain filenames, browser/profile labels, and error messages.
Review a report before posting it publicly.

## Run from source

Python 3.12.10 x64 is the verified release-build version. The GUI uses the
Python standard library; `sv-ttk` is optional in source mode. Run
`Setup-Tools.ps1` to install the pinned tools under the repository's `tools`
directory, or provide compatible yt-dlp, FFmpeg, and JavaScript runtime
executables on `PATH`.

```powershell
python -m pip install -r .\requirements.txt
.\Setup-Tools.ps1
python .\src\TubePort.pyw
```

Run the deterministic source checks with:

```powershell
python -m py_compile .\src\TubePort.pyw
python .\src\TubePort.pyw --url-input-self-test
python .\src\TubePort.pyw --cancellation-self-test
python .\src\TubePort.pyw --ui-contract
python .\src\TubePort.pyw --self-test
```

The cancellation check owns a harmless local process tree, stops it, confirms
that neither the parent nor child survived, and removes its marker file. The UI
contract verifies Known Folder resolution, result reveal behavior, per-attempt
state isolation, and English interface strings. The broader `--self-test`
reports the locally discovered yt-dlp, FFmpeg,
JavaScript runtime, authentication-source inventory, and command contract. It
is expected to report missing optional tools on an incomplete development
machine.

## Privacy and security

TubePort does not implement analytics or telemetry. It starts yt-dlp to make
the requests needed for the selected download and writes diagnostics locally.
Authentication data remains sensitive even though TubePort does not collect a
password. See [SECURITY.md](SECURITY.md) before reporting a vulnerability.

## Contributing

Bug reports and focused pull requests are welcome. Please read
[CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md) first. Never attach cookies, account
tokens, credentials, private media, or unredacted diagnostics to an issue.

## Third-party components

The public bootstrap ZIP does not redistribute yt-dlp, Deno, or FFmpeg
binaries. `Setup-Tools.ps1` downloads pinned artifacts directly from their
upstream release pages and verifies SHA-256 before local installation. The
PyInstaller application contains Python and sv-ttk runtime material. See
[`third_party`](third_party) for the component inventory and notices. Upstream
projects retain their own names, copyrights, and licenses.

## License

TubePort's original source code is released under the [MIT License](LICENSE),
Copyright (c) 2026 nanomicron. Third-party components remain under their own
licenses.
