"""Manages the two participant browser sessions (host / guest).

Backends per participant:
    managed   – Playwright-managed Firefox, dedicated persistent profile (automation possible)
    standard  – installed Firefox, dedicated profile, no automation (clipboard workflow)
    none      – no browser; the operator uses any window they like (clipboard workflow)

Stopping a conversation never closes browser windows. Windows are closed only on
an explicit operator action (or when the application exits, for managed ones).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from adapters.errors import AdapterError
from app import paths
from app.events import EventBus, EventType

from .firefox_backend import ManagedFirefoxSession, PlaywrightHub
from .manual_backend import StandardFirefoxSession
from .window_manager import Geometry, read_profile_geometry

log = logging.getLogger(__name__)

BACKENDS = {
    "managed": "Playwright-managed Firefox (automation)",
    "standard": "Installed Firefox (no automation, clipboard)",
    "none": "No browser (clipboard only)",
}


class BrowserManager:
    def __init__(self, bus: EventBus, firefox_path: str = "") -> None:
        self.bus = bus
        self.firefox_path = firefox_path
        self.hub = PlaywrightHub()
        self.sessions: dict[str, Any] = {}
        self._monitor: asyncio.Task | None = None

    # ------------------------------------------------------------------------------
    def _status(self, role: str, browser: str, detail: str = "") -> None:
        self.bus.emit(EventType.PARTICIPANT, role=role, field="browser", value=browser, detail=detail)

    def _on_closed(self, role: str) -> None:
        self._status(role, "closed", "browser window was closed")
        self.bus.emit(EventType.LOG, level="warning", message=f"{role}: browser window closed")

    async def open(self, role: str, provider_id: str, url: str, backend: str,
                   host_patterns: list[str] | None = None, geometry: Geometry | None = None,
                   apply_layout: bool = True) -> None:
        existing = self.sessions.get(role)
        if existing is not None and not existing.is_closed() and existing.provider_id == provider_id \
                and existing.backend == backend:
            await existing.focus()
            self._status(role, "open", "already open – focused")
            return
        if backend == "none":
            self.sessions.pop(role, None)
            self._status(role, "none", "clipboard workflow – open the chat in any browser")
            return
        if backend == "managed":
            profile = paths.managed_profile_dir(role, provider_id)
            session: Any = ManagedFirefoxSession(role, provider_id, profile, host_patterns or [], self.hub,
                                                 self._on_closed)
        elif backend == "standard":
            profile = paths.standard_profile_dir(role, provider_id)
            session = StandardFirefoxSession(role, provider_id, profile, self.firefox_path)
        else:
            raise AdapterError(f"unknown browser backend '{backend}'")
        if not apply_layout and read_profile_geometry(profile) is not None:
            geometry = None  # Firefox restores the geometry it remembered for this dedicated profile
        self._status(role, "launching", BACKENDS[backend])
        try:
            await session.start(url, geometry)
        except Exception as exc:
            self._status(role, "error", str(exc))
            raise
        self.sessions[role] = session
        self._status(role, "open", BACKENDS[backend])
        self._ensure_monitor()

    def page_getter(self, role: str) -> Callable[[], Any]:
        def get():
            session = self.sessions.get(role)
            return session.driver() if session is not None and not session.is_closed() else None
        return get

    def backend_of(self, role: str) -> str | None:
        s = self.sessions.get(role)
        return s.backend if s is not None else None

    def is_open(self, role: str) -> bool:
        s = self.sessions.get(role)
        return s is not None and not s.is_closed()

    async def focus(self, role: str) -> bool:
        s = self.sessions.get(role)
        if s is None or s.is_closed():
            return False
        await s.focus()
        return True

    async def current_url(self, role: str) -> str:
        s = self.sessions.get(role)
        return await s.current_url() if s is not None and not s.is_closed() else ""

    def geometries(self) -> dict[str, dict[str, int]]:
        out = {}
        for role, s in self.sessions.items():
            g = s.geometry() if not s.is_closed() else None
            if g:
                out[role] = g.as_dict()
        return out

    async def close(self, role: str) -> None:
        s = self.sessions.pop(role, None)
        if s is not None:
            await s.close()
            self._status(role, "closed", "closed by operator")

    async def shutdown(self) -> None:
        if self._monitor is not None:
            self._monitor.cancel()
        for role in list(self.sessions):
            s = self.sessions[role]
            if s.backend == "managed":
                try:
                    await s.close()
                except Exception:  # noqa: BLE001
                    log.exception("closing %s failed", role)
        await self.hub.stop()

    # ------------------------------------------------------------------------------
    def _ensure_monitor(self) -> None:
        if self._monitor is None or self._monitor.done():
            self._monitor = asyncio.ensure_future(self._watch())

    async def _watch(self) -> None:
        reported: set[str] = set()
        while True:
            await asyncio.sleep(2.0)
            for role, s in list(self.sessions.items()):
                if s.is_closed() and role not in reported:
                    reported.add(role)
                    if s.backend == "standard":
                        self._status(role, "closed", "Firefox window was closed")
                elif not s.is_closed():
                    reported.discard(role)
