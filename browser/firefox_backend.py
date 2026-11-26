"""Playwright-managed Firefox backend (automation-capable).

IMPORTANT DISTINCTION
* This backend launches *Playwright's own Firefox build* (installed with
  `python -m playwright install firefox`). It is NOT your installed Firefox and it
  cannot attach to Firefox windows that are already running.
* Each participant gets a dedicated persistent profile under the local data
  directory (e.g. profiles/managed-firefox/host-chatgpt). You log in there once
  manually; the login is reused on later launches. Your normal Firefox profile is
  never read, modified or deleted.
* No stealth, fingerprint or CAPTCHA workarounds are applied. Some providers may
  refuse sign-in in automated browsers – use the standard-Firefox backend with the
  clipboard mode in that case.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Callable

from adapters.errors import AdapterError, DependencyMissingError

from .playwright_driver import PlaywrightPageDriver
from .runtime import missing_runtime_hint
from .window_manager import Geometry, Win32Windows, seed_profile_geometry

log = logging.getLogger(__name__)



class PlaywrightHub:
    """One Playwright driver process shared by all managed sessions."""

    def __init__(self) -> None:
        self._pw: Any = None
        self._lock = asyncio.Lock()

    async def get(self) -> Any:
        async with self._lock:
            if self._pw is None:
                try:
                    from playwright.async_api import async_playwright
                except ImportError as exc:
                    raise DependencyMissingError("The 'playwright' package is not installed (run install.bat).") from exc
                self._pw = await async_playwright().start()
            return self._pw

    async def stop(self) -> None:
        async with self._lock:
            if self._pw is not None:
                try:
                    await self._pw.stop()
                finally:
                    self._pw = None


class ManagedFirefoxSession:
    backend = "managed"

    def __init__(self, role: str, provider_id: str, profile_dir: Path, host_patterns: list[str],
                 hub: PlaywrightHub, on_closed: Callable[[str], None], headless: bool | None = None) -> None:
        self.role = role
        self.provider_id = provider_id
        self.profile_dir = profile_dir
        self.host_patterns = [h.lower() for h in host_patterns]
        self.hub = hub
        self.on_closed = on_closed
        self.context: Any = None
        self.hwnd: int | None = None
        self.closed = True
        self._drivers: dict[int, PlaywrightPageDriver] = {}
        self._win = Win32Windows()
        # Headless only for automated self-tests (EMERGENCE_LAB_HEADLESS=1). Normal use is always visible,
        # because the operator logs in and watches the native interface.
        self.headless = headless if headless is not None else os.environ.get("EMERGENCE_LAB_HEADLESS") == "1"

    async def start(self, url: str, geometry: Geometry | None) -> None:
        pw = await self.hub.get()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        if geometry:
            seed_profile_geometry(self.profile_dir, geometry)
        before = set(self._win.firefox_windows()) if self._win.ok else set()
        # Window size/position: xulstore.json (seeded above) + Win32 move after launch.
        # (Playwright rejects positional launch arguments such as "-width 800".)
        try:
            self.context = await pw.firefox.launch_persistent_context(
                user_data_dir=str(self.profile_dir), headless=self.headless, no_viewport=True)
        except Exception as exc:  # noqa: BLE001 - mapped to readable messages
            msg = str(exc)
            if "Executable doesn't exist" in msg or "playwright install" in msg:
                raise DependencyMissingError(missing_runtime_hint()) from exc
            if "lock" in msg.lower() or "already in use" in msg.lower():
                raise AdapterError(f"The dedicated profile {self.profile_dir.name} is already in use. "
                                   "Close the other window that uses it.") from exc
            raise AdapterError(f"Could not launch the managed Firefox: {msg.splitlines()[0][:240]}") from exc
        self.closed = False
        self.context.on("close", lambda *_: self._mark_closed())
        page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        if url:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception as exc:  # noqa: BLE001 - window stays open for manual navigation
                log.warning("navigation to %s failed: %s", url, exc)
        if self._win.ok and not self.headless:
            self.hwnd = await asyncio.to_thread(self._win.wait_new_window, before, 10.0)
            if self.hwnd and geometry:
                self._win.move(self.hwnd, geometry)

    def _mark_closed(self) -> None:
        if not self.closed:
            self.closed = True
            self._drivers.clear()
            try:
                self.on_closed(self.role)
            except Exception:  # pragma: no cover
                log.exception("close callback failed")

    def _select_page(self) -> Any | None:
        if self.closed or self.context is None:
            return None
        pages = [p for p in self.context.pages if not p.is_closed()]
        if not pages:
            return None
        if self.host_patterns:
            matching = [p for p in pages if any(h in (p.url or "").lower() for h in self.host_patterns)]
            if matching:
                return matching[-1]
        return pages[-1]

    def driver(self) -> PlaywrightPageDriver | None:
        page = self._select_page()
        if page is None:
            return None
        key = id(page)
        if key not in self._drivers:
            self._drivers[key] = PlaywrightPageDriver(page)
        return self._drivers[key]

    def is_closed(self) -> bool:
        return self.closed or self._select_page() is None

    async def current_url(self) -> str:
        page = self._select_page()
        return page.url if page else ""

    async def focus(self) -> None:
        page = self._select_page()
        if page is not None:
            await page.bring_to_front()
        if self.hwnd and self._win.exists(self.hwnd):
            self._win.focus(self.hwnd)

    def geometry(self) -> Geometry | None:
        if self.hwnd and self._win.exists(self.hwnd):
            return self._win.rect(self.hwnd)
        return None

    async def close(self) -> None:
        if self.context is not None and not self.closed:
            try:
                await self.context.close()
            finally:
                self._mark_closed()
