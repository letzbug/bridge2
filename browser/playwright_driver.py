"""PageDriver implementation for Playwright (async API).

Used for Playwright's managed Firefox build. The same driver also works with
Chromium, which the test-suite uses against the local mock chat page.
"""

from __future__ import annotations

import re
from typing import Any

from adapters.errors import AdapterError, BrowserClosedError

from .page_driver import EXTRACT_JS, HIGHLIGHT_JS, READ_INPUT_JS

try:  # Playwright is an install-time dependency, but keep imports soft for tests/demo.
    from playwright.async_api import Error as PlaywrightError
except Exception:  # pragma: no cover
    class PlaywrightError(Exception):  # type: ignore[no-redef]
        pass

_SHORT = 3000
_ACTION = 8000
_MAX_SCAN = 6


class PlaywrightPageDriver:
    def __init__(self, page: Any) -> None:
        self.page = page

    # --- selector resolution --------------------------------------------------------
    def _loc(self, selector: str) -> Any:
        if selector.startswith("role:"):
            _, _, rest = selector.partition(":")
            role, _, name = rest.partition(":")
            if name:
                return self.page.get_by_role(role.strip(), name=re.compile(name, re.IGNORECASE))
            return self.page.get_by_role(role.strip())
        if selector.startswith("text:"):
            return self.page.get_by_text(re.compile(selector[5:], re.IGNORECASE))
        return self.page.locator(selector)

    def _guard(self) -> None:
        if self.page.is_closed():
            raise BrowserClosedError("The browser page was closed")

    async def _call(self, coro):
        try:
            return await coro
        except PlaywrightError as exc:
            msg = str(exc)
            if "closed" in msg.lower() or self.page.is_closed():
                raise BrowserClosedError("The browser page or window was closed") from exc
            raise AdapterError(f"Browser automation error: {msg.splitlines()[0][:200]}") from exc

    async def _first_visible(self, selector: str) -> Any | None:
        loc = self._loc(selector)
        n = await self._call(loc.count())
        for i in range(min(n, _MAX_SCAN)):
            item = loc.nth(i)
            try:
                if await item.is_visible():
                    return item
            except PlaywrightError:
                continue
        return None

    # --- PageDriver -------------------------------------------------------------------
    async def count(self, selector: str) -> int:
        self._guard()
        return int(await self._call(self._loc(selector).count()))

    async def any_visible(self, selector: str) -> bool:
        self._guard()
        return await self._first_visible(selector) is not None

    async def first_visible_enabled(self, selector: str) -> bool:
        self._guard()
        item = await self._first_visible(selector)
        if item is None:
            return False
        try:
            return bool(await item.is_enabled())
        except PlaywrightError:
            return False

    async def extract_text(self, selector: str, index: int, exclude: list[str], mode: str = "markdown") -> str:
        self._guard()
        loc = self._loc(selector)
        item = loc.last if index == -1 else loc.nth(index)
        return str(await self._call(item.evaluate(EXTRACT_JS, {"exclude": exclude, "mode": mode},
                                                  timeout=_ACTION)))

    async def get_attribute(self, selector: str, index: int, name: str) -> str | None:
        self._guard()
        loc = self._loc(selector)
        item = loc.last if index == -1 else loc.nth(index)
        return await self._call(item.get_attribute(name, timeout=_SHORT))

    async def fill(self, selector: str, text: str, method: str = "fill") -> None:
        self._guard()
        item = await self._first_visible(selector)
        if item is None:
            raise AdapterError(f"Input '{selector}' is not visible")
        await self._call(item.click(timeout=_ACTION))
        if method == "insert_text":
            await self._call(self.page.keyboard.press("Control+A"))
            await self._call(self.page.keyboard.press("Delete"))
            await self._call(self.page.keyboard.insert_text(text))
        else:
            await self._call(item.fill(text, timeout=_ACTION))

    async def read_input(self, selector: str) -> str:
        self._guard()
        item = await self._first_visible(selector)
        if item is None:
            return ""
        return str(await self._call(item.evaluate(READ_INPUT_JS, timeout=_SHORT)))

    async def click(self, selector: str) -> None:
        self._guard()
        item = await self._first_visible(selector)
        if item is None:
            raise AdapterError(f"Element '{selector}' is not visible")
        await self._call(item.click(timeout=_ACTION))

    async def press(self, selector: str, key: str) -> None:
        self._guard()
        item = await self._first_visible(selector)
        if item is None:
            raise AdapterError(f"Element '{selector}' is not visible")
        await self._call(item.press(key, timeout=_ACTION))

    async def texts(self, selector: str, limit: int = 5) -> list[str]:
        self._guard()
        loc = self._loc(selector)
        n = min(await self._call(loc.count()), limit)
        out = []
        for i in range(n):
            try:
                if await loc.nth(i).is_visible():
                    out.append(await loc.nth(i).inner_text(timeout=_SHORT))
            except PlaywrightError:
                continue
        return out

    async def highlight(self, selector: str, color: str = "#2fd3b5") -> int:
        self._guard()
        return int(await self._call(self._loc(selector).evaluate_all(HIGHLIGHT_JS, color)))

    async def url(self) -> str:
        return "" if self.page.is_closed() else self.page.url

    def is_closed(self) -> bool:
        return bool(self.page.is_closed())

    async def bring_to_front(self) -> None:
        self._guard()
        await self._call(self.page.bring_to_front())
