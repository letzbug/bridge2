"""Window layout, Firefox geometry persistence and (Windows-only) window positioning.

Two mechanisms, both best effort:

1. xulstore.json – Firefox stores the main window geometry per profile. Because
   every participant has its own dedicated profile, Firefox itself remembers
   window positions between launches. For the side-by-side layout the geometry
   is written into the dedicated profile *before* launch. The user's own
   Firefox profile is never touched.
2. Win32 (ctypes, Windows only) – after launch the new Firefox window is located
   by its window class and moved/focused. No extra dependency.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

XUL_KEY = "chrome://browser/content/browser.xhtml"


@dataclass
class Geometry:
    x: int
    y: int
    width: int
    height: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Geometry | None":
        if not d:
            return None
        try:
            return cls(int(d["x"]), int(d["y"]), int(d["width"]), int(d["height"]))
        except (KeyError, TypeError, ValueError):
            return None


def side_by_side(screen: Geometry, layout: str = "with_panel", panel_width: int = 440) -> dict[str, Geometry]:
    """Host left, guest right; optionally a column on the right for the control panel."""
    if layout == "with_panel" and screen.width >= 1500:
        panel_width = min(panel_width, screen.width // 4)
        browser_w = (screen.width - panel_width) // 2
        return {
            "host": Geometry(screen.x, screen.y, browser_w, screen.height),
            "guest": Geometry(screen.x + browser_w, screen.y, browser_w, screen.height),
            "panel": Geometry(screen.x + 2 * browser_w, screen.y, screen.width - 2 * browser_w, screen.height),
        }
    half = screen.width // 2
    return {
        "host": Geometry(screen.x, screen.y, half, screen.height),
        "guest": Geometry(screen.x + half, screen.y, screen.width - half, screen.height),
        "panel": Geometry(screen.x + screen.width - 460, screen.y + 40, 440, 560),  # compact bar on top
    }


# --- xulstore --------------------------------------------------------------------------

def seed_profile_geometry(profile_dir: Path, geom: Geometry) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    path = profile_dir / "xulstore.json"
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    win = data.setdefault(XUL_KEY, {}).setdefault("main-window", {})
    win.update({"screenX": str(geom.x), "screenY": str(geom.y), "width": str(geom.width),
                "height": str(geom.height), "sizemode": "normal"})
    path.write_text(json.dumps(data), encoding="utf-8")


def read_profile_geometry(profile_dir: Path) -> Geometry | None:
    path = profile_dir / "xulstore.json"
    try:
        win = json.loads(path.read_text(encoding="utf-8"))[XUL_KEY]["main-window"]
        return Geometry(int(win["screenX"]), int(win["screenY"]), int(win["width"]), int(win["height"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


# --- Win32 -----------------------------------------------------------------------------------

class Win32Windows:
    """Minimal ctypes wrapper. All methods are no-ops on other platforms."""

    available = sys.platform == "win32"

    def __init__(self) -> None:
        self._u = None
        if self.available:
            try:
                import ctypes
                from ctypes import wintypes
                self._ct, self._wt = ctypes, wintypes
                self._u = ctypes.WinDLL("user32", use_last_error=True)
                self._proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            except Exception:  # pragma: no cover - defensive
                log.exception("Win32 window management unavailable")
                self._u = None

    @property
    def ok(self) -> bool:
        return self._u is not None

    def firefox_windows(self) -> dict[int, int]:
        """Visible Firefox main windows -> owning process id."""
        if not self.ok:
            return {}
        ct, wt, u = self._ct, self._wt, self._u
        found: dict[int, int] = {}

        def cb(hwnd, _lparam):
            if u.IsWindowVisible(hwnd):
                buf = ct.create_unicode_buffer(128)
                u.GetClassNameW(hwnd, buf, 128)
                if buf.value == "MozillaWindowClass":
                    pid = wt.DWORD()
                    u.GetWindowThreadProcessId(hwnd, ct.byref(pid))
                    found[int(hwnd)] = int(pid.value)
            return True

        u.EnumWindows(self._proc_type(cb), 0)
        return found

    def wait_new_window(self, before: set[int], timeout: float = 12.0, pid: int | None = None) -> int | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for hwnd, owner in self.firefox_windows().items():
                if hwnd not in before and (pid is None or owner == pid):
                    return hwnd
            time.sleep(0.3)
        return None

    def window_for_pid(self, pid: int) -> int | None:
        for hwnd, owner in self.firefox_windows().items():
            if owner == pid:
                return hwnd
        return None

    def move(self, hwnd: int, g: Geometry) -> bool:
        if not self.ok or not hwnd:
            return False
        SW_RESTORE, SWP_NOZORDER, SWP_NOACTIVATE = 9, 0x0004, 0x0010
        self._u.ShowWindow(hwnd, SW_RESTORE)
        return bool(self._u.SetWindowPos(hwnd, 0, g.x, g.y, g.width, g.height, SWP_NOZORDER | SWP_NOACTIVATE))

    def focus(self, hwnd: int) -> bool:
        if not self.ok or not hwnd:
            return False
        if self._u.IsIconic(hwnd):
            self._u.ShowWindow(hwnd, 9)
        return bool(self._u.SetForegroundWindow(hwnd))

    def rect(self, hwnd: int) -> Geometry | None:
        if not self.ok or not hwnd:
            return None
        r = self._wt.RECT()
        if not self._u.GetWindowRect(hwnd, self._ct.byref(r)):
            return None
        return Geometry(r.left, r.top, r.right - r.left, r.bottom - r.top)

    def exists(self, hwnd: int) -> bool:
        return bool(self.ok and hwnd and self._u.IsWindow(hwnd))
