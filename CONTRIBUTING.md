# Contributing to TubePort

Thank you for helping improve TubePort. The project is intentionally small, so
focused changes with clear verification are preferred.

## Before opening an issue

- Search existing issues and the current release notes.
- Confirm the problem occurs with the latest TubePort release.
- Run the bundle self-test if you are using the portable package.
- Remove credentials, cookies, tokens, private URLs, and personal paths from
  anything you plan to post.
- If the report concerns a vulnerability, follow [SECURITY.md](SECURITY.md)
  instead of opening a public issue.

Source sites change frequently. An extractor failure may belong upstream in
yt-dlp rather than in TubePort. A TubePort issue is appropriate when the GUI,
URL validation, option mapping, local authentication flow, diagnostics, or
portable packaging behaves incorrectly.

## Development setup

Python 3.12 on Windows is the verified development environment.

```powershell
cd TubePort
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r .\requirements.txt
.\Setup-Tools.ps1
```

Install FFmpeg separately and make it available on `PATH` when testing actual
downloads. A compatible JavaScript runtime may also be required for current
YouTube extraction. Do not commit downloaded runtimes or local browser data.

Run the application from source:

```powershell
python .\src\TubePort.pyw
```

## Required checks

Run at least these deterministic checks before submitting a pull request:

```powershell
python -m py_compile .\src\TubePort.pyw
python .\src\TubePort.pyw --url-input-self-test
python .\src\TubePort.pyw --cancellation-self-test
python .\src\TubePort.pyw --ui-contract
```

When yt-dlp, FFmpeg, and a JavaScript runtime are available, also run:

```powershell
python .\src\TubePort.pyw --self-test
```

For UI or packaging changes, include the relevant UI-contract or portable
bundle verification results in the pull request. Network download tests must
use media that you own or are authorized to test, and they must not be added to
the repository.

## Pull requests

1. Keep each pull request scoped to one change.
2. Explain the user-visible behavior before and after the change.
3. Include reproducible verification steps and their result.
4. Update documentation and `CHANGELOG.md` when behavior changes.
5. Preserve the English user interface unless a reviewed localization system
   is introduced.
6. Do not weaken URL validation, authentication boundaries, diagnostic
   redaction, or portable-bundle integrity checks.
7. Do not add a server, telemetry, credential collection, automated browser
   login, or remote cookie storage without an explicit design and security
   review.

## Coding guidance

- Prefer the Python standard library for application logic.
- Keep subprocess arguments as lists; do not build shell command strings from
  user input.
- Treat browser cookies and `cookies.txt` as credentials.
- Keep persistent diagnostics useful but privacy-preserving.
- Ensure cancellation, temporary paths, and output paths remain safe on
  Windows.
- Do not silently close browsers or bypass browser security controls.

## Commit hygiene

Never commit:

- `cookies.txt`, browser profiles, cookie databases, or session exports
- diagnostic logs or test media
- credentials, API tokens, signing keys, or local environment files
- build directories, unpacked portable bundles, or release ZIP files
- generated caches such as `__pycache__`

By participating, you agree to follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
