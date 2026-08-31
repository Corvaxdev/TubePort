# SPDX-License-Identifier: MIT
# Copyright (c) 2026 nanomicron

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import sv_ttk
except ImportError:  # Source mode remains usable without the optional theme package.
    sv_ttk = None

APP_NAME = "TubePort"
APP_VERSION = "2.1.2"
APP_TAGLINE = "Download video or audio from YouTube and Instagram in your preferred format"
VIDEO_FORMATS = ("MP4", "MKV", "WebM")
AUDIO_FORMATS = ("MP3", "M4A", "Opus")
QUALITIES = ("Best", "2160p", "1440p", "1080p", "720p", "480p", "360p")
MEDIA_VIDEO_LABEL = "Video + audio"
MEDIA_AUDIO_LABEL = "Audio only"
COOKIE_NONE_LABEL = "Do not use"
COOKIE_BROWSERS = {
    COOKIE_NONE_LABEL: None,
    "Google Chrome": "chrome",
    "Microsoft Edge": "edge",
    "Brave": "brave",
    "Vivaldi": "vivaldi",
    "Opera": "opera",
    "Chromium": "chromium",
    "Mozilla Firefox": "firefox",
    "Naver Whale": "whale",
}
COOKIE_FILE_LABEL = "cookies.txt file…"
COOKIE_PROFILE_AUTO = "Automatic"
SUPPORTED_COOKIE_BROWSERS = frozenset(browser for browser in COOKIE_BROWSERS.values() if browser)
CHROMIUM_COOKIE_BROWSERS = frozenset({"brave", "chrome", "chromium", "edge", "opera", "vivaldi", "whale"})
BROWSER_EXECUTABLE_NAMES = {
    "brave": "brave.exe",
    "chrome": "chrome.exe",
    "chromium": "chromium.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
    "opera": "opera.exe",
    "vivaldi": "vivaldi.exe",
    "whale": "whale.exe",
}
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
TK_SHIFT_MASK = 0x0001
TK_CONTROL_MASK = 0x0004
WINDOWS_VIRTUAL_KEY_V = 86
COOKIE_EXPORT_HELP_URL = "https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp"


def is_url_paste_shortcut(
    keysym: str,
    keycode: int,
    state: int,
    platform_name: str | None = None,
) -> bool:
    """Recognize native paste shortcuts independently of the active keyboard layout."""
    normalized_keysym = (keysym or "").casefold()
    if state & TK_SHIFT_MASK and normalized_keysym in {"insert", "kp_insert"}:
        return True
    if not state & TK_CONTROL_MASK:
        return False
    if normalized_keysym == "v":
        return True
    return (platform_name or os.name) == "nt" and keycode == WINDOWS_VIRTUAL_KEY_V


def compose_url_paste(
    current: str,
    clipboard: str,
    cursor: int,
    selection: tuple[int, int] | None = None,
    *,
    replace_all: bool = False,
) -> tuple[str, int]:
    """Return Entry text/cursor after a native paste or a full-field replacement."""
    if replace_all:
        return clipboard, len(clipboard)
    text_length = len(current)
    cursor = max(0, min(cursor, text_length))
    if selection is None:
        start = end = cursor
    else:
        start, end = sorted(selection)
        start = max(0, min(start, text_length))
        end = max(start, min(end, text_length))
    updated = current[:start] + clipboard + current[end:]
    return updated, start + len(clipboard)


