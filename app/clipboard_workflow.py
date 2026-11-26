"""Clipboard workflow coordination.

The coordinator never touches the system clipboard itself. It only publishes
requests ("paste this text into Gem's window", "import Gem's reply"). The GUI
reads or writes the clipboard exclusively when the operator clicks a button or
presses a configured shortcut, so unrelated clipboard contents are never
monitored or recorded.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from .events import EventBus, EventType


@dataclass
class ClipboardRequest:
    request_id: str
    action: str          # paste | import
    role: str
    name: str
    text: str
    future: asyncio.Future


class ClipboardCoordinator:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self._pending: dict[str, ClipboardRequest] = {}

    async def request(self, action: str, role: str, name: str, text: str = "") -> Any:
        loop = asyncio.get_running_loop()
        req = ClipboardRequest(uuid.uuid4().hex[:10], action, role, name, text, loop.create_future())
        self._pending[req.request_id] = req
        self.bus.emit(EventType.CLIPBOARD_REQUEST, request_id=req.request_id, action=action, role=role,
                      name=name, text=text)
        try:
            return await req.future
        finally:
            self._pending.pop(req.request_id, None)
            self.bus.emit(EventType.CLIPBOARD_CLEARED, request_id=req.request_id)

    def resolve(self, request_id: str, value: Any) -> bool:
        """Call from the engine loop thread (the controller marshals GUI actions)."""
        req = self._pending.get(request_id)
        if req is None or req.future.done():
            return False
        req.future.set_result(value)
        return True

    def pending(self) -> list[ClipboardRequest]:
        return list(self._pending.values())

    def find(self, action: str, role: str | None = None) -> ClipboardRequest | None:
        for req in self._pending.values():
            if req.action == action and (role is None or req.role == role):
                return req
        return None

    def cancel_all(self) -> None:
        for req in list(self._pending.values()):
            if not req.future.done():
                req.future.cancel()
