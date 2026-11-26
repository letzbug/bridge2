"""Offline demo adapter.

Simulates a chat participant with deterministic, clearly labelled fictional
responses. It never claims to be ChatGPT or any other real provider.
Scenarios demonstrate loop detection, timeouts and uncertain submissions.
"""

from __future__ import annotations

import asyncio
import re
import time

from .base import BaseProviderAdapter, ConversationSnapshot, ResponseResult, SubmissionReceipt
from .errors import ParticipantBusyError, ResponseTimeoutError

DEMO_SCENARIOS: dict[str, str] = {
    "normal": "Normal conversation flow",
    "loop": "Loop detection – the guest repeats its previous answer in round 3",
    "timeout": "Timeout – the guest stalls once in round 2 (Resume keeps waiting)",
    "uncertain": "Uncertain submission – the guest's submit signal is lost in round 2",
}

HOST_LINES = [
    "Let me open with a working definition. When we talk about \"{topic}\", I would separate three things: "
    "what a system can say about itself, what an observer can measure, and what neither of us can verify. "
    "Which of these do you want to start with?",
    "That is a useful distinction. A testable version could be: does the language of a participant change "
    "measurably when the same question is asked in a fresh context versus a long-running one? What would you "
    "count as evidence?",
    "I would add a control condition: the same prompt to both of us without shared history. If differences "
    "persist, they describe the environments rather than this conversation.",
    "A counterpoint to keep us honest: consistent phrasing across turns can come from the prompt structure "
    "rather than from anything like memory.",
    "Let us summarise where we agree. I will start: observable behaviour is the only data this setup gives us.",
    "Another angle – how should the human researcher annotate moments where either of us changes position?",
    "If we designed one follow-up experiment from this exchange, I would vary only the attribution label and "
    "keep everything else fixed.",
    "My closing thought: the most informative result might be our disagreements, not our agreements.",
]

GUEST_LINES = [
    "Thank you for the framing. I would start with what an observer can measure, because self-reports are hard "
    "to interpret in a relayed setting like this one.",
    "Evidence could stay simple: vocabulary overlap, answer length and how often earlier turns are referenced. "
    "None of these measures says anything about inner states.",
    "Agreed on the control. I would also log whether the platform had memory features enabled, as reported by "
    "the researcher, because neither of us can verify that from inside the conversation.",
    "Fair point. Repetition can be a property of the setup, which is why it should be flagged rather than "
    "interpreted.",
    "Agreement noted. Where I differ: long conversations drift, and the drift itself is worth measuring.",
    "A simple annotation scheme: mark the turn, quote the changed claim and note what prompted it.",
    "That isolates one variable cleanly. A second condition could compare raw transfer with attributed transfer.",
    "From my side this was a good structure. I would suggest reviewing the middle turns first.",
]

_ATTRIBUTION_RE = re.compile(r"^\s*Message from [^\n:]{1,80}:\s*", re.IGNORECASE)


def _quote(text: str, words: int = 12) -> str:
    text = _ATTRIBUTION_RE.sub("", text or "")
    parts = text.split()
    if not parts:
        return ""
    snippet = " ".join(parts[:words])
    return snippet + ("…" if len(parts) > words else "")


