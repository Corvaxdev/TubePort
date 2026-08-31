# Release process

This document is for maintainers publishing TubePort from Windows 10/11 x64.

## 1. Prepare the version

Update the version consistently in:

- `VERSION`
- `src/TubePort.pyw`
- `packaging/version_info.txt`
- `packaging/tubeport.manifest`
- `packaging/README.html` and `packaging/QUICK_START.txt`
- `third_party/COMPONENTS.json`
- `CHANGELOG.md`

Update pinned tool versions, URLs, executable hashes, and archive hashes in
`third_party/TOOLS.lock.json` only after verifying the official upstream
release. Refresh the corresponding notices and license texts when required.

## 2. Build in a disposable directory

64-bit Python 3.12.10 is required for the pinned release recipe. Keep build
data outside the repository:

```powershell
.\packaging\build.ps1 `
  -WorkDirectory D:\build\TubePort `
  -OutputDirectory D:\releases\TubePort
```

The script creates a fresh virtual environment, installs pinned build
dependencies, compiles the source, runs deterministic source and packaged UI
contracts, builds with PyInstaller, writes an internal manifest, creates the
bootstrap ZIP, and writes a `.sha256` sidecar.

## 3. Inspect before publishing

Confirm that:

- the ZIP contains one top-level `TubePort-<version>-win64` directory;
- `TubePort.exe`, `_internal`, setup scripts, notices, and license files exist;
- no media, cookies, logs, diagnostic state, credentials, or personal paths are
  present;
- the public bootstrap ZIP does **not** contain yt-dlp, Deno, FFmpeg, or
  ffprobe binaries;
- the external checksum and internal `SHA256SUMS.txt` both verify;
- `Setup-Tools.ps1` installs only artifacts matching `TOOLS.lock.json`.

Do not upload a full bundle containing third-party GPL binaries unless the
maintainer has separately completed and documented every applicable source,
notice, and redistribution obligation. The default public artifact avoids this
problem by downloading those tools directly from upstream on the user's
machine.

## 4. Publish

Commit the reviewed source, create an annotated `v<version>` tag on that exact
commit, and create a GitHub Release containing only:

- `TubePort-<version>-win64-bootstrap.zip`
- `TubePort-<version>-win64-bootstrap.zip.sha256`

Release notes must state that this is an unsigned proof-of-concept build, that
the setup step needs internet access, and that authenticated Instagram behavior
depends on the user's own valid session. Mark a release as pre-release while
important paths remain unverified.
