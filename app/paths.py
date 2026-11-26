"""Local file locations – works from source and as a PyInstaller one-folder build.

Three separate places:

* RESOURCE_DIR – read-only files shipped with the application (config/, assets/, docs/).
  From source: the project folder. Portable build: EmergenceLab\\_internal.
* INSTALL_DIR  – the folder that contains EmergenceLab.exe (or main.py). Never written to.
* data_dir()   – everything the application writes: settings, research database, logs,
  exports, dedicated browser profiles, the optional Playwright browser runtime, audio models.

data_dir() resolution order:
1. environment variable EMERGENCE_LAB_HOME (also set by --data-dir)
2. portable data mode: a file named "EmergenceLab.portable" next to the executable
   -> sibling folder "EmergenceLab-Data" NEXT TO (not inside) the application folder
3. default: %LOCALAPPDATA%\\EmergenceLab (Windows), ~/Library/Application Support/EmergenceLab
   (macOS), $XDG_DATA_HOME/emergence-lab (Linux)

A data directory inside the application folder is rejected (falls back to the default) so
that replacing or deleting the application folder never touches research data or logins.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

log = logging.getLogger(__name__)

FROZEN = bool(getattr(sys, "frozen", False))


def _resource_dir() -> Path:
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)).resolve()
    return Path(__file__).resolve().parent.parent


def _install_dir() -> Path:
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


RESOURCE_DIR = _resource_dir()
INSTALL_DIR = _install_dir()
APP_DIR = RESOURCE_DIR                     # kept for compatibility with v0.1.0 code
CONFIG_DIR = RESOURCE_DIR / "config"
ASSETS_DIR = RESOURCE_DIR / "assets"
DOCS_DIR = RESOURCE_DIR / "docs"
PORTABLE_MARKER = "EmergenceLab.portable"
PORTABLE_DATA_DIRNAME = "EmergenceLab-Data"

_warned: set[str] = set()


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "EmergenceLab"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "EmergenceLab"
    xdg = os.environ.get("XDG_DATA_HOME")
    base_path = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base_path / "emergence-lab"


def portable_mode() -> bool:
    return (INSTALL_DIR / PORTABLE_MARKER).is_file()


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _guard(candidate: Path, source: str) -> Path:
    """Reject data locations inside the application folder (only relevant for the portable build)."""
    if FROZEN and is_inside(candidate, INSTALL_DIR):
        if source not in _warned:
            _warned.add(source)
            log.warning("data directory %s (%s) is inside the application folder – using %s instead",
                        candidate, source, default_data_dir())
        return default_data_dir()
    return candidate


def data_dir() -> Path:
    override = os.environ.get("EMERGENCE_LAB_HOME")
    if override:
        return _guard(Path(override).expanduser().resolve(), "EMERGENCE_LAB_HOME")
    if portable_mode():
        return _guard((INSTALL_DIR.parent / PORTABLE_DATA_DIRNAME).resolve(), "portable mode")
    return default_data_dir()


def data_location_description() -> str:
    if os.environ.get("EMERGENCE_LAB_HOME"):
        return "custom (EMERGENCE_LAB_HOME / --data-dir)"
    if portable_mode():
        return f"portable mode ({PORTABLE_DATA_DIRNAME} next to the application folder)"
    return "default (user profile)"


def _safe(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", part).strip("._") or "default"


def profiles_dir() -> Path:
    return data_dir() / "profiles"


def managed_profile_dir(role: str, provider_id: str) -> Path:
    """Dedicated persistent profile for Playwright's managed Firefox build."""
    return profiles_dir() / "managed-firefox" / f"{_safe(role)}-{_safe(provider_id)}"


def standard_profile_dir(role: str, provider_id: str) -> Path:
    """Dedicated profile for an installed standard Firefox (never the user's default profile)."""
    return profiles_dir() / "standard-firefox" / f"{_safe(role)}-{_safe(provider_id)}"


def logs_dir() -> Path:
    return data_dir() / "logs"


def sessions_db_path() -> Path:
    return data_dir() / "research" / "sessions.sqlite3"


def exports_dir() -> Path:
    return data_dir() / "exports"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def user_providers_path() -> Path:
    return data_dir() / "providers.user.json"


def audio_models_dir() -> Path:
    return data_dir() / "audio-models"


def browser_runtime_dir() -> Path:
    """Where the portable build keeps the optional Playwright browser runtime."""
    return data_dir() / "browser-runtime"


def configure_runtime_environment() -> None:
    """Called once at startup, before anything launches a browser.

    In the portable build the optional Playwright browser runtime lives in the data
    directory (outside the application folder). From source, Playwright's default
    location is kept so that `python -m playwright install firefox` keeps working.
    An explicit PLAYWRIGHT_BROWSERS_PATH set by the user always wins.
    """
    if FROZEN and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_runtime_dir())
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def ensure_dirs() -> list[Path]:
    created = []
    for p in (data_dir(), profiles_dir(), logs_dir(), sessions_db_path().parent, exports_dir(), audio_models_dir()):
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append(p)
    return created


def resolve_app_url(url: str) -> str:
    """Resolve '@app/...' URLs (local test pages shipped with the app) to file:// URLs."""
    if url.startswith("@app/"):
        return (RESOURCE_DIR / url[len("@app/"):]).resolve().as_uri()
    return url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EMERGENCE LAB local paths")
    parser.add_argument("--init", action="store_true", help="create local application directories")
    args = parser.parse_args(argv)
    if args.init:
        created = ensure_dirs()
        for p in created:
            print(f"  created {p}")
    print(f"  data directory: {data_dir()}  [{data_location_description()}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