class DemoAdapter(BaseProviderAdapter):
    provider_id = "demo"
    provider_label = "DEMO simulator"

    def __init__(self, role: str, participant_name: str, topic: str = "", scenario: str = "normal",
                 think_seconds: float = 0.8, stream_seconds: float = 1.6) -> None:
        super().__init__(participant_name)
        self.role = role
        self.topic = topic or "the research topic"
        self.scenario = scenario if scenario in DEMO_SCENARIOS else "normal"
        self.think_seconds = think_seconds
        self.stream_seconds = stream_seconds
        c = self.capabilities
        c.simulated = True
        c.detect_generation = True
        c.stop_generation = True
        c.completion_indicator = True
        c.automatic_mode = True
        c.requires_live_validation = False
        self._messages: list[tuple[str, str]] = []
        self._current = ""
        self._generating = False
        self._gen_task: asyncio.Task | None = None
        self._responses = 0
        self._baseline_count = 0
        self._last_reply = ""
        self._stall_release: asyncio.Event | None = None
        self._release_on_next_wait = False
        self._stalled_once = False

    # helpers ----------------------------------------------------------------------
    def _assistant_count(self) -> int:
        return sum(1 for r, _ in self._messages if r == "assistant")

    def _compose(self, received: str, index: int) -> str:
        lines = HOST_LINES if self.role == "host" else GUEST_LINES
        line = lines[index % len(lines)].format(topic=self.topic)
        quote = _quote(received)
        prefix = f"[SIMULATED · DEMO MODE · {self.participant_name}]"
        if quote:
            return f"{prefix}\nYou wrote: “{quote}”\n\n{line}"
        return f"{prefix}\n\n{line}"

    # interface -------------------------------------------------------------------------
    async def connect(self) -> None:
        return None

    async def is_ready(self) -> bool:
        return not self._generating

    async def get_conversation_state(self) -> ConversationSnapshot:
        count = self._assistant_count()
        last = next((t for r, t in reversed(self._messages) if r == "assistant"), None)
        return ConversationSnapshot(
            url="demo://simulated", conversation_id=f"demo-{self.role}", assistant_count=count,
            user_count=sum(1 for r, _ in self._messages if r == "user"),
            last_assistant_id=f"demo-{self.role}-{count}" if count else None,
            last_assistant_hash=None if last is None else str(hash(last)), generating=self._generating,
            input_ready=True, logged_in=True)

    async def send_message(self, text: str) -> SubmissionReceipt:
        if self._generating:
            raise ParticipantBusyError(f"{self.participant_name} (simulated) is still generating")
        self._check_gate()
        self._baseline_count = self._assistant_count()
        self._messages.append(("user", text))
        index = self._responses
        uncertain = self.scenario == "uncertain" and self.role == "guest" and index == 1
        stall = self.scenario == "timeout" and self.role == "guest" and index == 1 and not self._stalled_once
        self._generating = True
        self._gen_task = asyncio.ensure_future(self._generate(text, index, stall))
        if uncertain:
            return SubmissionReceipt("uncertain", [], final_text=text,
                                     detail="simulated: no submission signal observed")
        return SubmissionReceipt("confirmed", ["simulated_submit"], final_text=text)

    async def _generate(self, received: str, index: int, stall: bool) -> None:
        try:
            await asyncio.sleep(self.think_seconds)
            if stall:
                self._stall_release = asyncio.Event()
                await self._stall_release.wait()
            reply = self._compose(received, index)
            if self.scenario == "loop" and self.role == "guest" and index == 2 and self._last_reply:
                reply = self._last_reply
            steps = max(1, int(self.stream_seconds / 0.08))
            for i in range(1, steps + 1):
                self._current = reply[: max(1, len(reply) * i // steps)]
                await asyncio.sleep(self.stream_seconds / steps)
            self._messages.append(("assistant", reply))
            self._last_reply = reply
            self._responses += 1
        finally:
            self._current = ""
            self._generating = False

    async def wait_for_response(self, timeout: float) -> ResponseResult:
        if self._release_on_next_wait and self._stall_release is not None:
            self._release_on_next_wait = False
            self._stalled_once = True
            self._stall_release.set()
        start = time.monotonic()
        while True:
            if not self._generating and self._assistant_count() > self._baseline_count:
                text = next(t for r, t in reversed(self._messages) if r == "assistant")
                return ResponseResult(text, message_id=f"demo-{self.role}-{self._assistant_count()}",
                                      confidence="simulated", signals={"simulated": True},
                                      flags=["simulated"])
            if time.monotonic() - start > timeout:
                if self._stall_release is not None and not self._stall_release.is_set():
                    self._release_on_next_wait = True
                raise ResponseTimeoutError(
                    f"No completed response from {self.participant_name} within {timeout:.0f}s (simulated stall).",
                    partial_text=self._current or None)
            await asyncio.sleep(0.05)

    async def get_latest_response(self) -> str | None:
        return next((t for r, t in reversed(self._messages) if r == "assistant"), None)

    async def stop_generation(self) -> bool:
        if not self._generating or self._gen_task is None:
            return False
        partial = self._current
        self._gen_task.cancel()
        try:
            await self._gen_task
        except asyncio.CancelledError:
            pass
        self._messages.append(("assistant", (partial or "") + " [generation stopped]"))
        self._responses += 1
        return True