@dataclass(frozen=True)
class MediaLink:
    platform: str
    kind: str
    media_id: str
    canonical_url: str
    id_ref: str


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def app_directory() -> Path:
    """Directory containing the portable executable (or this source file)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundled_resource(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", app_directory()))
    return base / relative


def configure_process_environment() -> None:
    """Keep temporary files writable and UTF-8 output deterministic."""
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def emit_json(value: object, output_path: str | Path | None = None) -> str:
    payload = json.dumps(value, ensure_ascii=False, indent=2)
    if output_path:
        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload + "\n", encoding="utf-8")
    if sys.stdout is not None:
        try:
            sys.stdout.write(payload + "\n")
            sys.stdout.flush()
        except (AttributeError, OSError):
            pass
    return payload


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def command_version(path: str | None, *arguments: str) -> dict[str, object]:
    if not path:
        return {"path": None, "version": None, "exit_code": None, "present": False}
    executable = Path(path)
    try:
        completed = subprocess.run(
            [str(executable), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            timeout=20,
            check=False,
        )
        version = next((line.strip() for line in completed.stdout.splitlines() if line.strip()), "")
        return {
            "path": str(executable),
            "version": version,
            "exit_code": completed.returncode,
            "present": executable.is_file(),
            "sha256": sha256_file(executable),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"path": str(executable), "version": None, "exit_code": None, "present": executable.is_file(), "error": str(exc)}


def verify_sha256_manifest(root: Path, manifest_path: Path) -> dict[str, object]:
    result: dict[str, object] = {"path": str(manifest_path), "checked": 0, "missing": [], "mismatched": [], "invalid": [], "ok": False}
    if not manifest_path.is_file():
        result["invalid"] = ["manifest_missing"]
        return result
    missing: list[str] = []
    mismatched: list[str] = []
    invalid: list[str] = []
    checked = 0
    try:
        root_resolved = root.resolve()
        for line_number, raw_line in enumerate(manifest_path.read_text(encoding="utf-8-sig").splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            match = re.fullmatch(r"([A-Fa-f0-9]{64})\s+\*?(.+)", line)
            if not match:
                invalid.append(f"line:{line_number}")
                continue
            expected, relative = match.groups()
            target = (root_resolved / relative.replace("/", os.sep)).resolve()
            try:
                target.relative_to(root_resolved)
            except ValueError:
                invalid.append(f"outside_root:{relative}")
                continue
            if not target.is_file():
                missing.append(relative)
                continue
            actual = sha256_file(target)
            checked += 1
            if actual != expected.upper():
                mismatched.append(relative)
    except OSError as exc:
        invalid.append(str(exc))
    result.update({"checked": checked, "missing": missing, "mismatched": mismatched, "invalid": invalid, "ok": checked > 0 and not missing and not mismatched and not invalid})
    return result


def diagnostics_root() -> Path:
    override = os.environ.get("TUBEPORT_DATA_ROOT")
    if override:
        return Path(override).expanduser().resolve() / "logs"
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    return local / "TubePort" / "logs"


def youtube_video_id(value: str) -> str | None:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        return parsed.path.strip("/").split("/")[0] or None
    if host == "youtube.com" or host.endswith(".youtube.com"):
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            return parts[1]
    return None


def instagram_media_id(value: str) -> str | None:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in {"instagram.com", "www.instagram.com", "m.instagram.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) == 2 and parts[0].casefold() == "reel":
        media_id = parts[1]
        if re.fullmatch(r"[A-Za-z0-9_-]{5,64}", media_id):
            return media_id
    return None


def parse_media_url(value: str) -> MediaLink | None:
    try:
        parsed = urlparse(value.strip())
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or port is not None:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"):
        media_id = youtube_video_id(value)
        if media_id and re.fullmatch(r"[A-Za-z0-9_-]{6,32}", media_id):
            canonical = f"https://www.youtube.com/watch?v={media_id}"
            return MediaLink("youtube", "video", media_id, canonical, hashlib.sha256(f"youtube:{media_id}".encode()).hexdigest()[:12])
    if host in {"instagram.com", "www.instagram.com", "m.instagram.com"}:
        media_id = instagram_media_id(value)
        if media_id:
            canonical = f"https://www.instagram.com/reel/{media_id}/"
            return MediaLink("instagram", "reel", media_id, canonical, hashlib.sha256(f"instagram:{media_id}".encode()).hexdigest()[:12])
    return None


def media_identity(value: str) -> tuple[str | None, str | None]:
    link = parse_media_url(value)
    return (link.platform, link.media_id) if link else (None, None)


def redact_diagnostic_line(value: str) -> str:
    # yt-dlp does not normally print cookie values, but keep persistent logs defensive.
    safe = re.sub(
        r'''(?i)(["'](?:set-)?cookies?["']\s*:\s*["']).*?(["'])''',
        r"\1[redacted]\2",
        value,
    )
    safe = re.sub(r"(?i)((?:set-)?cookies?\s*[:=]\s*).+$", r"\1[redacted]", safe)

    def sanitize_url(match: re.Match[str]) -> str:
        raw = match.group(0)
        suffix = ""
        while raw and raw[-1] in ".,);]":
            suffix = raw[-1] + suffix
            raw = raw[:-1]
        try:
            parsed = urlparse(raw)
            link = parse_media_url(raw)
            host = (parsed.hostname or "").lower()
            if link and link.platform == "youtube":
                clean = f"{parsed.scheme}://{host}/watch?v=[ref:{link.id_ref}]"
            elif link and link.platform == "instagram":
                clean = f"{parsed.scheme}://{host}/reel/[ref:{link.id_ref}]/"
            else:
                clean = parsed._replace(query="", fragment="").geturl()
            return clean + suffix
        except ValueError:
            return "[redacted-url]" + suffix

    safe = re.sub(r'''https?://[^\s<>"']+''', sanitize_url, safe)

    def redact_instagram_token(match: re.Match[str]) -> str:
        token = match.group(2)
        reference = hashlib.sha256(f"instagram:{token}".encode()).hexdigest()[:12]
        return f"{match.group(1)}[ref:{reference}]"

    safe = re.sub(r"(?i)(\[Instagram\]\s+)([A-Za-z0-9_-]{5,64})", redact_instagram_token, safe)
    safe = re.sub(r"\[([A-Za-z0-9_-]{5,64})\](?=\.[A-Za-z0-9]{2,5}\b)", "[media-id]", safe)
    return safe


def sanitize_report_for_copy(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): sanitize_report_for_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_report_for_copy(item) for item in value]
    if isinstance(value, str):
        return value.replace(str(Path.home()), "%USERPROFILE%")
    return value


class DiagnosticsStore:
    def __init__(
        self,
        state_name: str | None = None,
        pointer_name: str | None = "latest-app.json",
        log_name: str = "app.log",
    ) -> None:
        self.root = diagnostics_root()
        self.log_path = self.root / Path(log_name).name
        self.state_path = self.root / Path(state_name or f"state-gui-{os.getpid()}.json").name
        self.pointer_path = self.root / Path(pointer_name).name if pointer_name else None
        self._lock = threading.Lock()
        self._memory_state: dict[str, object] = {}
        self._archived_terminal_key: tuple[object, object] | None = None
        self.last_error: str | None = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if self.log_path.exists() and self.log_path.stat().st_size > 2_000_000:
                rotated = self.root / "app.previous.log"
                os.replace(self.log_path, rotated)
        except OSError as exc:
            self.last_error = str(exc)

    def _atomic_write(self, path: Path, text: str) -> None:
        temporary = self.root / f".{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)

    def append(self, line: str) -> None:
        safe = redact_diagnostic_line(line.rstrip())
        try:
            with self._lock:
                with self.log_path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(f"{now_iso()}  {safe}\n")
            self.last_error = None
        except OSError as exc:
            self.last_error = str(exc)

    def write_state(self, state: dict[str, object]) -> None:
        self._memory_state = dict(state)
        try:
            with self._lock:
                self.root.mkdir(parents=True, exist_ok=True)
                payload = json.dumps(state, ensure_ascii=False, indent=2)
                self._atomic_write(self.state_path, payload)
                if self.pointer_path:
                    pointer = json.dumps(
                        {"state_file": self.state_path.name, "updated_at": state.get("updated_at")},
                        ensure_ascii=False,
                        indent=2,
                    )
                    self._atomic_write(self.pointer_path, pointer)
                if state.get("phase") in {"completed", "failed", "cancelled"}:
                    self._atomic_write(self.root / "last-terminal.json", payload)
                    terminal_key = (state.get("phase"), state.get("updated_at"))
                    if terminal_key != self._archived_terminal_key:
                        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
                        self._atomic_write(self.root / f"attempt-{stamp}-{os.getpid()}.json", payload)
                        self._archived_terminal_key = terminal_key
            self.last_error = None
        except OSError as exc:
            self.last_error = str(exc)

    def read_state(self) -> dict[str, object]:
        if self._memory_state:
            result = dict(self._memory_state)
            if self.last_error:
                result["diagnostics_error"] = self.last_error
            return result
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "app_version": APP_VERSION,
                "phase": "no_state",
                "message": "No diagnostic state has been created yet.",
                "state_path": str(self.state_path),
                "log_path": str(self.log_path),
                "diagnostics_error": str(exc),
            }


class MemoryDiagnosticsStore:
    def __init__(self) -> None:
        self.root = Path("<memory>")
        self.log_path = self.root / "app.log"
        self.state_path = self.root / "state.json"
        self.last_error: str | None = None
        self._state: dict[str, object] = {}
        self.lines: list[str] = []

    def append(self, line: str) -> None:
        self.lines.append(redact_diagnostic_line(line.rstrip()))

    def write_state(self, state: dict[str, object]) -> None:
        self._state = dict(state)

    def read_state(self) -> dict[str, object]:
        return dict(self._state)


def read_diagnostic_pointer(pointer_name: str) -> dict[str, object]:
    root = diagnostics_root()
    pointer_path = root / Path(pointer_name).name
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        state_name = Path(str(pointer["state_file"])).name
        return json.loads((root / state_name).read_text(encoding="utf-8"))
    except (KeyError, OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return {
            "app_version": APP_VERSION,
            "phase": "no_state",
            "message": f"No diagnostic state is available for {pointer_name}",
            "diagnostics_error": str(exc),
        }


def read_diagnostic_file(file_name: str) -> dict[str, object]:
    path = diagnostics_root() / Path(file_name).name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "app_version": APP_VERSION,
            "phase": "no_state",
            "message": f"No diagnostic state is available for {file_name}",
            "diagnostics_error": str(exc),
        }


def read_recent_attempts(root: Path | None = None, limit: int = 8) -> list[dict[str, object]]:
    directory = root or diagnostics_root()
    if not directory.is_dir():
        return []
    attempts: list[dict[str, object]] = []
    try:
        paths = sorted(directory.glob("attempt-*.json"), key=lambda path: path.name, reverse=True)[: max(0, limit)]
        for path in paths:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                attempts.append(
                    {
                        "file": path.name,
                        "updated_at": value.get("updated_at"),
                        "phase": value.get("phase"),
                        "service": value.get("service"),
                        "error_kind": value.get("error_kind"),
                        "message": value.get("message"),
                    }
                )
            except (OSError, json.JSONDecodeError, AttributeError):
                continue
    except OSError:
        return []
    return attempts


def find_executable(name: str) -> str | None:
    executable = f"{name}.exe" if os.name == "nt" else name
    portable_candidate = app_directory() / "tools" / executable
    if getattr(sys, "frozen", False):
        return str(portable_candidate) if portable_candidate.is_file() else None
    candidates = [
        portable_candidate,
        app_directory().parent / "tools" / executable,
        Path(sys.executable).resolve().parent / executable,
        Path(sys.executable).resolve().parent / "Scripts" / executable,
        Path(sys.executable).resolve().parent.parent / "Scripts" / executable,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def _environment_path(variable: str, *parts: str) -> Path | None:
    value = os.environ.get(variable)
    return Path(value, *parts) if value else None


def browser_user_data_root(browser: str) -> Path | None:
    browser = browser.casefold()
    locations: dict[str, tuple[str, tuple[str, ...]]] = {
        "brave": ("LOCALAPPDATA", ("BraveSoftware", "Brave-Browser", "User Data")),
        "chrome": ("LOCALAPPDATA", ("Google", "Chrome", "User Data")),
        "chromium": ("LOCALAPPDATA", ("Chromium", "User Data")),
        "edge": ("LOCALAPPDATA", ("Microsoft", "Edge", "User Data")),
        "firefox": ("APPDATA", ("Mozilla", "Firefox")),
        "opera": ("APPDATA", ("Opera Software", "Opera Stable")),
        "vivaldi": ("LOCALAPPDATA", ("Vivaldi", "User Data")),
        "whale": ("LOCALAPPDATA", ("Naver", "Naver Whale", "User Data")),
    }
    location = locations.get(browser)
    return _environment_path(location[0], *location[1]) if location else None


def _browser_executable_candidates(browser: str) -> list[Path]:
    local = os.environ.get("LOCALAPPDATA")
    program_files = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    relative: dict[str, tuple[str, ...]] = {
        "brave": ("BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
        "chrome": ("Google", "Chrome", "Application", "chrome.exe"),
        "chromium": ("Chromium", "Application", "chrome.exe"),
        "edge": ("Microsoft", "Edge", "Application", "msedge.exe"),
        "firefox": ("Mozilla Firefox", "firefox.exe"),
        "opera": ("Opera", "opera.exe"),
        "vivaldi": ("Vivaldi", "Application", "vivaldi.exe"),
        "whale": ("Naver", "Naver Whale", "Application", "whale.exe"),
    }
    result: list[Path] = []
    parts = relative.get(browser.casefold())
    if not parts:
        return result
    if local:
        result.append(Path(local, *parts))
        if browser == "opera":
            result.append(Path(local, "Programs", "Opera", "opera.exe"))
        elif browser == "vivaldi":
            result.append(Path(local, "Programs", "Vivaldi", "Application", "vivaldi.exe"))
    for base in program_files:
        if base:
            result.append(Path(base, *parts))
    return result


def find_browser_executable(browser: str) -> str | None:
    browser = browser.casefold()
    executable_name = BROWSER_EXECUTABLE_NAMES.get(browser)
    if not executable_name:
        return None
    on_path = shutil.which(executable_name)
    if on_path:
        return on_path
    if os.name == "nt":
        try:
            import winreg

            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}") as key:
                        value, _kind = winreg.QueryValueEx(key, None)
                    path = Path(str(value).strip('"'))
                    if path.is_file():
                        return str(path)
                except OSError:
                    continue
        except ImportError:
            pass
    return next((str(candidate) for candidate in _browser_executable_candidates(browser) if candidate.is_file()), None)


def discover_browser_profiles(browser: str) -> list[tuple[str, str | None]]:
    browser = browser.casefold()
    profiles: list[tuple[str, str | None]] = [(COOKIE_PROFILE_AUTO, None)]
    root = browser_user_data_root(browser)
    if not root or not root.is_dir():
        return profiles
    if browser == "firefox":
        parser = configparser.RawConfigParser()
        try:
            parser.read(root / "profiles.ini", encoding="utf-8")
            for section in parser.sections():
                if not section.startswith("Profile"):
                    continue
                name = parser.get(section, "Name", fallback="").strip()
                profile_path = parser.get(section, "Path", fallback="").strip()
                if not name or not profile_path:
                    continue
                candidate = (root / profile_path) if parser.getboolean(section, "IsRelative", fallback=True) else Path(profile_path)
                if candidate.is_dir():
                    profiles.append((name, name))
        except (OSError, configparser.Error, ValueError):
            return profiles
        return profiles
    if browser == "opera":
        return profiles

    try:
        candidates = [path for path in root.iterdir() if path.is_dir() and (path.name == "Default" or path.name.startswith("Profile "))]
    except OSError:
        return profiles
    candidates.sort(key=lambda path: (path.name != "Default", path.name.casefold()))
    for path in candidates:
        if not ((path / "Preferences").is_file() or (path / "Network" / "Cookies").is_file() or (path / "Cookies").is_file()):
            continue
        profiles.append((path.name, path.name))
    return profiles


def discover_browser_inventory() -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []
    for label, browser in COOKIE_BROWSERS.items():
        if not browser:
            continue
        executable = find_browser_executable(browser)
        root = browser_user_data_root(browser)
        profiles = discover_browser_profiles(browser)
        inventory.append(
            {
                "browser": browser,
                "label": label,
                "installed": bool(executable or (root and root.exists())),
                "executable": executable,
                "profile_root": str(root) if root else None,
                "profiles": [profile_label for profile_label, _value in profiles],
            }
        )
    return inventory


def browser_process_running(browser: str) -> bool:
    if os.name != "nt":
        return False
    process_names = {
        "chromium": ("chromium.exe", "chrome.exe"),
    }.get(browser.casefold(), (BROWSER_EXECUTABLE_NAMES.get(browser.casefold(), ""),))
    for process_name in process_names:
        if not process_name:
            continue
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/FO", "CSV", "/NH"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=8,
                check=False,
            )
            if re.search(rf'(?i)"?{re.escape(process_name)}"?', completed.stdout):
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def browser_cookie_process_advisory(
    browser: str | None,
    *,
    detected: bool | None = None,
) -> tuple[bool, str | None]:
    """Report process presence without treating it as proof of a cookie DB lock."""
    if not browser or browser not in CHROMIUM_COOKIE_BROWSERS:
        return False, None
    process_detected = browser_process_running(browser) if detected is None else bool(detected)
    if not process_detected:
        return False, None
    browser_label = next((label for label, key in COOKIE_BROWSERS.items() if key == browser), browser)
    return (
        True,
        f"A {browser_label} process was detected. TubePort will still try the selected profile because "
        "process presence alone does not prove that its cookie database is locked.",
    )


def build_browser_launch_command(browser: str, profile: str | None, url: str) -> list[str] | None:
    executable = find_browser_executable(browser)
    if not executable:
        return None
    command = [executable]
    if profile:
        if browser in CHROMIUM_COOKIE_BROWSERS and browser != "opera":
            command.append(f"--profile-directory={profile}")
        elif browser == "firefox":
            command.extend(["-P", profile])
    command.append(url)
    return command


def validate_cookies_file(path_text: str, service: str | None = None) -> dict[str, object]:
    path = Path(path_text).expanduser() if path_text.strip() else Path()
    result: dict[str, object] = {
        "ok": False,
        "error_kind": "cookies_file_invalid",
        "file_name": path.name if path_text.strip() else None,
        "cookie_rows": 0,
        "matching_rows": 0,
        "warning": None,
    }
    if not path_text.strip():
        result["message"] = "Select a cookies.txt file."
        return result
    if not path.is_file():
        result["message"] = "The cookies.txt file was not found."
        return result
    try:
        size = path.stat().st_size
        if size <= 0 or size > 50 * 1024 * 1024:
            result["message"] = "The cookies.txt file is empty or too large."
            return result
        header_seen = False
        cookie_rows = 0
        matching_rows = 0
        target_domains = {"youtube": ("youtube.com", "google.com"), "instagram": ("instagram.com",)}.get(service or "", ())
        with path.open("r", encoding="utf-8-sig", errors="replace") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                if line_number <= 30 and "netscape http cookie file" in raw_line.casefold():
                    header_seen = True
                line = raw_line.rstrip("\r\n")
                if line.startswith("#HttpOnly_"):
                    line = line[len("#HttpOnly_") :]
                elif not line or line.startswith("#"):
                    continue
                columns = line.split("\t")
                if len(columns) < 7:
                    continue
                domain = columns[0].lstrip(".").casefold()
                cookie_rows += 1
                if target_domains and any(domain == target or domain.endswith("." + target) for target in target_domains):
                    matching_rows += 1
        result.update({"cookie_rows": cookie_rows, "matching_rows": matching_rows})
        if not header_seen or cookie_rows == 0:
            result["message"] = "This is not a Netscape cookies.txt file, or it contains no cookies."
            return result
        result.update({"ok": True, "error_kind": None, "message": "The cookies.txt file is ready."})
        if target_domains and matching_rows == 0:
            result["warning"] = "No cookies for the selected service were found in this file."
        return result
    except OSError:
        result["message"] = "Could not read the cookies.txt file."
        return result


def find_js_runtime() -> tuple[str, str] | None:
    for name in ("deno", "node"):
        path = find_executable(name)
        if path:
            return name, path
    return None


def default_download_folder() -> Path:
    if os.name == "nt":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _kind = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
            redirected = Path(os.path.expandvars(str(value))).expanduser()
            if redirected.is_absolute():
                return redirected
        except (ImportError, OSError, ValueError):
            pass
    downloads = Path.home() / "Downloads"
    return downloads if downloads.exists() else Path.home()


def preferred_temp_folder() -> Path:
    override = os.environ.get("TUBEPORT_DATA_ROOT")
    if override:
        return Path(override).expanduser().resolve() / "temp"
    return Path(os.environ.get("TEMP", str(default_download_folder()))) / "TubePort"


def is_supported_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    service, media_id = media_identity(value)
    return bool(service and media_id)


def height_filter(quality: str) -> str:
    match = re.fullmatch(r"(\d+)p", quality)
    return f"[height<={match.group(1)}]" if match else ""


def build_download_command(
    yt_dlp: str,
    ffmpeg: str | None,
    url: str,
    output_folder: Path,
    temp_folder: Path,
    media_type: str,
    quality: str,
    container: str,
    single_video: bool = True,
    cookies_browser: str | None = None,
    browser_profile: str | None = None,
    cookies_file: str | Path | None = None,
    js_runtime: tuple[str, str] | None = None,
) -> list[str]:
    command = [
        yt_dlp,
        "--ignore-config",
        "--no-cache-dir",
        "--no-remote-components",
        "--newline",
        "--no-color",
        "--encoding",
        "utf-8",
        "--windows-filenames",
        "--trim-filenames",
        "180",
        "--progress-template",
        "download:PROGRESS|%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s|%(info.vcodec)s|%(info.acodec)s",
        "--print",
        "before_dl:TITLE:%(title)s",
        "--print",
        "after_move:RESULT:%(filepath)s",
        "--no-simulate",
        "--progress",
        "--paths",
        f"home:{output_folder}",
        "--paths",
        f"temp:{temp_folder}",
        "--output",
        "%(title).180B [%(id)s].%(ext)s",
    ]

    if single_video:
        command.append("--no-playlist")

    if ffmpeg:
        command.extend(["--ffmpeg-location", str(Path(ffmpeg).parent)])

    if cookies_browser and cookies_file:
        raise ValueError("Browser cookies and cookies.txt are mutually exclusive")
    if browser_profile and not cookies_browser:
        raise ValueError("A browser profile requires a cookies browser")
    if cookies_browser:
        browser = cookies_browser.casefold()
        if browser not in SUPPORTED_COOKIE_BROWSERS:
            raise ValueError(f"Unsupported cookies browser: {cookies_browser}")
        if browser_profile:
            if any(character in browser_profile for character in "\r\n\0"):
                raise ValueError("Invalid browser profile")
            browser = f"{browser}:{browser_profile}"
        command.extend(["--cookies-from-browser", browser])
    elif cookies_file:
        command.extend(["--cookies", str(Path(cookies_file).expanduser().resolve())])

    if js_runtime:
        runtime_name, runtime_path = js_runtime
        command.extend(["--no-js-runtimes", "--js-runtimes", f"{runtime_name}:{runtime_path}"])

    if media_type == "audio":
        audio_format = container.lower()
        if audio_format == "m4a":
            selector = "bestaudio[ext=m4a]/bestaudio/best"
        elif audio_format == "opus":
            selector = "bestaudio[acodec^=opus]/bestaudio[ext=webm]/bestaudio/best"
        else:
            selector = "bestaudio/best"
        command.extend(["--format", selector, "--extract-audio", "--audio-format", audio_format])
        if audio_format == "mp3":
            command.extend(["--audio-quality", "0"])
    else:
        limit = height_filter(quality)
        if container == "MP4":
            selector = (
                f"bestvideo{limit}[ext=mp4]+bestaudio[ext=m4a]"
                f"/best{limit}[ext=mp4]"
            )
            command.extend(["--format", selector, "--merge-output-format", "mp4", "--remux-video", "mp4"])
        elif container == "WebM":
            selector = (
                f"bestvideo{limit}[ext=webm]+bestaudio[ext=webm]"
                f"/best{limit}[ext=webm]"
            )
            command.extend(["--format", selector, "--merge-output-format", "webm", "--remux-video", "webm"])
        else:
            selector = f"bestvideo{limit}+bestaudio/best{limit}"
            command.extend(["--format", selector, "--merge-output-format", "mkv", "--remux-video", "mkv"])

    command.append(url)
    return command


class DownloaderApp:
    def __init__(
        self,
        root: tk.Tk,
        diagnostics_store: DiagnosticsStore | MemoryDiagnosticsStore | None = None,
    ) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("880x720")
        self.root.minsize(780, 640)
        try:
            self.root.iconbitmap(str(bundled_resource("assets/tubeport.ico")))
        except (OSError, tk.TclError):
            pass

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.last_result: Path | None = None
        self.display_progress = 0.0
        self.busy = False
        self.cancel_requested = False
        self.close_after_cancel = False
        self.detected_error_kind: str | None = None
        self.last_error_line: str | None = None
        self.cookie_notice_shown = False
        self.active_cookie_browser: str | None = None
        self.active_browser_profile: str | None = None
        self.active_cookies_file: Path | None = None

        self.diagnostics = diagnostics_store or DiagnosticsStore()
        self.recent_log: deque[str] = deque(maxlen=120)
        self.debug_state: dict[str, object] = {
            "schema": 1,
            "app_version": APP_VERSION,
            "phase": "initializing",
            "started_at": now_iso(),
            "pid": os.getpid(),
        }
        self.last_diagnostic_write = 0.0
        self.diagnostic_flush_pending = False

        self.yt_dlp = find_executable("yt-dlp")
        self.ffmpeg = find_executable("ffmpeg")
        self.js_runtime = find_js_runtime()
        self.browser_inventory = discover_browser_inventory()

        self.url_var = tk.StringVar()
        self.media_type_var = tk.StringVar(value=MEDIA_VIDEO_LABEL)
        self.quality_var = tk.StringVar(value="1080p")
        self.container_var = tk.StringVar(value="MP4")
        self.folder_var = tk.StringVar(value=str(default_download_folder()))
        self.single_video_var = tk.BooleanVar(value=True)
        self.cookies_browser_var = tk.StringVar(value=COOKIE_NONE_LABEL)
        self.cookies_profile_var = tk.StringVar(value=COOKIE_PROFILE_AUTO)
        self.cookies_file_var = tk.StringVar()
        self.cookie_hint_var = tk.StringVar(value="Public media usually does not require authentication.")
        self.profile_values: dict[str, str | None] = {COOKIE_PROFILE_AUTO: None}
        self.status_var = tk.StringVar(value="Ready to download")
        self.progress_var = tk.DoubleVar(value=0)
        self.tools_var = tk.StringVar()
        self.result_var = tk.StringVar()
        self.advanced_visible = False
        self.details_visible = False
        self.option_widgets: list[tk.Widget] = []

        self._configure_style()
        self._build_ui_v2()
        self._update_tool_status()
        self.diagnostics.append(f"=== session started; version={APP_VERSION}; pid={os.getpid()} ===")
        self.record_state(
            force=True,
            phase="ready",
            tools={"yt_dlp": self.yt_dlp, "ffmpeg": self.ffmpeg, "js_runtime": self.js_runtime},
            browser_inventory=self.browser_inventory,
            auth_source="none",
            message="Ready to download",
        )
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self._poll_events)

    def _configure_style(self) -> None:
        if sv_ttk is not None:
            try:
                sv_ttk.set_theme("light")
            except tk.TclError:
                pass
        style = ttk.Style(self.root)
        self.root.configure(bg="#f3f5fa")
        style.configure("App.TFrame", background="#f3f5fa")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Title.TLabel", background="#f3f5fa", foreground="#142039", font=("Segoe UI Semibold", 22))
        style.configure("Subtitle.TLabel", background="#f3f5fa", foreground="#59657a", font=("Segoe UI", 10))
        style.configure("Version.TLabel", background="#e9edf7", foreground="#4c5a75", font=("Segoe UI Semibold", 9), padding=(8, 4))
        style.configure("Section.TLabel", background="#ffffff", foreground="#18243b", font=("Segoe UI Semibold", 10))
        style.configure("Card.TLabel", background="#ffffff", foreground="#2f3b52", font=("Segoe UI", 10))
        style.configure("Hint.TLabel", background="#ffffff", foreground="#667085", font=("Segoe UI", 9))
        style.configure("Status.TLabel", background="#ffffff", foreground="#26334c", font=("Segoe UI Semibold", 10))
        style.configure("Result.TLabel", background="#eef9f3", foreground="#17623a", font=("Segoe UI Semibold", 9), padding=(10, 8))
        style.configure("Error.TLabel", background="#fff0f0", foreground="#9b2734", font=("Segoe UI Semibold", 9), padding=(10, 8))
        style.configure("Primary.TButton", font=("Segoe UI Semibold", 10), padding=(18, 10))
        style.configure("Secondary.TButton", font=("Segoe UI", 9), padding=(11, 8))
        style.configure("Link.TButton", font=("Segoe UI", 9), padding=(4, 4))
        style.configure("TEntry", padding=6)
        style.configure("TCombobox", padding=5)
        style.configure("Horizontal.TProgressbar", thickness=11)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, style="App.TFrame", padding=(24, 20, 24, 20))
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="TubePort", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Paste a link, choose a format, and save the file without using a command line.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 14))

        card = ttk.Frame(outer, style="Card.TFrame", padding=18)
        card.pack(fill="both", expand=True)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(11, weight=1)

        ttk.Label(card, text="YouTube or Instagram link", style="Card.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        self.url_entry = ttk.Entry(card, textvariable=self.url_var, font=("Segoe UI", 10))
        self.url_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 13), padx=(0, 8))
        ttk.Button(card, text="Paste", command=self.paste_url, style="Secondary.TButton").grid(row=1, column=2, sticky="ew", pady=(5, 13))

        options = ttk.Frame(card, style="Card.TFrame")
        options.grid(row=2, column=0, columnspan=3, sticky="ew")
        for index in range(3):
            options.columnconfigure(index, weight=1)

        ttk.Label(options, text="Content", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(options, text="Quality (maximum)", style="Card.TLabel").grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Label(options, text="Format", style="Card.TLabel").grid(row=0, column=2, sticky="w", padx=(12, 0))

        self.media_combo = ttk.Combobox(options, textvariable=self.media_type_var, values=(MEDIA_VIDEO_LABEL, MEDIA_AUDIO_LABEL), state="readonly")
        self.media_combo.grid(row=1, column=0, sticky="ew", pady=(5, 13))
        self.media_combo.bind("<<ComboboxSelected>>", self.on_media_type_changed)

        self.quality_combo = ttk.Combobox(options, textvariable=self.quality_var, values=QUALITIES, state="readonly")
        self.quality_combo.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(5, 13))

        self.container_combo = ttk.Combobox(options, textvariable=self.container_var, values=VIDEO_FORMATS, state="readonly")
        self.container_combo.grid(row=1, column=2, sticky="ew", padx=(12, 0), pady=(5, 13))

        ttk.Checkbutton(
            card,
            text="Download only this item even if the link includes a playlist",
            variable=self.single_video_var,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 13))

        auth_row = ttk.Frame(card, style="Card.TFrame")
        auth_row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(0, 13))
        auth_row.columnconfigure(1, weight=1)
        ttk.Label(auth_row, text="Authentication when required:", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.cookies_combo = ttk.Combobox(
            auth_row,
            textvariable=self.cookies_browser_var,
            values=tuple(COOKIE_BROWSERS),
            state="readonly",
            width=20,
        )
        self.cookies_combo.grid(row=0, column=1, sticky="w")
        self.cookies_combo.bind("<<ComboboxSelected>>", self.on_cookie_browser_changed)
        ttk.Label(
            auth_row,
            text="Required for private or restricted media",
            style="Hint.TLabel",
        ).grid(row=0, column=2, sticky="e", padx=(12, 0))

        ttk.Label(card, text="Save folder", style="Card.TLabel").grid(row=5, column=0, columnspan=3, sticky="w")
        self.folder_entry = ttk.Entry(card, textvariable=self.folder_var)
        self.folder_entry.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(5, 12), padx=(0, 8))
        ttk.Button(card, text="Browse…", command=self.choose_folder, style="Secondary.TButton").grid(row=6, column=2, sticky="ew", pady=(5, 12))

        action_row = ttk.Frame(card, style="Card.TFrame")
        action_row.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(1, 12))
        action_row.columnconfigure(0, weight=1)
        self.download_button = ttk.Button(action_row, text="Download", command=self.start_download, style="Primary.TButton")
        self.download_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.cancel_button = ttk.Button(action_row, text="Cancel", command=self.cancel_download, state="disabled", style="Secondary.TButton")
        self.cancel_button.grid(row=0, column=1, padx=(0, 8))
        self.open_button = ttk.Button(action_row, text="Open folder", command=self.open_result_folder, style="Secondary.TButton")
        self.open_button.grid(row=0, column=2)
        self.diagnostics_button = ttk.Button(action_row, text="Diagnostics", command=self.open_diagnostics, style="Secondary.TButton")
        self.diagnostics_button.grid(row=0, column=3, padx=(8, 0))

        status_row = ttk.Frame(card, style="Card.TFrame")
        status_row.grid(row=8, column=0, columnspan=3, sticky="ew")
        status_row.columnconfigure(0, weight=1)
        ttk.Label(status_row, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=0, sticky="w")
        self.percent_label = ttk.Label(status_row, text="0%", style="Hint.TLabel")
        self.percent_label.grid(row=0, column=1, sticky="e")

        self.progress = ttk.Progressbar(card, variable=self.progress_var, maximum=100, mode="determinate")
        self.progress.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(5, 10))

        ttk.Label(card, textvariable=self.tools_var, style="Hint.TLabel").grid(row=10, column=0, columnspan=3, sticky="w", pady=(0, 7))

        log_frame = ttk.Frame(card, style="Card.TFrame")
        log_frame.grid(row=11, column=0, columnspan=3, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(
            log_frame,
            height=9,
            wrap="word",
            state="disabled",
            font=("Consolas", 9),
            bg="#f7f8fb",
            fg="#33405a",
            relief="flat",
            padx=10,
            pady=8,
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

        ttk.Label(
            card,
            text="Download only material you have the right to use.",
            style="Hint.TLabel",
        ).grid(row=12, column=0, columnspan=3, sticky="w", pady=(9, 0))

        self.url_entry.focus_set()

    def _build_ui_v2(self) -> None:
        outer = ttk.Frame(self.root, style="App.TFrame", padding=(28, 22, 28, 22))
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill="x", pady=(0, 16))
        header.columnconfigure(0, weight=1)
        title_row = ttk.Frame(header, style="App.TFrame")
        title_row.grid(row=0, column=0, sticky="w")
        ttk.Label(title_row, text="TubePort", style="Title.TLabel").pack(side="left")
        ttk.Label(title_row, text=f"v{APP_VERSION}", style="Version.TLabel").pack(side="left", padx=(12, 0), pady=(3, 0))
        ttk.Label(header, text=APP_TAGLINE, style="Subtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 0))

        card = ttk.Frame(outer, style="Card.TFrame", padding=(22, 20, 22, 16))
        card.pack(fill="both", expand=True)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(12, weight=1)

        ttk.Label(card, text="Media link", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        url_row = ttk.Frame(card, style="Card.TFrame")
        url_row.grid(row=1, column=0, sticky="ew", pady=(7, 16))
        url_row.columnconfigure(0, weight=1)
        self.url_entry = ttk.Entry(url_row, textvariable=self.url_var, font=("Segoe UI", 10))
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._configure_url_entry_actions()
        self.paste_button = ttk.Button(url_row, text="Paste", command=self.paste_url, style="Secondary.TButton")
        self.paste_button.grid(row=0, column=1, padx=(0, 6))
        self.clear_button = ttk.Button(url_row, text="Clear", command=self.clear_url, style="Secondary.TButton")
        self.clear_button.grid(row=0, column=2)

        options = ttk.Frame(card, style="Card.TFrame")
        options.grid(row=2, column=0, sticky="ew")
        for index in range(3):
            options.columnconfigure(index, weight=1)
        ttk.Label(options, text="Content", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(options, text="Maximum quality", style="Card.TLabel").grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Label(options, text="Format", style="Card.TLabel").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.media_combo = ttk.Combobox(options, textvariable=self.media_type_var, values=(MEDIA_VIDEO_LABEL, MEDIA_AUDIO_LABEL), state="readonly")
        self.media_combo.grid(row=1, column=0, sticky="ew", pady=(6, 16))
        self.media_combo.bind("<<ComboboxSelected>>", self.on_media_type_changed)
        self.quality_combo = ttk.Combobox(options, textvariable=self.quality_var, values=QUALITIES, state="readonly")
        self.quality_combo.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(6, 16))
        self.container_combo = ttk.Combobox(options, textvariable=self.container_var, values=VIDEO_FORMATS, state="readonly")
        self.container_combo.grid(row=1, column=2, sticky="ew", padx=(12, 0), pady=(6, 16))

        ttk.Label(card, text="Save to", style="Section.TLabel").grid(row=3, column=0, sticky="w")
        folder_row = ttk.Frame(card, style="Card.TFrame")
        folder_row.grid(row=4, column=0, sticky="ew", pady=(7, 10))
        folder_row.columnconfigure(0, weight=1)
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.folder_var)
        self.folder_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.folder_button = ttk.Button(folder_row, text="Browse…", command=self.choose_folder, style="Secondary.TButton")
        self.folder_button.grid(row=0, column=1)

        self.advanced_button = ttk.Button(
            card,
            text="▸ Advanced options",
            command=self.toggle_advanced,
            style="Link.TButton",
        )
        self.advanced_button.grid(row=5, column=0, sticky="w", pady=(0, 8))
        self.advanced_frame = ttk.Frame(card, style="Card.TFrame")
        self.advanced_frame.grid(row=6, column=0, sticky="ew", pady=(0, 12))
        self.advanced_frame.columnconfigure(1, weight=1)
        self.single_video_check = ttk.Checkbutton(
            self.advanced_frame,
            text="Download one item only, even if the link includes a playlist",
            variable=self.single_video_var,
        )
        self.single_video_check.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 9))
        ttk.Label(self.advanced_frame, text="Authentication when required", style="Card.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 12))
        self.cookies_combo = ttk.Combobox(
            self.advanced_frame,
            textvariable=self.cookies_browser_var,
            values=(*COOKIE_BROWSERS, COOKIE_FILE_LABEL),
            state="readonly",
            width=24,
        )
        self.cookies_combo.grid(row=1, column=1, sticky="w")
        self.cookies_combo.bind("<<ComboboxSelected>>", self.on_cookie_browser_changed)
        self.open_login_button = ttk.Button(
            self.advanced_frame,
            text="Open sign-in page",
            command=self.open_auth_page,
            style="Secondary.TButton",
        )
        self.open_login_button.grid(row=1, column=2, sticky="w", padx=(8, 0))

        self.cookies_profile_label = ttk.Label(self.advanced_frame, text="Browser profile", style="Card.TLabel")
        self.cookies_profile_label.grid(row=2, column=0, sticky="w", padx=(0, 12), pady=(7, 0))
        self.cookies_profile_combo = ttk.Combobox(
            self.advanced_frame,
            textvariable=self.cookies_profile_var,
            values=(COOKIE_PROFILE_AUTO,),
            state="readonly",
            width=32,
        )
        self.cookies_profile_combo.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(7, 0))

        self.cookies_file_label = ttk.Label(self.advanced_frame, text="cookies.txt file", style="Card.TLabel")
        self.cookies_file_label.grid(row=3, column=0, sticky="w", padx=(0, 12), pady=(7, 0))
        self.cookies_file_entry = ttk.Entry(self.advanced_frame, textvariable=self.cookies_file_var)
        self.cookies_file_entry.grid(row=3, column=1, sticky="ew", pady=(7, 0))
        self.cookies_file_button = ttk.Button(
            self.advanced_frame,
            text="Browse…",
            command=self.choose_cookies_file,
            style="Secondary.TButton",
        )
        self.cookies_file_button.grid(row=3, column=2, sticky="w", padx=(8, 0), pady=(7, 0))
        ttk.Label(
            self.advanced_frame,
            textvariable=self.cookie_hint_var,
            style="Hint.TLabel",
            wraplength=700,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(7, 0))
        self.advanced_frame.grid_remove()

        action_row = ttk.Frame(card, style="Card.TFrame")
        action_row.grid(row=7, column=0, sticky="ew", pady=(2, 14))
        action_row.columnconfigure(0, weight=1)
        self.download_button = ttk.Button(action_row, text="Download", command=self.start_download, style="Primary.TButton")
        self.download_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.cancel_button = ttk.Button(action_row, text="Cancel", command=self.cancel_download, state="disabled", style="Secondary.TButton")
        self.cancel_button.grid(row=0, column=1, padx=(0, 8))
        self.open_button = ttk.Button(action_row, text="Open folder", command=self.open_result_folder, style="Secondary.TButton")
        self.open_button.grid(row=0, column=2)

        self.result_frame = ttk.Frame(card, style="Card.TFrame")
        self.result_frame.grid(row=8, column=0, sticky="ew", pady=(0, 12))
        self.result_frame.columnconfigure(0, weight=1)
        self.result_label = ttk.Label(self.result_frame, textvariable=self.result_var, style="Result.TLabel", wraplength=610)
        self.result_label.grid(row=0, column=0, sticky="ew")
        self.auth_recovery_button = ttk.Button(
            self.result_frame,
            text="Use cookies.txt…",
            command=self.use_cookies_file,
            style="Secondary.TButton",
        )
        self.auth_recovery_button.grid(row=0, column=1, padx=(8, 0))
        self.open_file_button = ttk.Button(self.result_frame, text="Open file", command=self.open_result_file, style="Secondary.TButton")
        self.open_file_button.grid(row=0, column=2, padx=(8, 0))
        self.auth_recovery_button.grid_remove()
        self.result_frame.grid_remove()

        status_row = ttk.Frame(card, style="Card.TFrame")
        status_row.grid(row=9, column=0, sticky="ew")
        status_row.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(status_row, textvariable=self.status_var, style="Status.TLabel", wraplength=650)
        self.status_label.grid(row=0, column=0, sticky="w")
        self.percent_label = ttk.Label(status_row, text="0%", style="Hint.TLabel")
        self.percent_label.grid(row=0, column=1, sticky="e")
        self.progress = ttk.Progressbar(card, variable=self.progress_var, maximum=100, mode="determinate")
        self.progress.grid(row=10, column=0, sticky="new", pady=(6, 9))

        details_header = ttk.Frame(card, style="Card.TFrame")
        details_header.grid(row=11, column=0, sticky="ew")
        details_header.columnconfigure(1, weight=1)
        self.details_button = ttk.Button(details_header, text="Diagnostics and log", command=self.open_diagnostics, style="Link.TButton")
        self.details_button.grid(row=0, column=0, sticky="w")
        ttk.Label(details_header, textvariable=self.tools_var, style="Hint.TLabel").grid(row=0, column=1, sticky="e")

        self.log_frame = ttk.Frame(card, style="Card.TFrame")
        self.log_frame.grid(row=12, column=0, sticky="nsew", pady=(8, 0))
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(
            self.log_frame,
            height=5,
            wrap="word",
            state="disabled",
            font=("Cascadia Mono", 9),
            bg="#f5f7fb",
            fg="#33405a",
            relief="flat",
            padx=10,
            pady=8,
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self.log_frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)
        diagnostics_button = ttk.Button(self.log_frame, text="Open diagnostic report", command=self.open_diagnostics, style="Secondary.TButton")
        diagnostics_button.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.log_frame.grid_remove()

        ttk.Label(
            card,
            text="Download only material you have the right to use.",
            style="Hint.TLabel",
        ).grid(row=13, column=0, sticky="w", pady=(12, 0))

        self.option_widgets = [
            self.url_entry,
            self.paste_button,
            self.clear_button,
            self.media_combo,
            self.quality_combo,
            self.container_combo,
            self.folder_entry,
            self.folder_button,
            self.advanced_button,
            self.single_video_check,
            self.cookies_combo,
            self.cookies_profile_combo,
            self.cookies_file_entry,
            self.cookies_file_button,
            self.open_login_button,
        ]
        self.url_entry.bind("<Return>", lambda _event: self.start_download())
        self._refresh_auth_controls()
        self.url_entry.focus_set()

    def _update_tool_status(self) -> None:
        yt_state = "yt-dlp: found" if self.yt_dlp else "yt-dlp: NOT FOUND"
        ff_state = "ffmpeg: found" if self.ffmpeg else "ffmpeg: NOT FOUND"
        runtime_state = f"JS: {self.js_runtime[0]}" if self.js_runtime else "JS: NOT FOUND"
        self.tools_var.set(f"{yt_state}  •  {ff_state}  •  {runtime_state}")

    def record_state(self, force: bool = False, **changes: object) -> None:
        self.debug_state.update(changes)
        self.debug_state["updated_at"] = now_iso()
        self.debug_state["state_path"] = str(self.diagnostics.state_path)
        self.debug_state["log_path"] = str(self.diagnostics.log_path)
        self.debug_state["recent_log"] = list(self.recent_log)
        moment = time.monotonic()
        if not force and moment - self.last_diagnostic_write < 0.5:
            if not self.diagnostic_flush_pending:
                self.diagnostic_flush_pending = True
                delay = max(1, int((0.5 - (moment - self.last_diagnostic_write)) * 1000))
                try:
                    self.root.after(delay, self._flush_diagnostic_state)
                except tk.TclError:
                    pass
            return
        self.diagnostic_flush_pending = False
        self.last_diagnostic_write = moment
        self.diagnostics.write_state(dict(self.debug_state))

    def _flush_diagnostic_state(self) -> None:
        self.diagnostic_flush_pending = False
        self.record_state(force=True)

    def open_diagnostics(self) -> None:
        window = tk.Toplevel(self.root)
        window.title(f"Diagnostics — {APP_NAME}")
        window.geometry("760x520")
        window.minsize(620, 400)

        frame = ttk.Frame(window, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        report = tk.Text(frame, wrap="none", font=("Consolas", 9), padx=9, pady=8)
        report.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=report.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=report.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        report.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)

        def report_payload() -> dict[str, object]:
            value = self.diagnostics.read_state()
            value["recent_attempts"] = read_recent_attempts(self.diagnostics.root)
            return value

        def refresh_report() -> str:
            self.record_state(force=True)
            value = json.dumps(report_payload(), ensure_ascii=False, indent=2)
            report.configure(state="normal")
            report.delete("1.0", "end")
            report.insert("1.0", value)
            report.configure(state="disabled")
            return value

        def copy_report() -> None:
            refresh_report()
            value = json.dumps(sanitize_report_for_copy(report_payload()), ensure_ascii=False, indent=2)
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
            self.status_var.set("Diagnostic report copied")

        def open_log_folder() -> None:
            try:
                self.diagnostics.root.mkdir(parents=True, exist_ok=True)
                os.startfile(self.diagnostics.root)  # type: ignore[attr-defined]
            except OSError as exc:
                messagebox.showerror(APP_NAME, f"The log folder is unavailable:\n{exc}")

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="Refresh", command=refresh_report).pack(side="left")
        ttk.Button(buttons, text="Copy report", command=copy_report).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Open log folder", command=open_log_folder).pack(side="right")
        refresh_report()

    def append_log(self, text: str) -> None:
        safe = redact_diagnostic_line(text.rstrip())
        self.recent_log.append(safe)
        self.diagnostics.append(safe)
        self.record_state()
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_url(self) -> None:
        self.url_var.set("")
        self.url_entry.focus_set()

    def _configure_url_entry_actions(self) -> None:
        self.url_context_menu = tk.Menu(self.root, tearoff=False)
        self.url_context_menu.add_command(label="Cut", command=lambda: self.url_entry.event_generate("<<Cut>>"))
        self.url_context_menu.add_command(label="Copy", command=lambda: self.url_entry.event_generate("<<Copy>>"))
        self.url_context_menu.add_command(label="Paste", command=self.paste_url_at_cursor)
        self.url_context_menu.add_separator()
        self.url_context_menu.add_command(label="Select all", command=self.select_all_url)
        self.url_entry.bind("<Control-KeyPress>", self._on_url_paste_shortcut, add="+")
        self.url_entry.bind("<Shift-Insert>", self._on_url_paste_shortcut, add="+")
        self.url_entry.bind("<Button-3>", self._show_url_context_menu, add="+")
        self.url_entry.bind("<Shift-F10>", self._show_url_context_menu, add="+")

    def _url_entry_selection(self) -> tuple[int, int] | None:
        try:
            return int(self.url_entry.index("sel.first")), int(self.url_entry.index("sel.last"))
        except tk.TclError:
            return None

    def _on_url_paste_shortcut(self, event: tk.Event[tk.Misc]) -> str | None:
        if not is_url_paste_shortcut(event.keysym, event.keycode, event.state):
            return None
        self.paste_url_at_cursor()
        return "break"

    def _show_url_context_menu(self, event: tk.Event[tk.Misc]) -> str:
        self.url_entry.focus_set()
        selection_present = self._url_entry_selection() is not None
        editable = str(self.url_entry.cget("state")) not in {"disabled", "readonly"}
        try:
            clipboard_present = isinstance(self.root.clipboard_get(), str)
        except tk.TclError:
            clipboard_present = False
        self.url_context_menu.entryconfigure(0, state="normal" if editable and selection_present else "disabled")
        self.url_context_menu.entryconfigure(1, state="normal" if selection_present else "disabled")
        self.url_context_menu.entryconfigure(2, state="normal" if editable and clipboard_present else "disabled")
        self.url_context_menu.entryconfigure(4, state="normal" if self.url_entry.get() else "disabled")
        x_root = event.x_root or self.url_entry.winfo_rootx() + 16
        y_root = event.y_root or self.url_entry.winfo_rooty() + self.url_entry.winfo_height()
        try:
            self.url_context_menu.tk_popup(x_root, y_root)
        finally:
            self.url_context_menu.grab_release()
        return "break"

    def select_all_url(self) -> None:
        self.url_entry.focus_set()
        self.url_entry.selection_range(0, "end")
        self.url_entry.icursor("end")

    def toggle_advanced(self) -> None:
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_frame.grid()
            self.advanced_button.configure(text="▾ Advanced options")
            self._fit_visible_content()
        else:
            self.advanced_frame.grid_remove()
            self.advanced_button.configure(text="▸ Advanced options")

    def toggle_details(self) -> None:
        self.open_diagnostics()

    def _fit_visible_content(self) -> None:
        self.root.update_idletasks()
        width = max(self.root.winfo_width(), 880)
        requested = self.root.winfo_reqheight() + 24
        available = max(640, self.root.winfo_screenheight() - 90)
        height = min(max(self.root.winfo_height(), requested), available)
        self.root.geometry(f"{width}x{height}")

    def _set_option_state(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for widget in (self.url_entry, self.paste_button, self.clear_button, self.folder_entry, self.folder_button, self.advanced_button, self.single_video_check):
            widget.configure(state=state)
        combo_state = "disabled" if busy else "readonly"
        self.media_combo.configure(state=combo_state)
        self.container_combo.configure(state=combo_state)
        self.cookies_combo.configure(state=combo_state)
        self.cookies_profile_combo.configure(state=combo_state if self._selected_cookie_browser() else "disabled")
        self.cookies_file_entry.configure(state="disabled" if busy or self.cookies_browser_var.get() != COOKIE_FILE_LABEL else "normal")
        self.cookies_file_button.configure(state="disabled" if busy or self.cookies_browser_var.get() != COOKIE_FILE_LABEL else "normal")
        if busy or self.media_type_var.get() == MEDIA_AUDIO_LABEL:
            self.quality_combo.configure(state="disabled")
        else:
            self.quality_combo.configure(state="readonly")
        self._refresh_auth_controls()

    def _set_busy_state(self, busy: bool) -> None:
        self.busy = busy
        self.download_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self._set_option_state(busy)

    def _show_result(
        self,
        message: str,
        *,
        error: bool = False,
        allow_open: bool = False,
        auth_recovery: bool = False,
    ) -> None:
        self.result_var.set(message)
        self.result_label.configure(style="Error.TLabel" if error else "Result.TLabel")
        if auth_recovery:
            self.auth_recovery_button.grid()
        else:
            self.auth_recovery_button.grid_remove()
        if allow_open:
            self.open_file_button.grid()
        else:
            self.open_file_button.grid_remove()
        self.result_frame.grid()

    def _paste_url_from_clipboard(self, *, replace_all: bool, notify_empty: bool) -> bool:
        try:
            value = self.root.clipboard_get()
        except tk.TclError:
            if notify_empty:
                messagebox.showinfo(APP_NAME, "The clipboard does not contain text.")
            return False
        if replace_all:
            value = value.strip()
        updated, cursor = compose_url_paste(
            self.url_entry.get(),
            value,
            int(self.url_entry.index("insert")),
            self._url_entry_selection(),
            replace_all=replace_all,
        )
        self.url_var.set(updated)
        self.url_entry.icursor(cursor)
        self.url_entry.selection_clear()
        self.url_entry.focus_set()
        return True

    def paste_url(self) -> None:
        """Button action: replace the complete URL field with trimmed clipboard text."""
        self._paste_url_from_clipboard(replace_all=True, notify_empty=True)

    def paste_url_at_cursor(self) -> None:
        """Keyboard/context-menu action: use native insert-or-replace-selection semantics."""
        self._paste_url_from_clipboard(replace_all=False, notify_empty=False)

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.folder_var.get() or str(default_download_folder()))
        if selected:
            self.folder_var.set(selected)

    def choose_cookies_file(self) -> bool:
        selected = filedialog.askopenfilename(
            title="Select a Netscape cookies.txt file",
            filetypes=(("Netscape cookies", "*.txt"), ("All files", "*.*")),
        )
        if not selected:
            return False
        self.cookies_file_var.set(selected)
        service, _media_id = media_identity(self.url_var.get())
        validation = validate_cookies_file(selected, service)
        self.cookie_hint_var.set(str(validation.get("warning") or validation.get("message")))
        return True

    def use_cookies_file(self) -> None:
        if not self.choose_cookies_file():
            return
        self.cookies_browser_var.set(COOKIE_FILE_LABEL)
        self._refresh_auth_controls()
        if not self.advanced_visible:
            self.toggle_advanced()

    def open_cookie_export_help(self) -> None:
        try:
            opened = webbrowser.open(COOKIE_EXPORT_HELP_URL, new=2)
        except (OSError, webbrowser.Error):
            opened = False
        if not opened:
            messagebox.showerror(APP_NAME, "Could not open the cookie export guide in your browser.")
            return
        self.diagnostics.append("Opened the yt-dlp cookie export guide.")

    def _selected_cookie_browser(self) -> str | None:
        return COOKIE_BROWSERS.get(self.cookies_browser_var.get())

    def _selected_browser_profile(self) -> str | None:
        return self.profile_values.get(self.cookies_profile_var.get())

    def _refresh_auth_controls(self) -> None:
        source = self.cookies_browser_var.get()
        browser = self._selected_cookie_browser()
        file_mode = source == COOKIE_FILE_LABEL

        if browser:
            profiles = discover_browser_profiles(browser)
            self.profile_values = {label: value for label, value in profiles}
            self.cookies_profile_combo.configure(values=tuple(self.profile_values))
            if self.cookies_profile_var.get() not in self.profile_values:
                self.cookies_profile_var.set(COOKIE_PROFILE_AUTO)
            self.cookies_profile_label.grid()
            self.cookies_profile_combo.grid()
            self.cookies_file_label.grid_remove()
            self.cookies_file_entry.grid_remove()
            self.cookies_file_button.grid_remove()
            executable = find_browser_executable(browser)
            self.open_login_button.configure(
                text="Open sign-in page",
                command=self.open_auth_page,
                state="disabled" if self.busy or not executable else "normal",
            )
            if not executable and not (browser_user_data_root(browser) and browser_user_data_root(browser).exists()):
                self.cookie_hint_var.set("This browser was not found on this computer. Choose cookies.txt or another browser.")
            elif browser in CHROMIUM_COOKIE_BROWSERS:
                self.cookie_hint_var.set(
                    "TubePort reads the selected profile through yt-dlp. If the database is locked, close the browser; "
                    "if Windows prevents access to DPAPI-protected v20 cookies, use cookies.txt."
                )
            else:
                self.cookie_hint_var.set("Select a profile that is already signed in. TubePort never asks for your password.")
        elif file_mode:
            self.cookies_profile_label.grid_remove()
            self.cookies_profile_combo.grid_remove()
            self.cookies_file_label.grid()
            self.cookies_file_entry.grid()
            self.cookies_file_button.grid()
            self.open_login_button.configure(
                text="Export help",
                command=self.open_cookie_export_help,
                state="disabled" if self.busy else "normal",
            )
            self.cookie_hint_var.set(
                "Use a fresh Netscape cookies.txt export. The file is used only for this run and is not copied by TubePort. "
                "Protect it like a password."
            )
        else:
            self.cookies_profile_label.grid_remove()
            self.cookies_profile_combo.grid_remove()
            self.cookies_file_label.grid_remove()
            self.cookies_file_entry.grid_remove()
            self.cookies_file_button.grid_remove()
            self.open_login_button.configure(text="Open sign-in page", command=self.open_auth_page, state="disabled")
            self.cookie_hint_var.set("Public media usually does not require authentication.")

    def open_auth_page(self) -> None:
        browser = self._selected_cookie_browser()
        if not browser:
            messagebox.showinfo(APP_NAME, "Select a browser for authentication first.")
            return
        profile = self._selected_browser_profile()
        service, _media_id = media_identity(self.url_var.get())
        login_url = (
            "https://www.instagram.com/accounts/login/"
            if service == "instagram"
            else "https://accounts.google.com/ServiceLogin?service=youtube"
        )
        command = build_browser_launch_command(browser, profile, login_url)
        if not command:
            messagebox.showerror(APP_NAME, "The selected browser was not found on this computer.")
            return
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.append_log(f"Sign-in page opened: browser={browser}; profile={profile or 'auto'}")
            self.record_state(
                force=True,
                phase="auth_page_opened",
                cookies_browser=browser,
                browser_profile=profile or "auto",
                message="Sign-in page opened in the external browser",
            )
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not open the browser:\n{exc}")

    def on_cookie_browser_changed(self, _event: object = None) -> None:
        self._refresh_auth_controls()
        if self.cookies_browser_var.get() == COOKIE_NONE_LABEL or self.cookie_notice_shown:
            return
        self.cookie_notice_shown = True
        messagebox.showinfo(
            APP_NAME,
            "TubePort never asks for or stores your username or password. It uses an already signed-in browser profile "
            "or a Netscape cookies.txt file you select.\n\n"
            "On Windows, Chromium-based browsers may lock their database while running or protect v20 cookies through DPAPI. "
            "Diagnostics distinguishes these cases.",
        )

    def on_media_type_changed(self, _event: object = None) -> None:
        if self.media_type_var.get() == MEDIA_AUDIO_LABEL:
            self.container_combo.configure(values=AUDIO_FORMATS)
            self.container_var.set("MP3")
            self.quality_combo.configure(state="disabled")
        else:
            self.container_combo.configure(values=VIDEO_FORMATS)
            self.container_var.set("MP4")
            self.quality_combo.configure(state="readonly")

    def _fail_preflight(
        self,
        error_kind: str,
        message: str,
        service: str | None,
        media_id: str | None,
        **details: object,
    ) -> None:
        self.detected_error_kind = error_kind
        self.last_error_line = None
        self.status_var.set("Authentication check found a problem")
        self.append_log(f"Preflight check: {error_kind}: {message}")
        self.record_state(
            force=True,
            phase="failed",
            service=service,
            media_id=media_id,
            video_id=media_id if service == "youtube" else None,
            instagram_shortcode=media_id if service == "instagram" else None,
            exit_code=None,
            error_kind=error_kind,
            last_error_line=None,
            message=message,
            **details,
        )
        self._show_result(message, error=True)
        messagebox.showerror(APP_NAME, message)

    def start_download(self) -> None:
        if self.busy:
            return

        self._reset_attempt_diagnostics()

        url = self.url_var.get().strip()
        if not is_supported_url(url):
            messagebox.showerror(APP_NAME, "Enter a valid YouTube or Instagram Reel link.")
            return
        if not self.yt_dlp:
            messagebox.showerror(
                APP_NAME,
                "yt-dlp was not found. Run Setup-Tools.cmd in the TubePort folder, then restart the application.",
            )
            return

        service, media_id = media_identity(url)
        media_type = "audio" if self.media_type_var.get() == MEDIA_AUDIO_LABEL else "video"
        if not self.ffmpeg and (media_type == "audio" or self.container_var.get() in VIDEO_FORMATS):
            messagebox.showerror(
                APP_NAME,
                "ffmpeg was not found. Run Setup-Tools.cmd in the TubePort folder, then restart the application.",
            )
            return

        auth_source = self.cookies_browser_var.get()
        selected_browser = self._selected_cookie_browser()
        selected_profile = self._selected_browser_profile() if selected_browser else None
        selected_cookies_file: Path | None = None
        browser_process_detected = False
        if auth_source == COOKIE_FILE_LABEL:
            validation = validate_cookies_file(self.cookies_file_var.get(), service)
            if not validation.get("ok"):
                self._fail_preflight(
                    "cookies_file_invalid",
                    str(validation.get("message")),
                    service,
                    media_id,
                    cookies_file=validation.get("file_name"),
                )
                return
            warning = validation.get("warning")
            if warning and not messagebox.askyesno(APP_NAME, f"{warning}\n\nContinue anyway?"):
                return
            selected_cookies_file = Path(self.cookies_file_var.get()).expanduser().resolve()
        elif selected_browser:
            root = browser_user_data_root(selected_browser)
            if not find_browser_executable(selected_browser) and not (root and root.exists()):
                self._fail_preflight(
                    "browser_profile_missing",
                    "The selected browser or profile was not found on this computer.",
                    service,
                    media_id,
                    cookies_browser=selected_browser,
                    browser_profile=selected_profile or "auto",
                )
                return
            browser_process_detected, advisory = browser_cookie_process_advisory(selected_browser)
            if advisory:
                self.append_log(f"Authentication note: {advisory}")

        folder_text = self.folder_var.get().strip()
        if not folder_text:
            messagebox.showerror(APP_NAME, "Choose a save folder.")
            return
        folder = Path(folder_text).expanduser()
        if not folder.is_absolute():
            messagebox.showerror(APP_NAME, "Enter a full path for the save folder.")
            return
        temp_folder = preferred_temp_folder()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            temp_folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not create the save folder:\n{exc}")
            return

        self.active_cookie_browser = selected_browser
        self.active_browser_profile = selected_profile
        self.active_cookies_file = selected_cookies_file
        command = build_download_command(
            yt_dlp=self.yt_dlp,
            ffmpeg=self.ffmpeg,
            url=url,
            output_folder=folder,
            temp_folder=temp_folder,
            media_type=media_type,
            quality=self.quality_var.get(),
            container=self.container_var.get(),
            single_video=self.single_video_var.get(),
            cookies_browser=self.active_cookie_browser,
            browser_profile=self.active_browser_profile,
            cookies_file=self.active_cookies_file,
            js_runtime=self.js_runtime,
        )

        self.last_result = None
        self.busy = True
        self.cancel_requested = False
        self.progress_var.set(0)
        self.display_progress = 0.0
        self.percent_label.configure(text="0%")
        self.status_var.set("Preparing…")
        self.result_frame.grid_remove()
        self._set_busy_state(True)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.record_state(
            force=True,
            phase="starting",
            service=service,
            media_id=media_id,
            video_id=media_id if service == "youtube" else None,
            instagram_shortcode=media_id if service == "instagram" else None,
            media_type=media_type,
            quality=self.quality_var.get(),
            container=self.container_var.get(),
            auth_source="cookies_file" if self.active_cookies_file else ("browser" if self.active_cookie_browser else "none"),
            cookies_browser=self.active_cookie_browser or "none",
            browser_profile=self.active_browser_profile or "auto",
            browser_process_detected=browser_process_detected,
            cookies_file=self.active_cookies_file.name if self.active_cookies_file else None,
            output_folder=str(folder),
            temp_folder=str(temp_folder),
            progress=0.0,
            title=None,
            speed=None,
            eta=None,
            result_path=None,
            exit_code=None,
            error_kind=None,
            message="Starting yt-dlp",
        )
        self.append_log("Starting yt-dlp…")

        threading.Thread(target=self._download_worker, args=(command, media_type), daemon=True).start()

    def _reset_attempt_diagnostics(self) -> None:
        self.detected_error_kind = None
        self.last_error_line = None
        self.recent_log.clear()
        self.record_state(
            force=True,
            phase="validating",
            service=None,
            media_id=None,
            video_id=None,
            instagram_shortcode=None,
            auth_source="none",
            cookies_browser="none",
            browser_profile="auto",
            browser_process_detected=False,
            cookies_file=None,
            media_type=None,
            quality=None,
            container=None,
            output_folder=None,
            temp_folder=None,
            progress=0.0,
            title=None,
            speed=None,
            eta=None,
            result_path=None,
            exit_code=None,
            error_kind=None,
            last_error_line=None,
            message="Validating download request",
        )

    def _download_worker(self, command: list[str], media_type: str) -> None:
        try:
            if self.cancel_requested:
                self.events.put(("done", -2))
                return
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
            if self.cancel_requested:
                self._terminate_process(self.process)
            assert self.process.stdout is not None
            for raw_line in self.process.stdout:
                line = raw_line.rstrip("\r\n")
                classified = classify_diagnostic_error(line)
                if classified and classified != "probe_error":
                    if error_kind_priority(classified) >= error_kind_priority(self.detected_error_kind):
                        self.detected_error_kind = classified
                        self.last_error_line = redact_diagnostic_line(line)
                if line.startswith("PROGRESS|"):
                    parts = line.split("|", 5)
                    percent_text = parts[1].strip() if len(parts) > 1 else "0%"
                    speed = parts[2].strip() if len(parts) > 2 else ""
                    eta = parts[3].strip() if len(parts) > 3 else ""
                    vcodec = parts[4].strip().lower() if len(parts) > 4 else ""
                    acodec = parts[5].strip().lower() if len(parts) > 5 else ""
                    match = re.search(r"([\d.]+)", percent_text)
                    percent = float(match.group(1)) if match else 0.0
                    if media_type == "video" and vcodec not in {"", "none", "na"} and acodec in {"", "none", "na"}:
                        percent *= 0.92
                    elif media_type == "video" and vcodec in {"", "none", "na"} and acodec not in {"", "none", "na"}:
                        percent = 92.0 + percent * 0.08
                    self.events.put(("progress", (percent, speed, eta)))
                elif line.startswith("TITLE:"):
                    self.events.put(("title", line[6:].strip()))
                elif line.startswith("RESULT:"):
                    result = line[7:].strip()
                    self.last_result = Path(result)
                    self.events.put(("log", f"Saved: {result}"))
                elif line:
                    if line.startswith(("[Merger]", "[ExtractAudio]", "[VideoRemuxer]", "[Metadata]")):
                        self.events.put(("processing", None))
                    self.events.put(("log", line))

            return_code = self.process.wait()
            self.events.put(("done", -2 if self.cancel_requested else return_code))
        except Exception as exc:  # GUI must report failures instead of crashing silently.
            self.events.put(("error", str(exc)))
        finally:
            self.process = None

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "log":
                    self.append_log(str(payload))
                elif event == "title":
                    full_title = str(payload)
                    visible_title = full_title if len(full_title) <= 72 else full_title[:69].rstrip() + "…"
                    self.status_var.set(f"Downloading: {visible_title}")
                    self.append_log(f"Title: {payload}")
                    self.record_state(force=True, phase="downloading", title=full_title, message="Title received")
                elif event == "progress":
                    percent, speed, eta = payload  # type: ignore[misc]
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                    self.display_progress = min(99.0, max(self.display_progress, float(percent)))
                    self.progress_var.set(self.display_progress)
                    self.percent_label.configure(text=f"{self.display_progress:.1f}%")
                    details = " • ".join(item for item in (speed, f"ETA {eta}" if eta else "") if item)
                    self.status_var.set(f"Downloading{': ' + details if details else '…'}")
                    self.record_state(phase="downloading", progress=round(self.display_progress, 2), speed=speed, eta=eta, message="Downloading")
                elif event == "processing":
                    self.status_var.set("Processing file…")
                    self.display_progress = max(self.display_progress, 98.0)
                    self.progress_var.set(self.display_progress)
                    self.percent_label.configure(text="processing")
                    self.progress.configure(mode="indeterminate")
                    self.progress.start(12)
                    self.record_state(force=True, phase="processing", progress=round(self.display_progress, 2), message="Processing file")
                elif event == "done":
                    self._finish_download(int(payload))
                elif event == "error":
                    self._finish_download(-1, str(payload))
                elif event == "cancel_failed":
                    self.status_var.set("Could not stop the process")
                    self.append_log(f"Cancellation error: {payload}")
                    self.record_state(force=True, phase="cancellation_failed", error_kind="cancel_failed", message=str(payload))
                    if self.process is not None and self.process.poll() is None:
                        self.cancel_button.configure(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _finish_download(self, return_code: int, error: str | None = None) -> None:
        self.busy = False
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self._set_busy_state(False)
        if return_code == 0:
            self.progress_var.set(100)
            self.percent_label.configure(text="100%")
            self.status_var.set("Done")
            self.record_state(
                force=True,
                phase="completed",
                progress=100.0,
                result_path=str(self.last_result) if self.last_result else None,
                exit_code=0,
                error_kind=None,
                message="Download completed",
            )
            result_name = self.last_result.name if self.last_result else "File saved"
            if len(result_name) > 74:
                result_name = result_name[:71].rstrip() + "…"
            self._show_result(f"✓ Done: {result_name}", allow_open=bool(self.last_result))
        elif return_code == -2:
            self.status_var.set("Canceled")
            self.append_log("Download canceled by the user.")
            self.record_state(force=True, phase="cancelled", exit_code=-2, error_kind="cancelled", message="Canceled by the user")
            self._show_result("Download canceled.", error=True)
        else:
            error_kind = self.detected_error_kind or "download_error"
            status_by_kind = {
                "browser_database_locked": "Could not access browser cookie database",
                "chromium_app_bound_encryption": "Cookies are protected by Windows",
                "browser_profile_missing": "Browser profile not found",
                "cookies_file_invalid": "cookies.txt was rejected",
                "authentication_required": "Authentication required",
                "video_unavailable": "Media unavailable",
            }
            self.status_var.set(status_by_kind.get(error_kind, "Error"))
            if error:
                self.append_log(f"Launch error: {error}")
            self.record_state(
                force=True,
                phase="failed",
                exit_code=return_code,
                error_kind=error_kind,
                last_error_line=self.last_error_line,
                message=error or self.last_error_line or self.status_var.get(),
            )
            visible_error = diagnostic_error_message(
                error_kind,
                has_browser=bool(self.active_cookie_browser),
                has_cookies_file=bool(self.active_cookies_file),
            )
            self._show_result(
                visible_error,
                error=True,
                auth_recovery=error_kind in {
                    "browser_database_locked",
                    "chromium_app_bound_encryption",
                    "authentication_required",
                },
            )
        if self.close_after_cancel:
            self.root.after(50, self._close_when_process_stops)

    def _close_when_process_stops(self) -> None:
        if self.process is None or self.process.poll() is not None:
            self.root.destroy()
        else:
            self.root.after(100, self._close_when_process_stops)

    def cancel_download(self) -> None:
        self.cancel_requested = True
        process = self.process
        if process is None:
            return
        self.status_var.set("Canceling…")
        self.cancel_button.configure(state="disabled")
        threading.Thread(target=self._cancel_worker, args=(process,), daemon=False).start()

    def _cancel_worker(self, process: subprocess.Popen[str]) -> None:
        try:
            if not self._terminate_process(process):
                self.events.put(("cancel_failed", "Could not stop the yt-dlp/ffmpeg process."))
        except (OSError, subprocess.SubprocessError) as exc:
            self.events.put(("cancel_failed", str(exc)))

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> bool:
        if process.poll() is not None:
            return True
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                    check=False,
                    timeout=8,
                )
            except subprocess.TimeoutExpired:
                pass
        else:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                return False
        return process.poll() is not None

    def open_result_file(self) -> None:
        if not self.last_result or not self.last_result.exists():
            messagebox.showerror(APP_NAME, "The downloaded file was not found.")
            return
        try:
            if os.name == "nt":
                os.startfile(self.last_result)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(self.last_result)])
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not open the file:\n{exc}")

    def open_result_folder(self) -> None:
        target = self.last_result.parent if self.last_result and self.last_result.exists() else Path(self.folder_var.get())
        if not target.exists():
            messagebox.showerror(APP_NAME, "The folder does not exist yet.")
            return
        try:
            if os.name == "nt":
                os.startfile(target)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not open the folder:\n{exc}")

    def on_close(self) -> None:
        if self.busy:
            if not messagebox.askyesno(APP_NAME, "A download is still running. Stop it and close the application?"):
                return
            self.close_after_cancel = True
            self.record_state(
                force=True,
                phase="closing",
                error_kind="cancel_requested",
                message="Window is closing; download cancellation requested",
            )
            self.cancel_download()
            return
        self.root.destroy()


def url_input_self_test(report_file: str | None = None) -> int:
    shortcut_checks = {
        "ctrl_v_english": is_url_paste_shortcut("v", WINDOWS_VIRTUAL_KEY_V, TK_CONTROL_MASK, "nt"),
        "ctrl_v_russian_layout": is_url_paste_shortcut("Cyrillic_em", WINDOWS_VIRTUAL_KEY_V, TK_CONTROL_MASK, "nt"),
        "shift_insert": is_url_paste_shortcut("Insert", 45, TK_SHIFT_MASK, "nt"),
        "ctrl_c_rejected": not is_url_paste_shortcut("c", 67, TK_CONTROL_MASK, "nt"),
        "plain_v_rejected": not is_url_paste_shortcut("v", WINDOWS_VIRTUAL_KEY_V, 0, "nt"),
        "physical_vk_windows_only": not is_url_paste_shortcut("Cyrillic_em", WINDOWS_VIRTUAL_KEY_V, TK_CONTROL_MASK, "posix"),
    }
    paste_checks = {
        "insert_at_cursor": compose_url_paste("abcd", "XY", 2) == ("abXYcd", 4),
        "replace_selection": compose_url_paste("abcdef", "XY", 2, (1, 4)) == ("aXYef", 3),
        "button_replaces_all": compose_url_paste("old", " new ".strip(), 1, (0, 2), replace_all=True) == ("new", 3),
    }
    ok = all(shortcut_checks.values()) and all(paste_checks.values())
    result = {
        "schema": 1,
        "app_version": APP_VERSION,
        "shortcut_checks": shortcut_checks,
        "paste_checks": paste_checks,
        "ok": ok,
    }
    emit_json(result, report_file)
    return 0 if ok else 1


def self_test(report_file: str | None = None) -> int:
    yt_dlp = find_executable("yt-dlp")
    ffmpeg = find_executable("ffmpeg")
    js_runtime = find_js_runtime()
    command = None
    if yt_dlp:
        command = build_download_command(
            yt_dlp=yt_dlp,
            ffmpeg=ffmpeg,
            url="https://www.youtube.com/watch?v=8KB0HvvXIN0",
            output_folder=default_download_folder(),
            temp_folder=preferred_temp_folder(),
            media_type="video",
            quality="1080p",
            container="MP4",
            cookies_browser=None,
            js_runtime=js_runtime,
        )
    common = {
        "yt_dlp": yt_dlp or "yt-dlp.exe",
        "ffmpeg": ffmpeg or "ffmpeg.exe",
        "url": "https://www.instagram.com/reel/DX1X9dBC_3Z/",
        "output_folder": default_download_folder(),
        "temp_folder": preferred_temp_folder(),
        "media_type": "video",
        "quality": "720p",
        "container": "MP4",
        "js_runtime": js_runtime,
    }
    profile_command = build_download_command(**common, cookies_browser="chrome", browser_profile="Profile 2")
    cookies_file_command = build_download_command(**common, cookies_file=Path("cookies.txt"))
    mutual_exclusion_rejected = False
    try:
        build_download_command(**common, cookies_browser="edge", cookies_file=Path("cookies.txt"))
    except ValueError:
        mutual_exclusion_rejected = True
    auth_contract = {
        "supported_browsers": SUPPORTED_COOKIE_BROWSERS == frozenset({"brave", "chrome", "chromium", "edge", "firefox", "opera", "vivaldi", "whale"}),
        "profile_argument": "chrome:Profile 2" in profile_command,
        "cookies_file_argument": "--cookies" in cookies_file_command,
        "mutual_exclusion": mutual_exclusion_rejected,
        "classify_locked": classify_diagnostic_error("ERROR: Could not copy Chrome cookie database") == "browser_database_locked",
        "classify_app_bound": classify_diagnostic_error("ERROR: Failed to decrypt with DPAPI") == "chromium_app_bound_encryption",
        "classify_profile": classify_diagnostic_error("Could not find Chrome cookies database in profile") == "browser_profile_missing",
        "classify_file": classify_diagnostic_error("cookies.txt invalid Netscape format") == "cookies_file_invalid",
        "youtube_url": bool(parse_media_url("https://www.youtube.com/watch?v=8KB0HvvXIN0")),
        "instagram_url": bool(parse_media_url("https://www.instagram.com/reel/DX1X9dBC_3Z/")),
    }
    result = {
        "app_version": APP_VERSION,
        "python": sys.executable,
        "tkinter": tk.TkVersion,
        "yt_dlp": yt_dlp,
        "ffmpeg": ffmpeg,
        "js_runtime": js_runtime,
        "sample_command": command,
        "browser_inventory": discover_browser_inventory(),
        "auth_contract": auth_contract,
        "ok": bool(yt_dlp and ffmpeg and all(auth_contract.values())),
    }
    emit_json(result, report_file)
    return 0 if result["ok"] else 1


def ui_self_test(report_file: str | None = None) -> int:
    root = tk.Tk()
    root.withdraw()
    app = DownloaderApp(root, diagnostics_store=MemoryDiagnosticsStore())
    app.open_diagnostics()
    root.update_idletasks()
    diagnostic_windows = [child for child in root.winfo_children() if isinstance(child, tk.Toplevel)]
    diagnostic_state = app.diagnostics.read_state()
    result = {
        "title": root.title(),
        "window": root.geometry(),
        "yt_dlp": bool(app.yt_dlp),
        "ffmpeg": bool(app.ffmpeg),
        "js_runtime": app.js_runtime[0] if app.js_runtime else None,
        "diagnostics_window": len(diagnostic_windows) == 1,
        "diagnostics_state": diagnostic_state.get("phase"),
        "diagnostics_path": str(app.diagnostics.state_path),
        "ok": bool(app.yt_dlp and app.ffmpeg and len(diagnostic_windows) == 1),
    }
    root.destroy()
    emit_json(result, report_file)
    return 0 if result["ok"] else 1


def bundle_self_test(report_file: str | None = None) -> int:
    yt_dlp = find_executable("yt-dlp")
    ffmpeg = find_executable("ffmpeg")
    ffprobe = find_executable("ffprobe")
    js_runtime = find_js_runtime()
    tools: dict[str, dict[str, object]] = {
        "yt-dlp": command_version(yt_dlp, "--version"),
        "ffmpeg": command_version(ffmpeg, "-version"),
        "ffprobe": command_version(ffprobe, "-version"),
    }
    if js_runtime:
        tools[js_runtime[0]] = command_version(js_runtime[1], "--version")
    else:
        tools["javascript_runtime"] = command_version(None, "--version")

    tools_directory = (app_directory() / "tools").resolve()
    portable_paths = all(
        details.get("path") and Path(str(details["path"])).resolve().parent == tools_directory
        for details in tools.values()
    )
    docs = {
        name: (app_directory() / name).is_file()
        for name in ("README.html", "THIRD_PARTY_NOTICES.txt", "VERSIONS.json", "SHA256SUMS.txt")
    }
    integrity = verify_sha256_manifest(app_directory(), app_directory() / "SHA256SUMS.txt")
    inventory: dict[str, object] = {"path": str(app_directory() / "VERSIONS.json"), "hash_mismatches": [], "version_mismatches": [], "ok": False}
    try:
        inventory_payload = json.loads((app_directory() / "VERSIONS.json").read_text(encoding="utf-8-sig"))
        components = {str(item.get("name")): item for item in inventory_payload.get("components", []) if isinstance(item, dict)}
        expected_hashes: dict[str, str] = {}
        for component in components.values():
            artifact = component.get("artifact")
            if artifact and component.get("sha256"):
                expected_hashes[str(artifact).replace("\\", "/")] = str(component["sha256"]).upper()
            for artifact_item in component.get("artifacts", []):
                if isinstance(artifact_item, dict) and artifact_item.get("path") and artifact_item.get("sha256"):
                    expected_hashes[str(artifact_item["path"]).replace("\\", "/")] = str(artifact_item["sha256"]).upper()
        actual_hashes = {
            "tools/yt-dlp.exe": tools["yt-dlp"].get("sha256"),
            "tools/deno.exe": tools.get("deno", {}).get("sha256"),
            "tools/ffmpeg.exe": tools["ffmpeg"].get("sha256"),
            "tools/ffprobe.exe": tools["ffprobe"].get("sha256"),
        }
        hash_mismatches = [path for path, actual in actual_hashes.items() if not actual or expected_hashes.get(path) != actual]
        expected_versions = {
            "yt-dlp": str(components.get("yt-dlp", {}).get("version", "")),
            "deno": str(components.get("Deno", {}).get("version", "")),
            "ffmpeg": str(components.get("FFmpeg", {}).get("version", "")).split("-")[0],
            "ffprobe": str(components.get("FFmpeg", {}).get("version", "")).split("-")[0],
        }
        version_mismatches = [
            name for name, expected in expected_versions.items()
            if not expected or expected not in str(tools.get(name, {}).get("version", ""))
        ]
        inventory.update({
            "components": sorted(components),
            "verified_artifacts": len(actual_hashes),
            "hash_mismatches": hash_mismatches,
            "version_mismatches": version_mismatches,
            "ok": not hash_mismatches and not version_mismatches and len(actual_hashes) == 4,
        })
    except (OSError, json.JSONDecodeError, TypeError, AttributeError) as exc:
        inventory["error"] = str(exc)
    toolchain_ok = all(bool(details.get("present")) and details.get("exit_code") == 0 for details in tools.values())
    ok = bool(toolchain_ok and portable_paths and all(docs.values()) and integrity.get("ok") and inventory.get("ok"))
    result = {
        "schema": 1,
        "app": APP_NAME,
        "app_version": APP_VERSION,
        "tested_at": now_iso(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "architecture": platform.machine(),
        "windows": platform.platform(),
        "app_directory": str(app_directory()),
        "tools_directory": str(tools_directory),
        "portable_tool_paths": portable_paths,
        "tools": tools,
        "documentation": docs,
        "integrity": integrity,
        "versions_inventory": inventory,
        "ok": ok,
    }
    destination = report_file or str(diagnostics_root() / "bundle-self-test.json")
    emit_json(result, destination)
    return 0 if ok else 1


def ui_contract(report_file: str | None = None) -> int:
    root = tk.Tk()
    root.withdraw()
    app = DownloaderApp(root, diagnostics_store=MemoryDiagnosticsStore())
    root.update_idletasks()
    initial = {
        "title": root.title(),
        "geometry": root.geometry(),
        "advanced_visible": app.advanced_visible,
        "details_visible": app.details_visible,
        "media_type": app.media_type_var.get(),
        "quality": app.quality_var.get(),
        "container": app.container_var.get(),
        "cookie_sources": list(app.cookies_combo.cget("values")),
        "cookie_profile": app.cookies_profile_var.get(),
        "download_button": str(app.download_button.cget("text")),
        "cancel_state": str(app.cancel_button.cget("state")),
    }
    app.toggle_advanced()
    app.open_diagnostics()
    root.update_idletasks()
    diagnostic_windows = [child for child in root.winfo_children() if isinstance(child, tk.Toplevel)]
    geometry_after_toggle = root.geometry()
    geometry_match = re.match(r"(\d+)x(\d+)", geometry_after_toggle)
    geometry_width = int(geometry_match.group(1)) if geometry_match else 0
    geometry_height = int(geometry_match.group(2)) if geometry_match else 0
    toggled = {
        "advanced_visible": app.advanced_visible,
        "details_visible": app.details_visible,
        "diagnostics_windows": len(diagnostic_windows),
        "required_width": root.winfo_reqwidth(),
        "required_height": root.winfo_reqheight(),
        "window_geometry": geometry_after_toggle,
        "window_width": geometry_width,
        "window_height": geometry_height,
    }
    app._set_busy_state(True)
    busy_states = {
        "url": str(app.url_entry.cget("state")),
        "paste": str(app.paste_button.cget("state")),
        "clear": str(app.clear_button.cget("state")),
        "media": str(app.media_combo.cget("state")),
        "quality": str(app.quality_combo.cget("state")),
        "format": str(app.container_combo.cget("state")),
        "folder": str(app.folder_entry.cget("state")),
        "folder_button": str(app.folder_button.cget("state")),
        "advanced_button": str(app.advanced_button.cget("state")),
        "single_video": str(app.single_video_check.cget("state")),
        "cookies": str(app.cookies_combo.cget("state")),
        "download": str(app.download_button.cget("state")),
        "cancel": str(app.cancel_button.cget("state")),
    }
    app._set_busy_state(False)
    restored_states = {
        "url": str(app.url_entry.cget("state")),
        "paste": str(app.paste_button.cget("state")),
        "clear": str(app.clear_button.cget("state")),
        "media": str(app.media_combo.cget("state")),
        "quality": str(app.quality_combo.cget("state")),
        "format": str(app.container_combo.cget("state")),
        "folder": str(app.folder_entry.cget("state")),
        "folder_button": str(app.folder_button.cget("state")),
        "advanced_button": str(app.advanced_button.cget("state")),
        "single_video": str(app.single_video_check.cget("state")),
        "cookies": str(app.cookies_combo.cget("state")),
        "download": str(app.download_button.cget("state")),
        "cancel": str(app.cancel_button.cget("state")),
    }
    sample_command = build_download_command(
        yt_dlp=app.yt_dlp or "tools/yt-dlp.exe",
        ffmpeg=app.ffmpeg or "tools/ffmpeg.exe",
        url="https://www.youtube.com/watch?v=8KB0HvvXIN0",
        output_folder=default_download_folder(),
        temp_folder=preferred_temp_folder(),
        media_type="video",
        quality="1080p",
        container="MP4",
        js_runtime=app.js_runtime or ("deno", "tools/deno.exe"),
    )
    required_flags = ["--ignore-config", "--no-remote-components", "--no-js-runtimes", "--js-runtimes", "--ffmpeg-location", "--no-playlist"]
    profile_command = build_download_command(
        yt_dlp="tools/yt-dlp.exe",
        ffmpeg="tools/ffmpeg.exe",
        url="https://www.instagram.com/reel/DX1X9dBC_3Z/",
        output_folder=default_download_folder(),
        temp_folder=preferred_temp_folder(),
        media_type="video",
        quality="720p",
        container="MP4",
        cookies_browser="edge",
        browser_profile="Profile 2",
    )
    callbacks = {
        "paste": bool(str(app.paste_button.cget("command"))),
        "clear": bool(str(app.clear_button.cget("command"))),
        "download": bool(str(app.download_button.cget("command"))),
        "cancel": bool(str(app.cancel_button.cget("command"))),
        "open_folder": bool(str(app.open_button.cget("command"))),
        "open_file": bool(str(app.open_file_button.cget("command"))),
        "auth_recovery": bool(str(app.auth_recovery_button.cget("command"))),
        "diagnostics": bool(str(app.details_button.cget("command"))),
        "open_login": bool(str(app.open_login_button.cget("command"))),
        "choose_cookies_file": bool(str(app.cookies_file_button.cget("command"))),
    }
    process_detected, process_advisory = browser_cookie_process_advisory("chrome", detected=True)
    process_policy = {
        "presence_is_advisory": bool(
            process_detected
            and process_advisory
            and "does not prove" in process_advisory
        ),
        "dpapi_has_priority": (
            error_kind_priority("chromium_app_bound_encryption")
            > error_kind_priority("browser_database_locked")
        ),
    }
    app.detected_error_kind = "browser_database_locked"
    app.last_error_line = "stale error from a previous attempt"
    app.recent_log.append("stale log line")
    app.debug_state.update(
        {
            "phase": "failed",
            "auth_source": "browser",
            "browser_process_detected": True,
            "exit_code": 1,
            "error_kind": "authentication_required",
            "last_error_line": "stale persisted error",
            "result_path": "stale-result.mp4",
        }
    )
    app.record_state(force=True)
    app._reset_attempt_diagnostics()
    persisted_reset = app.diagnostics.read_state()
    state_hygiene = {
        "error_kind_cleared": app.detected_error_kind is None,
        "error_line_cleared": app.last_error_line is None,
        "recent_log_cleared": not app.recent_log,
        "persisted_phase_reset": persisted_reset.get("phase") == "validating",
        "persisted_error_cleared": persisted_reset.get("error_kind") is None,
        "persisted_error_line_cleared": persisted_reset.get("last_error_line") is None,
        "persisted_exit_code_cleared": persisted_reset.get("exit_code") is None,
        "persisted_result_cleared": persisted_reset.get("result_path") is None,
        "persisted_auth_reset": persisted_reset.get("auth_source") == "none",
        "persisted_process_reset": persisted_reset.get("browser_process_detected") is False,
    }

    original_file_dialog = filedialog.askopenfilename
    try:
        app.cookies_browser_var.set("Google Chrome")
        app.cookies_file_var.set("previous-cookies.txt")
        filedialog.askopenfilename = lambda **_kwargs: ""
        app.use_cookies_file()
        recovery_cancel = {
            "source_preserved": app.cookies_browser_var.get() == "Google Chrome",
            "path_preserved": app.cookies_file_var.get() == "previous-cookies.txt",
        }
        filedialog.askopenfilename = lambda **_kwargs: r"C:\selected-cookies.txt"
        app.use_cookies_file()
        recovery_success = {
            "source_changed_after_selection": app.cookies_browser_var.get() == COOKIE_FILE_LABEL,
            "path_changed_after_selection": app.cookies_file_var.get() == r"C:\selected-cookies.txt",
            "export_help_available": str(app.open_login_button.cget("text")) == "Export help",
        }
    finally:
        filedialog.askopenfilename = original_file_dialog
        app.cookies_browser_var.set(COOKIE_NONE_LABEL)
        app.cookies_file_var.set("")
        app._refresh_auth_controls()

    original_thread = threading.Thread
    original_find_browser = globals()["find_browser_executable"]
    original_process_check = globals()["browser_process_running"]
    worker_starts: list[object] = []

    class DeferredThread:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.target = kwargs.get("target") or (args[0] if args else None)

        def start(self) -> None:
            worker_starts.append(self.target)

    try:
        threading.Thread = DeferredThread  # type: ignore[assignment]
        globals()["find_browser_executable"] = lambda _browser: r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        globals()["browser_process_running"] = lambda _browser: True
        app.yt_dlp = "tools/yt-dlp.exe"
        app.ffmpeg = "tools/ffmpeg.exe"
        app.url_var.set("https://www.youtube.com/watch?v=8KB0HvvXIN0")
        app.folder_var.set(str(Path.cwd()))
        app.cookies_browser_var.set("Google Chrome")
        app._refresh_auth_controls()
        app.start_download()
        false_lock_regression = {
            "worker_started": len(worker_starts) == 1,
            "download_entered_busy_state": app.busy,
            "no_preflight_error": app.detected_error_kind is None,
            "phase_is_starting": app.debug_state.get("phase") == "starting",
            "process_recorded_as_advisory": app.debug_state.get("browser_process_detected") is True,
        }
    finally:
        threading.Thread = original_thread
        globals()["find_browser_executable"] = original_find_browser
        globals()["browser_process_running"] = original_process_check
        app.busy = False
        app._set_busy_state(False)
        app.cookies_browser_var.set(COOKIE_NONE_LABEL)
        app._refresh_auth_controls()
    url_actions = {
        "control_keypress": bool(app.url_entry.bind("<Control-KeyPress>")),
        "shift_insert": bool(app.url_entry.bind("<Shift-Insert>")),
        "right_click": bool(app.url_entry.bind("<Button-3>")),
        "context_menu_entries": int(app.url_context_menu.index("end")) + 1 == 5,
    }
    interface_strings: list[str] = [APP_TAGLINE, app.status_var.get()]

    def collect_interface_strings(widget: tk.Misc) -> None:
        for option in ("text", "values"):
            try:
                value = widget.cget(option)
            except tk.TclError:
                continue
            if isinstance(value, (tuple, list)):
                interface_strings.extend(str(item) for item in value)
            elif value:
                interface_strings.append(str(value))
        for child in widget.winfo_children():
            collect_interface_strings(child)

    collect_interface_strings(root)
    menu_labels: list[str] = []
    for index in range(int(app.url_context_menu.index("end")) + 1):
        try:
            label = str(app.url_context_menu.entrycget(index, "label"))
        except tk.TclError:
            continue
        if label:
            menu_labels.append(label)
            interface_strings.append(label)
    cyrillic_strings = sorted({value for value in interface_strings if re.search(r"[\u0400-\u052F]", value)})
    english_interface = {
        "media_type": initial["media_type"] == MEDIA_VIDEO_LABEL,
        "download_button": initial["download_button"] == "Download",
        "paste_button": str(app.paste_button.cget("text")) == "Paste",
        "advanced_button": str(app.advanced_button.cget("text")) == "▾ Advanced options",
        "cookie_sources": initial["cookie_sources"][0] == COOKIE_NONE_LABEL and initial["cookie_sources"][-1] == COOKIE_FILE_LABEL,
        "cookie_profile": initial["cookie_profile"] == COOKIE_PROFILE_AUTO,
        "context_menu": menu_labels == ["Cut", "Copy", "Paste", "Select all"],
        "diagnostics_title": bool(diagnostic_windows) and diagnostic_windows[0].title() == f"Diagnostics — {APP_NAME}",
        "no_cyrillic": not cyrillic_strings,
    }
    busy_options_ok = all(state == "disabled" for name, state in busy_states.items() if name != "cancel") and busy_states["cancel"] == "normal"
    restored_ok = all(state != "disabled" for name, state in restored_states.items() if name != "cancel") and restored_states["cancel"] == "disabled"
    result = {
        "schema": 1,
        "app_version": APP_VERSION,
        "initial": initial,
        "toggles": toggled,
        "busy_states": busy_states,
        "restored_states": restored_states,
        "required_flags": {flag: flag in sample_command for flag in required_flags},
        "profile_argument": "edge:Profile 2" in profile_command,
        "url_actions": url_actions,
        "english_interface": english_interface,
        "cyrillic_strings": cyrillic_strings,
        "callbacks": callbacks,
        "browser_process_policy": process_policy,
        "attempt_state_hygiene": state_hygiene,
        "cookies_file_recovery_cancel": recovery_cancel,
        "cookies_file_recovery_success": recovery_success,
        "false_lock_regression": false_lock_regression,
        "diagnostics_phase": app.diagnostics.read_state().get("phase"),
        "ok": (
            initial["title"] == APP_NAME
            and not initial["advanced_visible"]
            and not initial["details_visible"]
            and busy_options_ok
            and restored_ok
            and toggled["advanced_visible"] is True
            and toggled["details_visible"] is False
            and toggled["diagnostics_windows"] == 1
            and toggled["required_width"] <= 880
            and toggled["required_height"] <= toggled["window_height"]
            and all(flag in sample_command for flag in required_flags)
            and "edge:Profile 2" in profile_command
            and all(url_actions.values())
            and all(english_interface.values())
            and all(callbacks.values())
            and all(process_policy.values())
            and all(state_hygiene.values())
            and all(recovery_cancel.values())
            and all(recovery_success.values())
            and all(false_lock_regression.values())
        ),
    }
    root.destroy()
    destination = report_file or str(diagnostics_root() / "ui-contract.json")
    emit_json(result, destination)
    return 0 if result["ok"] else 1


def error_kind_priority(error_kind: str | None) -> int:
    return {
        "chromium_app_bound_encryption": 100,
        "browser_database_locked": 90,
        "cookies_file_invalid": 85,
        "browser_profile_missing": 80,
        "video_unavailable": 75,
        "authentication_required": 70,
        "unsupported_url": 60,
        "cookie_read_error": 50,
        "probe_error": 10,
    }.get(error_kind or "", 0)


def diagnostic_error_message(error_kind: str, *, has_browser: bool = False, has_cookies_file: bool = False) -> str:
    if error_kind == "browser_database_locked":
        return (
            "yt-dlp could not copy the browser cookie database. A browser or background process may be using it. "
            "Close that browser completely and retry; if the problem persists, use a fresh cookies.txt file."
        )
    if error_kind == "chromium_app_bound_encryption":
        return (
            "Chromium protected its v20 cookies with Windows App-Bound/DPAPI encryption. Closing the browser will not fix this: "
            "use a Netscape cookies.txt file or a Firefox profile."
        )
    if error_kind == "browser_profile_missing":
        return "The browser profile or its cookie database was not found. Select a profile that is signed in."
    if error_kind == "cookies_file_invalid":
        return "The file was rejected. Select a non-empty Netscape cookies.txt file with a valid header."
    if error_kind == "authentication_required":
        if has_browser:
            return "The service rejected the selected profile session. Sign in to that profile or use cookies.txt."
        if has_cookies_file:
            return "The service rejected cookies.txt. The session may have expired, or the file may not contain cookies for this site."
        return "Sign-in is required. Select a browser profile or cookies.txt under Advanced options."
    if error_kind == "video_unavailable":
        return "This media is unavailable to the selected account or has been removed."
    return "The download did not finish. Open the diagnostic report for the exact error code and last error line."


def classify_diagnostic_error(output: str) -> str | None:
    lowered = output.lower()
    if "failed to decrypt with dpapi" in lowered or "app-bound" in lowered or "app bound" in lowered:
        return "chromium_app_bound_encryption"
    if (
        ("could not copy" in lowered and "cookie" in lowered)
        or ("permission denied" in lowered and "cookie" in lowered)
        or ("database is locked" in lowered and "cookie" in lowered)
    ):
        return "browser_database_locked"
    if (
        ("could not find" in lowered and "cookie" in lowered and "database" in lowered)
        or ("profile" in lowered and "not found" in lowered and "cookie" in lowered)
        or "no such profile" in lowered
    ):
        return "browser_profile_missing"
    if (
        "does not look like a netscape format cookies file" in lowered
        or "invalid netscape" in lowered
        or ("cookies.txt" in lowered and ("invalid" in lowered or "not found" in lowered))
    ):
        return "cookies_file_invalid"
    if (
        "cookie database" in lowered
        or "cookies database" in lowered
        or "failed to decrypt" in lowered
    ):
        return "cookie_read_error"
    if (
        "sign in to confirm your age" in lowered
        or "sign in to confirm you're not a bot" in lowered
        or "use --cookies-from-browser" in lowered
        or "login required" in lowered
    ):
        return "authentication_required"
    if "video unavailable" in lowered or "private video" in lowered:
        return "video_unavailable"
    if "unsupported url" in lowered:
        return "unsupported_url"
    return "probe_error" if "error:" in lowered else None


def diagnostic_probe(
    url: str,
    report_file: str | None = None,
    cookies_browser: str | None = None,
    browser_profile: str | None = None,
    cookies_file: str | None = None,
) -> int:
    store = DiagnosticsStore(
        state_name=f"state-probe-{os.getpid()}-{time.time_ns()}.json",
        pointer_name="latest-probe.json",
        log_name="probe.log",
    )
    service, media_id = media_identity(url)
    if not is_supported_url(url):
        state = {
            "schema": 1,
            "app_version": APP_VERSION,
            "phase": "probe_failed",
            "updated_at": now_iso(),
            "service": service,
            "media_id": media_id,
            "video_id": media_id if service == "youtube" else None,
            "instagram_shortcode": media_id if service == "instagram" else None,
            "exit_code": None,
            "error_kind": "invalid_url",
            "message": "Invalid YouTube or Instagram link",
            "state_path": str(store.state_path),
            "log_path": str(store.log_path),
            "recent_log": [],
        }
        store.write_state(state)
        emit_json(state, report_file)
        return 2

    yt_dlp = find_executable("yt-dlp")
    ffmpeg = find_executable("ffmpeg")
    js_runtime = find_js_runtime()
    browser_process_detected, process_advisory = browser_cookie_process_advisory(cookies_browser)
    if cookies_file:
        validation = validate_cookies_file(cookies_file, service)
    else:
        validation = None
    if validation and not validation.get("ok"):
        output = f"cookies.txt invalid: {validation.get('message')}"
        return_code = 1
    elif not yt_dlp:
        output = "yt-dlp not found"
        return_code = -1
    else:
        command = build_download_command(
            yt_dlp=yt_dlp,
            ffmpeg=ffmpeg,
            url=url,
            output_folder=default_download_folder(),
            temp_folder=preferred_temp_folder(),
            media_type="video",
            quality="1080p",
            container="MP4",
            cookies_browser=cookies_browser,
            browser_profile=browser_profile,
            cookies_file=cookies_file,
            js_runtime=js_runtime,
        )
        command[-1:-1] = ["--simulate"]
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=90,
                check=False,
            )
            output = completed.stdout
            return_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            output += "\nDiagnostic probe timed out"
            return_code = -2

    lines = [redact_diagnostic_line(line) for line in output.splitlines() if line.strip()][-120:]
    recent_lines = ([process_advisory] if process_advisory else []) + lines
    recent_lines = recent_lines[-120:]
    for line in recent_lines:
        store.append(f"[probe] {line}")
    error_kind = classify_diagnostic_error(output)
    phase = "probe_completed" if return_code == 0 else "probe_failed"
    state = {
        "schema": 1,
        "app_version": APP_VERSION,
        "phase": phase,
        "updated_at": now_iso(),
        "service": service,
        "media_id": media_id,
        "video_id": media_id if service == "youtube" else None,
        "instagram_shortcode": media_id if service == "instagram" else None,
        "auth_source": "cookies_file" if cookies_file else ("browser" if cookies_browser else "none"),
        "cookies_browser": cookies_browser or "none",
        "browser_profile": browser_profile or "auto",
        "browser_process_detected": browser_process_detected,
        "cookies_file": Path(cookies_file).name if cookies_file else None,
        "exit_code": return_code,
        "error_kind": error_kind,
        "message": "Availability check completed" if return_code == 0 else "The check found an error",
        "tools": {"yt_dlp": yt_dlp, "ffmpeg": ffmpeg, "js_runtime": js_runtime},
        "state_path": str(store.state_path),
        "log_path": str(store.log_path),
        "recent_log": recent_lines,
    }
    store.write_state(state)
    emit_json(state, report_file)
    return 0 if return_code == 0 else 1


def headless_download_test(
    url: str,
    output_folder: str | None = None,
    report_file: str | None = None,
    cookies_browser: str | None = None,
    browser_profile: str | None = None,
    cookies_file: str | None = None,
) -> int:
    store = DiagnosticsStore(
        state_name=f"state-download-test-{os.getpid()}-{time.time_ns()}.json",
        pointer_name="latest-download-test.json",
        log_name="download-test.log",
    )
    yt_dlp = find_executable("yt-dlp")
    ffmpeg = find_executable("ffmpeg")
    ffprobe = find_executable("ffprobe")
    js_runtime = find_js_runtime()
    destination = Path(output_folder).expanduser().resolve() if output_folder else diagnostics_root().parent / "download-test"
    destination.mkdir(parents=True, exist_ok=True)
    result_path: Path | None = None
    output = ""
    return_code = -1
    probe_result: dict[str, object] | None = None

    service, media_id = media_identity(url)
    if not is_supported_url(url):
        output = "Invalid YouTube or Instagram URL"
        error_kind = "invalid_url"
    elif not yt_dlp or not ffmpeg or not ffprobe:
        output = "Portable toolchain is incomplete"
        error_kind = "missing_tool"
    else:
        command = build_download_command(
            yt_dlp=yt_dlp,
            ffmpeg=ffmpeg,
            url=url,
            output_folder=destination,
            temp_folder=destination / ".temp",
            media_type="video",
            quality="360p",
            container="MP4",
            cookies_browser=cookies_browser,
            browser_profile=browser_profile,
            cookies_file=cookies_file,
            js_runtime=js_runtime,
        )
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=600,
                check=False,
            )
            output = completed.stdout
            return_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            output += "\nHeadless download test timed out"
            return_code = -2
        for line in output.splitlines():
            if line.startswith("RESULT:"):
                result_path = Path(line[7:].strip())
        error_kind = classify_diagnostic_error(output)
        if return_code == 0 and result_path and result_path.is_file():
            probe = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration,size,format_name", "-of", "json", str(result_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=60,
                check=False,
            )
            try:
                probe_payload: object = json.loads(probe.stdout)
            except json.JSONDecodeError:
                probe_payload = probe.stdout.strip()
            probe_result = {"exit_code": probe.returncode, "data": probe_payload}

    lines = [redact_diagnostic_line(line) for line in output.splitlines() if line.strip()][-100:]
    for line in lines:
        store.append(f"[download-test] {line}")
    ok = bool(return_code == 0 and result_path and result_path.is_file() and probe_result and probe_result.get("exit_code") == 0)
    state = {
        "schema": 1,
        "app_version": APP_VERSION,
        "phase": "download_test_completed" if ok else "download_test_failed",
        "updated_at": now_iso(),
        "service": service,
        "media_id": media_id,
        "video_id": media_id if service == "youtube" else None,
        "instagram_shortcode": media_id if service == "instagram" else None,
        "auth_source": "cookies_file" if cookies_file else ("browser" if cookies_browser else "none"),
        "cookies_browser": cookies_browser or "none",
        "browser_profile": browser_profile or "auto",
        "cookies_file": Path(cookies_file).name if cookies_file else None,
        "exit_code": return_code,
        "error_kind": None if ok else (error_kind or "download_test_error"),
        "result_path": str(result_path) if result_path else None,
        "result_sha256": sha256_file(result_path) if result_path else None,
        "ffprobe": probe_result,
        "tools": {"yt_dlp": yt_dlp, "ffmpeg": ffmpeg, "ffprobe": ffprobe, "js_runtime": js_runtime},
        "state_path": str(store.state_path),
        "log_path": str(store.log_path),
        "recent_log": lines,
        "ok": ok,
    }
    store.write_state(state)
    emit_json(state, report_file or str(diagnostics_root() / "download-test-report.json"))
    return 0 if ok else 1


def print_diagnostics(target: str, report_file: str | None = None) -> int:
    if target == "app":
        result: object = read_diagnostic_pointer("latest-app.json")
    elif target == "probe":
        result = read_diagnostic_pointer("latest-probe.json")
    elif target == "terminal":
        result = read_diagnostic_file("last-terminal.json")
    else:
        result = {
            "current_app": read_diagnostic_pointer("latest-app.json"),
            "last_terminal": read_diagnostic_file("last-terminal.json"),
            "last_probe": read_diagnostic_pointer("latest-probe.json"),
            "recent_attempts": read_recent_attempts(),
        }
    emit_json(result, report_file)
    return 0


def main() -> int:
    configure_process_environment()
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass
    parser = argparse.ArgumentParser(prog=APP_NAME, description="Portable YouTube and Instagram media downloader")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--url-input-self-test", action="store_true")
    parser.add_argument("--ui-self-test", action="store_true")
    parser.add_argument("--bundle-self-test", action="store_true")
    parser.add_argument("--ui-contract", action="store_true")
    parser.add_argument("--diagnostics", nargs="?", const="app", choices=("app", "probe", "terminal", "all"))
    parser.add_argument("--debug-probe")
    parser.add_argument("--download-test")
    parser.add_argument("--test-output-folder")
    parser.add_argument("--report-file")
    auth_group = parser.add_mutually_exclusive_group()
    auth_group.add_argument("--cookies-browser", choices=tuple(sorted(SUPPORTED_COOKIE_BROWSERS)))
    auth_group.add_argument("--cookies-file")
    parser.add_argument("--browser-profile")
    args = parser.parse_args()
    if args.browser_profile and not args.cookies_browser:
        parser.error("--browser-profile requires --cookies-browser")
    if args.url_input_self_test:
        return url_input_self_test(args.report_file)
    if args.self_test:
        return self_test(args.report_file)
    if args.ui_self_test:
        return ui_self_test(args.report_file)
    if args.bundle_self_test:
        return bundle_self_test(args.report_file)
    if args.ui_contract:
        return ui_contract(args.report_file)
    if args.diagnostics:
        return print_diagnostics(args.diagnostics, args.report_file)
    if args.debug_probe:
        return diagnostic_probe(
            args.debug_probe,
            args.report_file,
            cookies_browser=args.cookies_browser,
            browser_profile=args.browser_profile,
            cookies_file=args.cookies_file,
        )
    if args.download_test:
        return headless_download_test(
            args.download_test,
            args.test_output_folder,
            args.report_file,
            cookies_browser=args.cookies_browser,
            browser_profile=args.browser_profile,
            cookies_file=args.cookies_file,
        )

    root = tk.Tk()
    DownloaderApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
