"""Standard Firefox backend (no automation).

Launches the Firefox installed on the computer with a DEDICATED profile
(profiles/standard-firefox/<role>-<provider>) via `-profile <dir> -no-remote
-new-instance`. The application never reads or controls the page: messages
move exclusively through the clipboard workflow. This is the integration to use
when a provider's terms or sign-in restrictions rule out automation.

The user's default Firefox profile is never used, read or modified.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

from adapters.errors import AdapterError, DependencyMissingError

from .window_manager import Geometry, Win32Windows, seed_profile_geometry


def find_firefox(custom_path: str = "") -> Path | None:
    if custom_path and Path(custom_path).is_file():
        return Path(custom_path)
    if sys.platform == "win32":
        try:
            import winreg
            for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe") as k:
                        val, _ = winreg.QueryValueEx(k, "")
                        if val and Path(val).is_file():
                            return Path(val)
                except OSError:
                    continue
        except ImportError:  # pragma: no cover
            pass
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
            cand = Path(base) / "Mozilla Firefox" / "firefox.exe"
            if cand.is_file():
                return cand
    elif sys.platform == "darwin":
        cand = Path("/Applications/Firefox.app/Contents/MacOS/firefox")
        if cand.is_file():
            return cand
    found = shutil.which("firefox")
    return Path(found) if found else None


class StandardFirefoxSession:
    backend = "standard"

    def __init__(self, role: str, provider_id: str, profile_dir: Path, firefox_path: str = "") -> None:
        self.role = role
        self.provider_id = provider_id
        self.profile_dir = profile_dir
        self.firefox_path = firefox_path
        self.proc: subprocess.Popen | None = None
        self.hwnd: int | None = None
        self._win = Win32Windows()

    async def start(self, url: str, geometry: Geometry | None) -> None:
        exe = find_firefox(self.firefox_path)
        if exe is None:
            raise DependencyMissingError("No installed Firefox found. Install Firefox, set its path in Settings, "
                                         "or use the Playwright-managed browser.")
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        if geometry:
            seed_profile_geometry(self.profile_dir, geometry)
        cmd = [str(exe), "-no-remote", "-new-instance", "-profile", str(self.profile_dir)]
        if url:
            cmd.append(url)
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise AdapterError(f"Could not start Firefox: {exc}") from exc
        if self._win.ok:
            self.hwnd = await asyncio.to_thread(self._win.wait_new_window, set(self._win.firefox_windows()),
                                                10.0, self.proc.pid)
            if self.hwnd and geometry:
                self._win.move(self.hwnd, geometry)

    def driver(self):
        return None  # no automation by design

    def is_closed(self) -> bool:
        return self.proc is None or self.proc.poll() is not None

    async def current_url(self) -> str:
        return ""

    async def focus(self) -> None:
        if self._win.ok and self.proc is not None:
            hwnd = self.hwnd if (self.hwnd and self._win.exists(self.hwnd)) else self._win.window_for_pid(self.proc.pid)
            if hwnd:
                self.hwnd = hwnd
                self._win.focus(hwnd)

    def geometry(self) -> Geometry | None:
        if self.hwnd and self._win.exists(self.hwnd):
            return self._win.rect(self.hwnd)
        return None

    async def close(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
