"""Thread-agnostic event bus used between the engine, the recorder and the GUI.

Events are plain data. They never carry callables, and handlers never execute
anything contained in message text.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


class EventType:
    STATE = "state"                          # state, previous, reason
    SESSION_STARTED = "session_started"      # meta
    SESSION_ENDED = "session_ended"          # end_state, reason
    ENTRY_ADDED = "entry_added"              # entry (dict)
    ENTRY_UPDATED = "entry_updated"          # entry (dict)
    ROUND = "round"                          # current_round, completed_rounds, max_rounds, turn
    TRANSFER = "transfer"                    # status, source, destination, detail
    WAITING = "waiting"                      # role, name, timeout, started (monotonic), active
    ISSUE = "issue"                          # code, severity, message, actions
    ISSUE_CLEARED = "issue_cleared"
    CONFIRMATION_REQUIRED = "confirmation_required"   # kind, ...
    CONFIRMATION_CLEARED = "confirmation_cleared"
    HUMAN = "human"                          # status, detail
    CLIPBOARD_REQUEST = "clipboard_request"  # request_id, action, role, name, text
    CLIPBOARD_CLEARED = "clipboard_cleared"  # request_id
    PARTICIPANT = "participant"              # role, field, value
    LOG = "log"                              # level, message
    AUDIO = "audio"                          # status, detail


@dataclass(frozen=True)
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


Handler = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._subs: list[Handler] = []
        self._lock = threading.Lock()

    def subscribe(self, handler: Handler) -> Callable[[], None]:
        with self._lock:
            self._subs.append(handler)

        def unsubscribe() -> None:
            with self._lock:
                if handler in self._subs:
                    self._subs.remove(handler)

        return unsubscribe

    def emit(self, type_: str, **data: Any) -> Event:
        event = Event(type_, data)
        with self._lock:
            subs = list(self._subs)
        for handler in subs:
            try:
                handler(event)
            except Exception:  # a broken subscriber must never break the engine
                log.exception("event handler failed for %s", type_)
        return event


class EventRecorder:
    """Collects events (used by tests and the demo)."""

    def __init__(self, bus: EventBus) -> None:
        self.events: list[Event] = []
        self._lock = threading.Lock()
        bus.subscribe(self._on)

    def _on(self, ev: Event) -> None:
        with self._lock:
            self.events.append(ev)

    def of(self, type_: str) -> list[Event]:
        with self._lock:
            return [e for e in self.events if e.type == type_]

    def states(self) -> list[str]:
        return [e.data["state"] for e in self.of(EventType.STATE)]
