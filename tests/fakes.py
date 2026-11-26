"""Fake provider adapters and a fake chat page used by the tests."""

from __future__ import annotations

import asyncio
import time
from typing import Callable

from adapters.base import BaseProviderAdapter, ConversationSnapshot, ResponseResult, SubmissionReceipt
from adapters.errors import BrowserClosedError, ResponseTimeoutError
from app.engine import ConversationConfig, ConversationEngine, Participant, Role, TransferMode
from app.events import EventBus, EventRecorder
from app.gate import SendGate


class ScriptedAdapter(BaseProviderAdapter):
    """Deterministic participant. Reply n is replies[n] (or replies(n, received_text))."""

    provider_id = "fake"
    provider_label = "Fake"

    def __init__(self, name: str, replies: list[str] | Callable[[int, str], str], delay: float = 0.01,
                 uncertain_on: set[int] | None = None, timeout_once_on: set[int] | None = None,
                 close_on_send: set[int] | None = None, generation_seconds: float = 0.0) -> None:
        super().__init__(name)
        self.provider_label = f"Fake {name}"
        self.replies = replies
        self.delay = delay
        self.uncertain_on = uncertain_on or set()
        self.timeout_once_on = set(timeout_once_on or set())
        self.close_on_send = close_on_send or set()
        self.generation_seconds = generation_seconds
        self.capabilities.automatic_mode = True
        self.capabilities.detect_generation = True
        self.capabilities.requires_live_validation = False
        self.sent: list[str] = []
        self.submissions = 0          # actual "clicks"
        self.closed = False
        self._pending: list[str] = []
        self._responses = 0
        self._generating_until = 0.0

    def _reply(self, n: int, received: str) -> str:
        if callable(self.replies):
            return self.replies(n, received)
        return self.replies[n % len(self.replies)]

    async def connect(self) -> None:
        if self.closed:
            raise BrowserClosedError(f"{self.participant_name}: browser window was closed")

    async def is_ready(self) -> bool:
        return not self.closed

    async def get_conversation_state(self) -> ConversationSnapshot:
        if self.closed:
            raise BrowserClosedError(f"{self.participant_name}: browser window was closed")
        return ConversationSnapshot(url="fake://", conversation_id=f"conv-{self.participant_name}",
                                    assistant_count=self._responses,
                                    generating=time.monotonic() < self._generating_until)

    async def send_message(self, text: str) -> SubmissionReceipt:
        if self.closed:
            raise BrowserClosedError(f"{self.participant_name}: browser window was closed")
        index = len(self.sent)
        if index in self.close_on_send:
            self.closed = True
            raise BrowserClosedError(f"{self.participant_name}: browser window was closed")
        self._check_gate()
        self.sent.append(text)
        self.submissions += 1
        self._pending.append(text)
        self._generating_until = time.monotonic() + self.generation_seconds
        if index in self.uncertain_on:
            return SubmissionReceipt("uncertain", [], final_text=text, detail="no signal (test)")
        return SubmissionReceipt("confirmed", ["test_signal"], final_text=text)

    async def wait_for_response(self, timeout: float) -> ResponseResult:
        n = self._responses
        if n in self.timeout_once_on:
            self.timeout_once_on.discard(n)
            await asyncio.sleep(min(timeout, 0.05))
            raise ResponseTimeoutError(f"No completed response from {self.participant_name} within {timeout}s.")
        remaining = self._generating_until - time.monotonic()
        await asyncio.sleep(max(self.delay, remaining))
        if self.closed:
            raise BrowserClosedError(f"{self.participant_name}: browser window was closed")
        received = self._pending.pop(0) if self._pending else ""
        self._responses += 1
        return ResponseResult(self._reply(n, received), message_id=f"{self.participant_name}-{n}")

    async def get_latest_response(self) -> str | None:
        return None

    async def stop_generation(self) -> bool:
        if time.monotonic() < self._generating_until:
            self._generating_until = 0.0
            return True
        return False


def numbered(prefix: str) -> Callable[[int, str], str]:
    return lambda n, received: f"{prefix} reply number {n} with some distinct words about topic {n * 7919}"


def make_engine(host: BaseProviderAdapter, guest: BaseProviderAdapter, **cfg) -> tuple[ConversationEngine, EventRecorder]:
    bus = EventBus()
    rec = EventRecorder(bus)
    config = ConversationConfig(**{
        "session_name": "test", "topic": "testing", "max_rounds": 3, "max_wait_seconds": 2,
        "transfer_mode": TransferMode.AUTOMATIC, "min_interval_seconds": 0, **cfg})
    engine = ConversationEngine(
        Participant(Role.HOST, host.participant_name, host.provider_label, host),
        Participant(Role.GUEST, guest.participant_name, guest.provider_label, guest),
        config, bus=bus, gate=SendGate())
    return engine, rec


async def wait_for(predicate: Callable[[], bool], timeout: float = 5.0, interval: float = 0.01) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(interval)
