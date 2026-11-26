"""Browser session management.

The managed session runs with Playwright's real Firefox build when it is installed
(e.g. on the Windows CI runner) and otherwise with Playwright's Chromium standing in
(same persistent-context API). Headless, so it also runs without a display.
"""

import asyncio

import pytest

from adapters.registry import ProviderRegistry
from app.events import EventBus, EventRecorder, EventType
from browser.browser_manager import BrowserManager
from browser.firefox_backend import ManagedFirefoxSession, PlaywrightHub
from browser.window_manager import Geometry, read_profile_geometry, seed_profile_geometry, side_by_side


def test_side_by_side_layouts():
    wide = side_by_side(Geometry(0, 0, 2560, 1400), "with_panel")
    assert wide["host"].x == 0 and wide["guest"].x == wide["host"].width
    assert wide["panel"].x + wide["panel"].width == 2560
    narrow = side_by_side(Geometry(0, 0, 1366, 728), "with_panel")   # falls back to halves + compact bar
    assert narrow["host"].width + narrow["guest"].width == 1366


def test_xulstore_geometry_roundtrip(tmp_path):
    seed_profile_geometry(tmp_path, Geometry(10, 20, 900, 700))
    assert read_profile_geometry(tmp_path) == Geometry(10, 20, 900, 700)
    assert read_profile_geometry(tmp_path / "missing") is None


class _ChromiumHub(PlaywrightHub):
    """Hands Chromium to the session in place of Playwright's Firefox (test only)."""

    async def get(self):
        pw = await super().get()

        class Proxy:
            firefox = pw.chromium
        return Proxy()


def test_managed_session_profile_reuse_and_close_detection(tmp_path):
    pytest.importorskip("playwright.async_api")
    from browser import runtime

    real_firefox = runtime.firefox_installed()

    async def main():
        hub = PlaywrightHub() if real_firefox else _ChromiumHub()
        closed = []
        url = ProviderRegistry().get("mock").url + "?speed=fast"
        profile = tmp_path / "host-mock"
        s = ManagedFirefoxSession("host", "mock", profile, ["mock_chat.html"], hub, closed.append, headless=True)
        try:
            await s.start(url, Geometry(0, 0, 800, 600))
        except Exception as exc:  # noqa: BLE001
            await hub.stop()
            pytest.skip(f"browser could not start: {exc}")
        try:
            assert not s.is_closed()
            drv = s.driver()
            assert drv is not None and "mock_chat.html" in await drv.url()
            # a second tab on another site does not steal the participant page
            other = await s.context.new_page()
            await other.goto("about:blank")
            assert "mock_chat.html" in await s.driver().url()
            await s.close()
            assert s.is_closed() and closed == ["host"]
            assert any(profile.iterdir())                       # persistent profile written
            s2 = ManagedFirefoxSession("host", "mock", profile, ["mock_chat.html"], hub, closed.append,
                                       headless=True)
            await s2.start(url, None)                           # same dedicated profile reused
            assert not s2.is_closed()
            await s2.close()
        finally:
            await hub.stop()
    asyncio.run(asyncio.wait_for(main(), 90))


def test_browser_manager_none_backend_and_page_getter():
    async def main():
        bus = EventBus()
        rec = EventRecorder(bus)
        bm = BrowserManager(bus)
        await bm.open("guest", "gemini", "", "none")
        assert bm.page_getter("guest")() is None
        assert not bm.is_open("guest")
        ev = rec.of(EventType.PARTICIPANT)[-1]
        assert ev.data["value"] == "none"
        await bm.shutdown()
    asyncio.run(main())
