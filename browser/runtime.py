"""Optional Playwright browser runtime (Playwright's own Firefox build).

The portable build bundles the Playwright Python package and its driver (which
contains its own Node.js runtime – nothing has to be installed on the computer),
but NOT the ~80–100 MB Firefox build. The Firefox build is only needed for the
automated browser adapters and is downloaded on request into the data directory
(portable build) or Playwright's default location (source install).

Demo mode, clipboard mode and the installed-Firefox backend never need it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from app import paths

DOWNLOAD_SIZE = "about 80–100 MB"
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def browsers_path() -> Path:
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env and env != "0":
        return Path(env)
    if env == "0":
        try:
            import playwright
            return Path(playwright.__file__).parent / "driver" / "package" / ".local-browsers"
        except ImportError:
            pass
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ms-playwright"


def playwright_available() -> tuple[bool, str]:
    try:
        from playwright._impl._driver import compute_driver_executable  # noqa: F401
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"The Playwright package is not available ({type(exc).__name__})."


def installed_firefox_builds() -> list[Path]:
    root = browsers_path()
    if not root.is_dir():
        return []
    found = []
    for d in sorted(root.glob("firefox-*")):
        exe_candidates = (d / "firefox" / "firefox.exe", d / "firefox" / "firefox", d / "firefox" / "Nightly.app")
        if any(c.exists() for c in exe_candidates):
            found.append(d)
    return found


def firefox_installed() -> bool:
    return bool(installed_firefox_builds())


def status() -> dict[str, object]:
    ok, msg = playwright_available()
    builds = installed_firefox_builds()
    return {"playwright": ok, "playwright_error": msg, "firefox_installed": bool(builds),
            "builds": [b.name for b in builds], "path": str(browsers_path()),
            "managed_by_app": removable()}


def driver_command() -> list[str]:
    from playwright._impl._driver import compute_driver_executable
    result = compute_driver_executable()
    if isinstance(result, (tuple, list)):
        return [str(x) for x in result]
    return [str(result)]


def driver_env() -> dict[str, str]:
    try:
        from playwright._impl._driver import get_driver_env
        return get_driver_env()
    except ImportError:
        return dict(os.environ)


def install_firefox(on_line: Callable[[str], None] | None = None, timeout: float = 1800) -> int:
    """Downloads Playwright's Firefox build (explicit operator action only). Returns the exit code."""
    ok, msg = playwright_available()
    if not ok:
        raise RuntimeError(msg)
    browsers_path().mkdir(parents=True, exist_ok=True)
    cmd = driver_command() + ["install", "firefox"]
    emit = on_line or (lambda _line: None)
    emit(f"Installing Playwright Firefox into {browsers_path()} ({DOWNLOAD_SIZE}) …")
    proc = subprocess.Popen(cmd, env=driver_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            emit(line)
    rc = proc.wait(timeout)
    emit("Firefox runtime installed." if rc == 0 else f"Installation failed (exit code {rc}).")
    return rc


def removable() -> bool:
    """Only a runtime inside the application's own data directory may be removed from the app."""
    return paths.is_inside(browsers_path(), paths.data_dir())


def remove_firefox() -> int:
    if not removable():
        raise RuntimeError(f"The browser runtime at {browsers_path()} is shared with other Playwright installations "
                           "and is not removed by EMERGENCE LAB. Use 'playwright uninstall' instead.")
    removed = 0
    for d in installed_firefox_builds():
        shutil.rmtree(d, ignore_errors=True)
        removed += 1
    return removed


def missing_runtime_hint() -> str:
    if paths.FROZEN:
        return ("Playwright's managed Firefox build is not installed. It is optional and only needed for automated "
                f"adapters: Settings → Browser & windows → Browser runtime → Install ({DOWNLOAD_SIZE}). "
                "Without it, use the 'Installed Firefox' backend with the clipboard workflow.")
    return ("Playwright's managed Firefox build is not installed. Run install.bat again and answer Y to the "
            "browser runtime question, or run:  .venv\\Scripts\\python -m playwright install firefox")
