"""In-memory chat page implementing the PageDriver protocol (exact-selector mapping)."""

from __future__ import annotations

import asyncio

from adapters.errors import AdapterError, BrowserClosedError
from adapters.registry import ProviderConfig

SEL = {
    "input": "#prompt",
    "send": "button[data-testid=send]",
    "assistant": "article[data-role=assistant]",
    "user": "article[data-role=user]",
    "generating": "button[data-testid=stop]",
    "completion": ".msg-actions",
    "login": "#login-wall",
    "alert": "[role=alert]",
}


def fake_config(with_generation: bool = True, with_completion: bool = True, **extra) -> ProviderConfig:
    return ProviderConfig(
        id="fake", label="FakeChat", url="fake://chat",
        selectors={
            "input": ["#does-not-exist", SEL["input"]],          # first candidate fails -> fallback
            "send_button": [SEL["send"]],
            "assistant_message": [".nope", SEL["assistant"]],
            "user_message": [SEL["user"]],
            "generating": [SEL["generating"]] if with_generation else [],
            "stop_button": [SEL["generating"]] if with_generation else [],
            "completion_indicator": [SEL["completion"]] if with_completion else [],
            "login_required": [SEL["login"]],
            "error_banner": [SEL["alert"]],
        },
        message_id_attributes=["data-message-id"], conversation_id_patterns=[r"conv=(\w+)"],
        rate_limit_text_patterns=["rate limit"], stability_ms=80, poll_ms=20, submit_verify_seconds=0.6,
        **extra)


class FakeChatPage:
    def __init__(self, existing: int = 0, ignore_submit: bool = False, steps: int = 3, step_s: float = 0.03,
                 show_generation: bool = True, login: bool = False, rate_limit_after: int | None = None,
                 reply=lambda n, text: f"Fake reply {n} to: {text[:30]}") -> None:
        self.messages: list[dict] = []
        self.input_text = ""
        self.generating = False
        self.closed = False
        self.ignore_submit = ignore_submit
        self.steps, self.step_s = steps, step_s
        self.show_generation = show_generation
        self.login = login
        self.rate_limit_after = rate_limit_after
        self.alerts: list[str] = []
        self.reply = reply
        self.replies = 0
        self.clicks = 0
        self._next_id = 1
        self._task: asyncio.Task | None = None
        for k in range(existing):
            self._add("user", f"Earlier question {k}")
            self._add("assistant", f"Earlier answer {k}", done=True)

    def _add(self, role: str, text: str, done: bool = False) -> dict:
        msg = {"role": role, "id": f"m{self._next_id}", "text": text, "done": done}
        self._next_id += 1
        self.messages.append(msg)
        return msg

    def _of(self, role: str) -> list[dict]:
        return [m for m in self.messages if m["role"] == role]

    def _kind(self, selector: str) -> str | None:
        for k, v in SEL.items():
            if v == selector:
                return k
        return None

    def _guard(self) -> None:
        if self.closed:
            raise BrowserClosedError("fake page closed")

    async def count(self, selector: str) -> int:
        self._guard()
        k = self._kind(selector)
        if k == "assistant":
            return len(self._of("assistant"))
        if k == "user":
            return len(self._of("user"))
        if k == "completion":
            return sum(1 for m in self._of("assistant") if m["done"])
        if k == "generating":
            return 1 if (self.generating and self.show_generation) else 0
        if k == "input" or k == "send":
            return 0 if self.login else 1
        if k == "login":
            return 1 if self.login else 0
        if k == "alert":
            return len(self.alerts)
        return 0

    async def any_visible(self, selector: str) -> bool:
        return await self.count(selector) > 0

    async def first_visible_enabled(self, selector: str) -> bool:
        if self._kind(selector) == "send":
            return bool(self.input_text.strip()) and not self.generating and not self.login
        return await self.any_visible(selector)

    async def extract_text(self, selector: str, index: int, exclude: list[str], mode: str = "markdown") -> str:
        self._guard()
        if self._kind(selector) != "assistant":
            raise AdapterError("not a message selector")
        return self._of("assistant")[index]["text"]

    async def get_attribute(self, selector: str, index: int, name: str) -> str | None:
        self._guard()
        if self._kind(selector) == "assistant" and name == "data-message-id":
            return self._of("assistant")[index]["id"]
        return None

    async def fill(self, selector: str, text: str, method: str = "fill") -> None:
        self._guard()
        self.input_text = text

    async def read_input(self, selector: str) -> str:
        self._guard()
        return self.input_text

    async def click(self, selector: str) -> None:
        self._guard()
        k = self._kind(selector)
        if k == "send":
            self.clicks += 1
            self._submit()
        elif k == "generating" and self._task:
            self._task.cancel()

    async def press(self, selector: str, key: str) -> None:
        self._guard()
        if key == "Enter":
            self.clicks += 1
            self._submit()

    def _submit(self) -> None:
        if self.ignore_submit or not self.input_text.strip():
            return
        text = self.input_text
        self._add("user", text)
        self.input_text = ""
        if self.rate_limit_after is not None and self.replies >= self.rate_limit_after:
            self.alerts.append("You hit the rate limit. Try again later.")
            return
        self._task = asyncio.ensure_future(self._stream(text))

    async def _stream(self, text: str) -> None:
        self.generating = True
        msg = self._add("assistant", "")
        full = self.reply(self.replies, text)
        try:
            for i in range(1, self.steps + 1):
                await asyncio.sleep(self.step_s)
                msg["text"] = full[: len(full) * i // self.steps]
        finally:
            msg["done"] = True
            self.generating = False
            self.replies += 1

    async def texts(self, selector: str, limit: int = 5) -> list[str]:
        self._guard()
        return self.alerts[:limit] if self._kind(selector) == "alert" else []

    async def highlight(self, selector: str, color: str = "") -> int:
        return await self.count(selector)

    async def url(self) -> str:
        return "fake://chat?conv=abc123"

    def is_closed(self) -> bool:
        return self.closed

    async def bring_to_front(self) -> None:
        return None
