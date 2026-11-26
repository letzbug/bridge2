"""Thread-safe submission gate.

The emergency stop disarms this gate synchronously from the GUI thread. Every
adapter checks it immediately before it performs the actual submission (click /
Enter / TTS playback), so no automated submission can happen after the
emergency stop, even if asyncio cancellation has not propagated yet.
"""

from __future__ import annotations

import threading

from adapters.errors import SubmissionBlockedError


class SendGate:
    def __init__(self) -> None:
        self._armed = threading.Event()
        self._armed.set()
        self._lock = threading.Lock()
        self.reason: str | None = None

    def arm(self) -> None:
        with self._lock:
            self.reason = None
            self._armed.set()

    def disarm(self, reason: str = "emergency stop") -> None:
        with self._lock:
            self.reason = reason
            self._armed.clear()

    @property
    def armed(self) -> bool:
        return self._armed.is_set()

    def check(self) -> None:
        if not self._armed.is_set():
            raise SubmissionBlockedError(f"Submission blocked: {self.reason or 'gate closed'}")
